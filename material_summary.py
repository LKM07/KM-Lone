"""Read the current search sources and extract key sentences, without an LLM.

Public entry points: extract_summary_target, resolve_material,
summarise_material, format_summary. Importing this module never makes requests.
"""

from __future__ import annotations

import gzip
import io
import json
import logging
import math
import re
import time
import unicodedata
from collections import Counter
from dataclasses import dataclass
from html.parser import HTMLParser
from http.client import HTTPException
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urlsplit, urlunsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

from material_search import Material, SearchReport


LOGGER = logging.getLogger(__name__)
TIMEOUT = 12
MAX_BYTES = 2_000_000
MAX_TEXT = 60_000
API_HOSTS = {"api.github.com", "api.stackexchange.com", "api.openalex.org"}
_cooldowns: dict[str, float] = {}
STOP_WORDS = set("""a an and are as at be been being but by can could did do does
for from had has have how i if in into is it its may more most not of on one or
our out should so some than that the their them then there these they this those
to use used using was we were what when where which who will with would you your
also about all any each other such through very""".split())


class SummaryError(Exception):
    """An expected reading/summary failure that the terminal can explain."""


@dataclass(frozen=True)
class Summary:
    title: str
    url: str
    scope: str
    points: list[str]
    notes: tuple[str, ...] = ()


def extract_summary_target(command: str) -> str | None:
    """Return a number/URL, '' for a missing target, or None for another command."""
    match = re.fullmatch(
        r"\s*(?:(?:can|could|would) you (?:please )?(?:help me (?:to )?)?|"
        r"please |(?:give|show) me (?:a )?)?"
        r"(?:summari[sz]e\b|summary\b(?:\s+(?:of|for)\b)?|总结|摘要)\s*(.*?)\s*",
        command, flags=re.IGNORECASE,
    )
    if not match:
        return None
    target = match.group(1).strip()
    # Natural-language question marks are removed only around numbered targets;
    # URL paths and query strings must retain their original case and punctuation.
    number = re.fullmatch(r"(?:link\s*|第\s*)?#?([0-9]+)(?:\s*个(?:链接)?)?[?.!？。！]?", target, re.I)
    return number.group(1) if number else target


def _url_key(value: str) -> str:
    parts = urlsplit(value)
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path.rstrip("/"), parts.query, ""))


def resolve_material(target: str, report: SearchReport | None) -> Material:
    """Only select links actually displayed by the latest search in this session."""
    materials = report.popular + report.recent if report else []
    if not materials:
        raise SummaryError("Search for materials first, then enter 'summarise 3'.")
    if not target:
        raise SummaryError("Include a result number or a displayed link, e.g. 'summarise 3'.")
    if target.isascii() and target.isdigit():
        if len(target) <= 3 and 1 <= int(target) <= len(materials):
            return materials[int(target) - 1]
        raise SummaryError(f"Choose a result number from 1 to {len(materials)}.")
    try:
        key = _url_key(target)
        for material in materials:
            if _url_key(material.url) == key:
                return material
    except ValueError:
        pass
    raise SummaryError("That link is not in the latest search results. Copy one of the displayed links.")


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _fetch(url: str, accept: str = "application/json") -> str:
    """Read only fixed public API hosts; do not follow URLs supplied by a page."""
    parts = urlsplit(url)
    if (parts.scheme != "https" or parts.hostname not in API_HOSTS or
            parts.username or parts.password or parts.port not in (None, 443)):
        raise SummaryError("Unsupported content endpoint.")
    host = parts.hostname
    remaining = _cooldowns.get(host, 0) - time.monotonic()
    if remaining > 0:
        raise SummaryError(f"{host} requested a pause. Try again in {math.ceil(remaining)} seconds.")
    request = Request(url, headers={
        "Accept": accept, "Accept-Encoding": "gzip",
        "User-Agent": "KM-Lone/0.4 MaterialSummary",
    })
    try:
        # No credentials, environment proxies or automatic cross-host redirects.
        with build_opener(ProxyHandler({}), _NoRedirect()).open(request, timeout=TIMEOUT) as response:
            raw = response.read(MAX_BYTES + 1)
            if len(raw) > MAX_BYTES:
                raise SummaryError("The source response is too large to summarise safely.")
            if response.headers.get("Content-Encoding", "").lower() == "gzip":
                with gzip.GzipFile(fileobj=io.BytesIO(raw)) as compressed:
                    raw = compressed.read(MAX_BYTES + 1)
                if len(raw) > MAX_BYTES:
                    raise SummaryError("The expanded source response is too large.")
            charset = response.headers.get_content_charset() or "utf-8"
            return raw.decode(charset, errors="replace")
    except HTTPError as error:
        with error:
            if error.code in (403, 429):
                delay = error.headers.get("Retry-After", "60")
                seconds = int(delay) if delay.isdigit() else 60
                reset = error.headers.get("X-RateLimit-Reset", "")
                if reset.isdigit():
                    seconds = max(seconds, int(reset) - int(time.time()))
                _cooldowns[host] = time.monotonic() + max(1, seconds)
            message = {
                401: "This content requires access permission.",
                403: "The source denied access or its public API quota was reached.",
                404: "No readable content was found at this source.",
                429: "The source rate limit was reached; please try later.",
            }.get(error.code, f"The source returned HTTP {error.code}.")
        raise SummaryError(message) from error
    except (URLError, OSError, LookupError, ValueError, EOFError, HTTPException) as error:
        LOGGER.debug("Content read failed: host=%s error=%s", host, type(error).__name__)
        raise SummaryError("Could not read the source. Check your connection and try again.") from error


