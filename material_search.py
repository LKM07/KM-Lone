"""Public-API material search for the KM-Lone terminal assistant.

This module deliberately uses only documented, public endpoints.  It does not
scrape Google results pages, sign in to websites, or try to bypass a CAPTCHA.
"""

from __future__ import annotations

import html
import json
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


LOGGER = logging.getLogger(__name__)
REQUEST_TIMEOUT_SECONDS = 12
RESULTS_PER_SOURCE = 20
USER_AGENT = "KM-Lone/0.3 MaterialSearch (educational terminal assistant)"


@dataclass(frozen=True)
class Material:
    """One public resource returned by a search source."""

    title: str
    url: str
    source: str
    engagement_count: int
    engagement_label: str
    published_at: datetime | None
    description: str = ""


@dataclass(frozen=True)
class SearchReport:
    """The selected results plus enough status information to debug a search."""

    topic: str
    popular: list[Material]
    recent: list[Material]
    sources_used: list[str]
    errors: list[str]


def enable_debug_logging(log_path: str | Path = "km_lone_debug.log") -> None:
    """Write module diagnostics to a local file when debugging is explicitly on."""

    logging.basicConfig(
        filename=log_path,
        level=logging.DEBUG,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        force=True,
    )


def extract_material_topic(user_text: str) -> str | None:
    """Recognise a small, predictable set of terminal search requests.

    This is intentionally rule based for now: a user does not need an API key
    or an LLM merely to turn a request into a search query.
    """

    text = " ".join(user_text.strip().split())
    if not text:
        return None

    patterns = (
        r"(?:materials?|resources?)\s+(?:about|on|for)\s+(.+)",
        r"^(?:search|find)\s+(?:for\s+)?(.+)",
        r"\b(?:search|find)\s+(?:for\s+)?(.+)",
    )

    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            topic = match.group(1).strip(" .?!")
            topic = re.sub(r"^(?:the\s+)?(?:materials?|resources?)\s+(?:about|on|for)\s+", "", topic, flags=re.IGNORECASE)
            if topic:
                return topic

    return None


def search_materials(topic: str) -> SearchReport:
    """Search several legal public sources and choose popular and recent links."""

    cleaned_topic = " ".join(topic.split())
    if not cleaned_topic:
        raise ValueError("Please include a topic to search for.")

    all_materials: list[Material] = []
    sources_used: list[str] = []
    errors: list[str] = []

    for source_name, search_source in (
        ("OpenAlex", _search_openalex),
        ("GitHub", _search_github),
        ("Stack Overflow", _search_stack_overflow),
    ):
        try:
            materials = search_source(cleaned_topic)
        except (HTTPError, URLError, TimeoutError, ValueError, json.JSONDecodeError) as error:
            LOGGER.debug("%s search failed for %r", source_name, cleaned_topic, exc_info=True)
            errors.append(f"{source_name}: {error}")
            continue

        if materials:
            all_materials.extend(materials)
            sources_used.append(source_name)

    unique_materials = _deduplicate(all_materials)
    popular, recent = select_materials(unique_materials)
    return SearchReport(cleaned_topic, popular, recent, sources_used, errors)


def select_materials(materials: list[Material], count: int = 5) -> tuple[list[Material], list[Material]]:
    """Select up to ``count`` popular and ``count`` newly published unique items."""

    now = datetime.now(timezone.utc)
    # Indexes occasionally contain planned or incorrectly dated publications.
    # A future record cannot honestly be presented as a newly published result.
    materials = [
        material
        for material in materials
        if material.published_at is None or material.published_at <= now
    ]

    popular = sorted(
        materials,
        key=lambda material: (material.engagement_count, material.published_at or datetime.min.replace(tzinfo=timezone.utc)),
        reverse=True,
    )[:count]
    popular_urls = {material.url for material in popular}

    recent_candidates = [material for material in materials if material.url not in popular_urls]
    recent = sorted(
        recent_candidates,
        key=lambda material: material.published_at or datetime.min.replace(tzinfo=timezone.utc),
        reverse=True,
    )[:count]
    return popular, recent


