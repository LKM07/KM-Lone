# KM-Lone

A small Python terminal assistant: open applications, find materials and extract
key sentences from a selected result, using typing or optional offline voice input.
Python 3.10+. Keyboard features use the standard library; voice has optional dependencies.

## Run in VS Code Terminal

Open the KM-Lone folder in VS Code, then run:

```powershell
python -B main.py
```

On this computer, the project virtual environment includes voice support:

```powershell
& ".\.venv\Scripts\python.exe" -B main.py
```

Example interaction (type the commands after the prompt):

```text
You: Can you help me to get the materials about Neural Network?
KM-Lone: ... numbered links ...
You: summarise 3
KM-Lone: Reading the selected material...
KM-Lone: Summary of ...
Source: ...
Read: ...
Extractive summary: key sentences from the source, in its original language. No AI rewriting.
...
You: summarise https://github.com/OWNER/REPOSITORY
You: exit
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
retried. The keyboard input prompt is `You: `; recognised voice is echoed as `You (voice): `.

## Free offline voice input

Voice uses the open-source multilingual Whisper **base** model through
faster-whisper on the CPU. No subscription, paid API, API key or recurring
service fee is required. The first setup downloads the model (about 145 MB);
subsequent recognition uses local files only. Ordinary searches still need an
internet connection. Audio is held in RAM for recognition, not saved by KM-Lone
or uploaded. Debug logs do not intentionally record microphone audio or
transcripts (the existing search logger can record the resulting search topic).

The environment and model have already been installed on this computer. Start
with the `.venv` command above, then type:

```text
You: voice
KM-Lone: Recording 8 seconds. Speak now. Ctrl+C cancels.
```

Say one command, for example:

- "Search materials about neural networks."
- "Summarise three." (after a search)
- "Open Chrome."
- "搜索神经网络。" or "总结第三个链接。"

Recognition ends after the recording window. It echoes the command and passes
it to the same search/summary/application logic as typing. No separate list or
summary history is created for voice. Enter `voice` again for another recording.
There is no continuous background listening, wake word or spoken reply in this version.
`Ctrl+C` while recording/recognising cancels voice and returns to keyboard input.
Speech recognition can make mistakes; keep commands short and check the echoed
text. The existing command rules still apply; voice is not a general AI conversation.

`voice` / `voice auto` detects the language. For short commands, `voice en` or
`voice zh` can be more reliable. `voice devices` lists microphones without
recording. An alternative input can be selected before launching KM-Lone:

```powershell
& ".\.venv\Scripts\python.exe" -B voice_input.py --devices
$env:KM_LONE_MIC_DEVICE = "1"  # Choose an input number actually listed above.
$env:KM_LONE_VOICE_SECONDS = "12"  # Optional: integer 3–30; default 8.
& ".\.venv\Scripts\python.exe" -B main.py
```

In VS Code, choose `.venv\Scripts\python.exe` with **Python: Select Interpreter**
if you want the Run button to use voice dependencies too. Running with another
Python that lacks the voice packages still supports typing.

### Installation on another computer

```powershell
python -m venv .venv
& ".\.venv\Scripts\python.exe" -m pip install -r requirements-voice.txt
& ".\.venv\Scripts\python.exe" -B voice_input.py --setup
& ".\.venv\Scripts\python.exe" -B voice_input.py --check
& ".\.venv\Scripts\python.exe" -B main.py
```

`--setup` (or `voice setup` in the terminal) is the explicit download step;
normal voice input will not silently download a missing model. `--check` loads
the local model and lists microphones but does not record. `.venv/` and
`.voice_models/` are excluded from Git; other contributors install their own copies.

If recording fails, check that a microphone works in Windows Sound Recorder,
that desktop applications have microphone access, and that the selected device
is an input. Audio errors `-9999`/`-9996` mean the audio backend could not open
the device; the native details are available with `KM_LONE_DEBUG=1`. Try another
listed microphone/host API in your own VS Code terminal. Do not select Stereo
Mix or a speaker loopback when you intend to use the microphone.

## Files and small-module layout

- `main.py`: terminal input, the latest result list and session summary cache.
- `findmicrosoftapp.py`: existing Office application lookup.
- `material_search.py`: search and display; consecutive result numbering.
- `material_summary.py`: command parsing, result selection, public API reads,
  text cleanup, key-sentence extraction and summary formatting.
- `voice_input.py`: model setup, microphone capture, offline transcription and
  a few spoken-command aliases (such as "summarise three" → `summarise 3`).
- `requirements-voice.txt`: optional voice dependency versions.
- `tests/test_material_search.py`: existing search tests.
- `tests/test_material_summary.py`: summary and terminal workflow tests.
- `tests/test_voice_input.py`: voice capture, cancellation, silence, local-only
  model loading, command conversion and shared terminal workflow tests.

All summary network requests use fixed HTTPS API hosts and have a 12-second
timeout and a 2 MB response/decompression limit. No API keys or LLM are used.
Only a resource identifier is sent to its public API. Page links, code and
instructions are not executed; redirects to arbitrary hosts are not followed.
Public API limits/backoff are reported without automatic repeated requests.

## Verify and debug

```powershell
python -B -m unittest discover -s tests -v
```

Tests use mocked content/audio and do not need network access, a model,
microphone access or application launches.
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

Voice references: [faster-whisper](https://github.com/SYSTRAN/faster-whisper),
[sounddevice](https://python-sounddevice.readthedocs.io/).