def _json(url: str) -> dict:
    try:
        payload = json.loads(_fetch(url))
    except (ValueError, TypeError) as error:
        raise SummaryError("The source returned an unreadable response.") from error
    if not isinstance(payload, dict):
        raise SummaryError("The source returned an unexpected response format.")
    delay = payload.get("backoff")
    if isinstance(delay, int) and delay > 0:
        _cooldowns[urlsplit(url).hostname] = time.monotonic() + delay
    if payload.get("error_id"):
        raise SummaryError("The source API could not provide this content.")
    return payload


def terminal_text(value: str) -> str:
    """Prevent retrieved text from injecting terminal control sequences."""
    return "".join(c for c in value if c in "\n\t" or not unicodedata.category(c).startswith("C"))


class _BodyText(HTMLParser):
    """Extract prose from API-rendered HTML; omit scripts, navigation and code blocks."""
    SKIP = {"script", "style", "nav", "footer", "form", "noscript", "svg", "pre"}
    BLOCK = {"p", "li", "div", "section", "article", "h1", "h2", "h3", "h4", "tr", "br"}
    VOID = {"br", "hr", "img", "input", "meta", "link", "wbr", "source", "area", "embed"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.stack: list[tuple[str, bool]] = []

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        skip = (bool(self.stack and self.stack[-1][1]) or tag in self.SKIP or
                "hidden" in attributes or attributes.get("aria-hidden") == "true")
        if tag in self.BLOCK and not skip:
            self.parts.append("\n")
        if tag not in self.VOID:
            self.stack.append((tag, skip))

    def handle_endtag(self, tag):
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index][0] == tag:
                del self.stack[index:]
                break
        if tag in self.BLOCK and not (self.stack and self.stack[-1][1]):
            self.parts.append("\n")

    def handle_data(self, data):
        if not (self.stack and self.stack[-1][1]):
            # Source-code line wrapping inside <p> is not a sentence boundary.
            self.parts.append(re.sub(r"\s+", " ", data))


def html_to_text(content: str) -> str:
    parser = _BodyText()
    parser.feed(content)
    parser.close()
    return "\n".join(line for part in "".join(parser.parts).splitlines()
                     if (line := " ".join(terminal_text(part).split())))


def _read_material(material: Material) -> tuple[str, str, tuple[str, ...]]:
    """Use the official API for each existing search source, not arbitrary URLs."""
    parts = urlsplit(material.url)
    if parts.scheme != "https" or parts.username or parts.password or parts.port not in (None, 443):
        raise SummaryError("Only public HTTPS resource links are supported.")
    host = parts.hostname
    path = parts.path.rstrip("/")
    if host == "github.com" and re.fullmatch(r"/[\w.-]+/[\w.-]+", path):
        body = _fetch(f"https://api.github.com/repos{path}/readme", "application/vnd.github.html+json")
        return html_to_text(body), "Repository README only", ()

    question = re.match(r"/questions/([0-9]+)(?:/|$)", path)
    if host == "stackoverflow.com" and question:
        base = f"https://api.stackexchange.com/2.3/questions/{question.group(1)}"
        params = urlencode({"site": "stackoverflow", "filter": "withbody"})
        payload = _json(f"{base}?{params}")
        items = payload.get("items", [])
        if not items:
            raise SummaryError("This question is no longer publicly available.")
        text = html_to_text(items[0].get("body", ""))
        try:
            answers = _json(f"{base}/answers?{params}&sort=votes&order=desc&pagesize=3")
            # Prefer answers as the explanatory material; retain the question for context.
            answer_text = "\n".join(html_to_text(answer.get("body", ""))
                                    for answer in answers.get("items", []))
        except SummaryError as error:
            return text, "Question body only", (f"Answers unavailable: {error}",)
        if answer_text.strip():
            return answer_text + "\n" + text, "Question and up to 3 top-voted answers (code blocks omitted)", ()
        return text, "Question body only; no readable answer text", ()

    if host in {"doi.org", "openalex.org"}:
        if host == "doi.org" and re.fullmatch(r"/10\.[0-9]{4,9}/.+", path):
            identifier = "https://doi.org" + path
        elif host == "openalex.org" and re.fullmatch(r"/W[0-9]+", path, re.I):
            identifier = path[1:]
        else:
            raise SummaryError("This research link has an unsupported identifier.")
        work = _json("https://api.openalex.org/works/" + quote(identifier, safe=""))
        inverted = work.get("abstract_inverted_index")
        if not isinstance(inverted, dict) or not inverted:
            raise SummaryError("OpenAlex has no readable abstract for this paper. A title alone is not enough to summarise.")
        positions = {}
        for word, offsets in inverted.items():
            if isinstance(word, str) and isinstance(offsets, list):
                for offset in offsets:
                    if isinstance(offset, int) and 0 <= offset < MAX_TEXT:
                        positions[offset] = word
        return " ".join(positions[index] for index in sorted(positions)), "Paper abstract only; full paper not read", ()
    raise SummaryError("This version reads GitHub repository READMEs, Stack Overflow questions and OpenAlex paper abstracts.")