def format_material_report(report: SearchReport) -> str:
    """Return a terminal-friendly report without hiding source-specific metrics."""

    lines = [f'KM-Lone: Materials about "{report.topic}"']

    if report.popular:
        lines.extend((
            "",
            "Most attention",
            "(Public APIs do not provide one comparable visitor count. The metric shown is views, stars, or citations from each source.)",
        ))
        lines.extend(_format_item(index, material) for index, material in enumerate(report.popular, start=1))

    if report.recent:
        lines.extend(("", "Newest published"))
        lines.extend(_format_item(index, material) for index, material in enumerate(report.recent, start=1))

    if not report.popular and not report.recent:
        lines.extend(("", "No public results were returned. Try a more specific topic."))

    if report.sources_used:
        lines.extend(("", f"Sources used: {', '.join(report.sources_used)}."))

    if report.errors:
        lines.extend(("", "Some sources were unavailable: " + "; ".join(report.errors)))

    return "\n".join(lines)


def _format_item(index: int, material: Material) -> str:
    date_text = material.published_at.date().isoformat() if material.published_at else "date unavailable"
    return (
        f"{index}. {material.title}\n"
        f"   {material.url}\n"
        f"   {material.source} | {material.engagement_count:,} {material.engagement_label} | {date_text}"
    )


def _search_openalex(topic: str) -> list[Material]:
    materials: list[Material] = []
    for sort in ("cited_by_count:desc", "publication_date:desc"):
        payload = _get_json(
            "https://api.openalex.org/works",
            {
                "search": topic,
                "per-page": RESULTS_PER_SOURCE,
                "sort": sort,
                "select": "id,display_name,doi,publication_date,cited_by_count,type",
            },
        )
        for work in payload.get("results", []):
            title = work.get("display_name")
            url = work.get("doi") or work.get("id")
            if not title or not url:
                continue
            materials.append(
                Material(
                    title=html.unescape(title),
                    url=url,
                    source="OpenAlex",
                    engagement_count=_as_nonnegative_int(work.get("cited_by_count")),
                    engagement_label="citations",
                    published_at=_parse_date(work.get("publication_date")),
                    description=f"Research work ({work.get('type', 'unknown type')})",
                )
            )
    return materials


def _search_github(topic: str) -> list[Material]:
    payload = _get_json(
        "https://api.github.com/search/repositories",
        {"q": topic, "sort": "stars", "order": "desc", "per_page": RESULTS_PER_SOURCE},
    )
    materials: list[Material] = []
    for repository in payload.get("items", []):
        title = repository.get("full_name")
        url = repository.get("html_url")
        if not title or not url:
            continue
        materials.append(
            Material(
                title=title,
                url=url,
                source="GitHub",
                engagement_count=_as_nonnegative_int(repository.get("stargazers_count")),
                engagement_label="stars",
                published_at=_parse_datetime(repository.get("created_at")),
                description=repository.get("description") or "",
            )
        )
    return materials


def _search_stack_overflow(topic: str) -> list[Material]:
    materials: list[Material] = []
    for sort in ("votes", "creation"):
        payload = _get_json(
            "https://api.stackexchange.com/2.3/search/advanced",
            {
                "site": "stackoverflow",
                "q": topic,
                "sort": sort,
                "order": "desc",
                "pagesize": RESULTS_PER_SOURCE,
            },
        )
        for question in payload.get("items", []):
            title = question.get("title")
            url = question.get("link")
            if not title or not url:
                continue
            materials.append(
                Material(
                    title=html.unescape(title),
                    url=url,
                    source="Stack Overflow",
                    engagement_count=_as_nonnegative_int(question.get("view_count")),
                    engagement_label="views",
                    published_at=_parse_unix_timestamp(question.get("creation_date")),
                    description="Question and answers",
                )
            )
    return materials


def _get_json(url: str, params: dict[str, Any]) -> dict[str, Any]:
    request = Request(
        f"{url}?{urlencode(params)}",
        headers={"Accept": "application/json", "User-Agent": USER_AGENT},
    )
    with urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
        charset = response.headers.get_content_charset() or "utf-8"
        return json.loads(response.read().decode(charset))


def _deduplicate(materials: list[Material]) -> list[Material]:
    """Keep the strongest copy when an API returns the same URL twice."""

    unique: dict[str, Material] = {}
    for material in materials:
        key = material.url.rstrip("/").lower()
        existing = unique.get(key)
        if existing is None or material.engagement_count > existing.engagement_count:
            unique[key] = material
    return list(unique.values())


def _parse_date(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _parse_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _parse_unix_timestamp(value: Any) -> datetime | None:
    try:
        return datetime.fromtimestamp(int(value), tz=timezone.utc)
    except (TypeError, ValueError, OSError):
        return None


def _as_nonnegative_int(value: Any) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0
