# KM-Lone

A small Python terminal assistant: open applications, find materials and extract
key sentences from a selected result. Python 3.10+; Python standard library only.

## Run in VS Code Terminal

Open the KM-Lone folder in VS Code, then run:

```powershell
python -B main.py
```

On this computer, if `python` is not on PATH:

```powershell
& "C:\Users\Hi\anaconda3\python.exe" -B main.py
```

Example interaction (type the commands after the prompt):

```text
你： Can you help me to get the materials about Neural Network?
KM-Lone: ... numbered links ...
你： summarise 3
KM-Lone: Reading the selected material...
KM-Lone: Summary of ...
Source: ...
Read: ...
Extractive summary: key sentences from the source, in its original language. No AI rewriting.
...
你： summarise https://github.com/OWNER/REPOSITORY
你： exit
```

Replace the URL above with a link actually shown in your latest search.
`summarize 3`, `Can you summarise link 3?`, `summary of 3`, and `总结3` also work.
Numbers run consecutively across both result groups (normally 1–5 and 6–10).
If there are fewer results, choose any displayed number.

## What the summary reads

| Resource from search | Content read through its public API |
| --- | --- |
| GitHub repository | Rendered README, with code blocks omitted |
| Stack Overflow question | Question and up to three top-voted answers; code blocks omitted |
| OpenAlex/DOI research work | Indexed abstract only, not the full paper |

This is an **extractive summary**: up to four original sentences selected by
recurring words, title overlap and a preference for earlier sentences, displayed in their source order. It does not
translate, rewrite, check the author's claims, or answer arbitrary follow-up
questions. A short source may produce fewer points. Questions and answers may
contain differing opinions; the result is a selection of their text, not a
verified answer. Very long content is limited to its first 60,000 characters,
with a visible notice.

If the source requires access, reaches its API quota, has no README/abstract, or
contains insufficient prose, KM-Lone explains the problem. It does not invent a
summary from a title or search snippet. This first version supports the three
sources above; arbitrary websites, PDFs and Google search are not integrated.

Selection and successful summaries are kept only in memory until the next
search or exit. Repeating a summary in that interval reuses it. A new search
replaces the numbered list, even if it returns no results. Failed reads can be
retried. The input prompt is always `你： `.

## Files and small-module layout

- `main.py`: terminal input, the latest result list and session summary cache.
- `findmicrosoftapp.py`: existing Office application lookup.
- `material_search.py`: search and display; consecutive result numbering.
- `material_summary.py`: command parsing, result selection, public API reads,
  text cleanup, key-sentence extraction and summary formatting.
- `tests/test_material_search.py`: existing search tests.
- `tests/test_material_summary.py`: summary and terminal workflow tests.

All summary network requests use fixed HTTPS API hosts and have a 12-second
timeout and a 2 MB response/decompression limit. No API keys or LLM are used.
Only a resource identifier is sent to its public API. Page links, code and
instructions are not executed; redirects to arbitrary hosts are not followed.
Public API limits/backoff are reported without automatic repeated requests.

## Verify and debug

```powershell
python -B -m unittest discover -s tests -v
```

Tests use mocked content and do not need network access or launch applications.
For a real check, search a topic, summarise a numbered result, then summarise the
same result by URL. Try an out-of-range number and a new search as well.

To enable the existing local debug log:

```powershell
$env:KM_LONE_DEBUG = "1"
python -B main.py
```

`km_lone_debug.log` is excluded from Git. Summary diagnostics record source,
content length and timing; the existing search logger can record search topics
on failures, so check logs before sharing them.

API references: [GitHub README](https://docs.github.com/en/rest/repos/contents#get-a-repository-readme),
[Stack Exchange questions](https://api.stackexchange.com/docs/questions-by-ids),
[answers](https://api.stackexchange.com/docs/answers-on-questions),
[OpenAlex works](https://help.openalex.org/data/works/).