def _tokens(text: str) -> list[str]:
    # Underscore-separated identifiers are code, not recurring prose keywords.
    words = re.findall(r"\b[a-zA-Z][a-zA-Z'-]{1,}\b|[\u4e00-\u9fff]", text.lower())
    return [word for word in words if word not in STOP_WORDS]


def extract_key_sentences(text: str, title: str = "", count: int = 4) -> list[str]:
    """Rank prose sentences by recurring words/title overlap; retain source order."""
    sentences = []
    seen = set()
    for part in re.split(r"(?<=[.!?])\s+|(?<=[。！？])|\n+", terminal_text(text)):
        sentence = " ".join(part.split())
        key = sentence.casefold()
        prose_words = re.findall(r"\b[A-Za-z][A-Za-z'-]*\b", sentence)
        chinese_chars = re.findall(r"[\u4e00-\u9fff]", sentence)
        is_prose = len(prose_words) >= 5 or len(chinese_chars) >= 15
        complete = sentence.endswith((".", "!", "?", "。", "！", "？"))
        config_row = re.match(r"^[A-Z][A-Z0-9]*_[A-Z0-9_]+(?:\s|$)", sentence)
        if (25 <= len(sentence) <= 600 and key not in seen and is_prose and complete
                and not config_row and _tokens(sentence)):
            seen.add(key)
            sentences.append(sentence)
    if not sentences:
        raise SummaryError("There is not enough readable prose to extract a useful summary.")
    tokens = [_tokens(sentence) for sentence in sentences]
    frequency = Counter(word for words in tokens for word in words)
    title_words = set(_tokens(title))
    scores = [(sum(frequency[word] for word in set(words)) / math.sqrt(len(words))
               + 2 * len(set(words) & title_words)) * (1 + 1 / math.sqrt(index + 1))
              for index, words in enumerate(tokens)]
    chosen = []
    for index in sorted(range(len(sentences)), key=lambda i: (-scores[i], i)):
        words = set(tokens[index])
        if any(len(words & set(tokens[old])) / max(1, len(words | set(tokens[old]))) > 0.8 for old in chosen):
            continue
        chosen.append(index)
        if len(chosen) >= max(1, count):
            break
    return [sentences[index] for index in sorted(chosen)]


def summarise_material(material: Material) -> Summary:
    started = time.monotonic()
    try:
        text, scope, notes = _read_material(material)
        if len(text) > MAX_TEXT:
            notes += (f"Long source: analysed only the first {MAX_TEXT:,} characters.",)
            text = text[:MAX_TEXT].rsplit("\n", 1)[0] if "\n" in text[:MAX_TEXT] else text[:MAX_TEXT]
        points = extract_key_sentences(text, material.title)
        LOGGER.debug("Summary ready: source=%s chars=%s points=%s seconds=%.2f",
                     material.source, len(text), len(points), time.monotonic() - started)
        return Summary(material.title, material.url, scope, points, notes)
    except (ValueError, TypeError, KeyError, AttributeError) as error:
        LOGGER.debug("Unexpected source format: source=%s error=%s", material.source, type(error).__name__)
        raise SummaryError("This source returned content in an unsupported format.") from error


def format_summary(summary: Summary) -> str:
    lines = [f"KM-Lone: Summary of {summary.title}", f"Source: {summary.url}",
             f"Read: {summary.scope}",
             "Extractive summary: key sentences from the source, in its original language. No AI rewriting.", ""]
    lines.extend(f"- {point}" for point in summary.points)
    lines.extend(f"Note: {note}" for note in summary.notes)
    return terminal_text("\n".join(lines))
