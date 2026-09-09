"""Optional offline microphone input. Typing never imports audio/ML packages.

Run --setup once to download the multilingual base model, or --devices to list
microphones. Normal recognition loads local files only and keeps audio in RAM.
"""

from __future__ import annotations

import argparse
import io
import logging
import math
import os
import re
import threading
import unicodedata
import wave
from array import array
from pathlib import Path


LOGGER = logging.getLogger(__name__)
MODEL_DIR = Path(__file__).resolve().parent / ".voice_models" / "base"
REQUIRED_MODEL_FILES = ("model.bin", "config.json", "tokenizer.json")
INSTALL_HELP = "Use the project .venv Python, or install requirements-voice.txt in your selected Python."


class VoiceError(Exception):
    """A voice failure that should return control to keyboard input."""


def _sounddevice():
    try:
        import sounddevice
        return sounddevice
    except (ImportError, OSError) as error:
        raise VoiceError(f"Microphone support is not available. {INSTALL_HELP}") from error


def _whisper_class():
    # Imported only for explicit setup or voice input.
    os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
    os.environ.setdefault("HF_HOME", str(MODEL_DIR.parent / ".hub"))
    try:
        from faster_whisper import WhisperModel
        return WhisperModel
    except (ImportError, OSError) as error:
        raise VoiceError(f"Offline speech recognition is not available. {INSTALL_HELP}") from error


def setup_voice() -> None:
    """Explicit, one-time network operation; never records or sends any audio."""
    _whisper_class()
    from faster_whisper.utils import download_model
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    print("KM-Lone: Downloading the multilingual base speech model (about 145 MB)...", flush=True)
    try:
        download_model("base", output_dir=str(MODEL_DIR))
    except Exception as error:
        # Third-party HTTP backends expose different exception types.
        LOGGER.debug("Voice setup failed: %s", type(error).__name__)
        raise VoiceError("Model download did not finish. Check your connection and run 'voice setup' again.") from error
    if not all((MODEL_DIR / name).is_file() for name in REQUIRED_MODEL_FILES):
        raise VoiceError("The model download is incomplete. Run 'voice setup' again.")
    print("KM-Lone: Offline voice model is ready.")


def list_microphones() -> str:
    sd = _sounddevice()
    try:
        devices = sd.query_devices()
        default_input = sd.default.device[0]
    except Exception as error:
        raise VoiceError("Could not list microphones. Check your Windows audio settings.") from error
    lines = [f"{index}: {device['name']}" + (" [default]" if index == default_input else "")
             for index, device in enumerate(devices) if device['max_input_channels'] > 0]
    return "\n".join(lines) or "No microphone found. Connect one or enable microphone access in Windows."


def _seconds() -> int:
    try:
        value = int(os.getenv("KM_LONE_VOICE_SECONDS", "8"))
    except ValueError as error:
        raise VoiceError("KM_LONE_VOICE_SECONDS must be a whole number from 3 to 30.") from error
    if not 3 <= value <= 30:
        raise VoiceError("KM_LONE_VOICE_SECONDS must be from 3 to 30.")
    return value


def _device() -> int | None:
    value = os.getenv("KM_LONE_MIC_DEVICE", "").strip()
    if not value:
        return None
    if not value.isascii() or not value.isdigit():
        raise VoiceError("KM_LONE_MIC_DEVICE must be a microphone number from 'voice devices'.")
    if len(value) > 5:
        raise VoiceError("Choose a microphone number shown by 'voice devices'.")
    return int(value)


def record_audio(seconds: int, device: int | None = None) -> bytes:
    """Record a bounded mono PCM clip at the device's native rate into a WAV buffer."""
    if not 1 <= seconds <= 30:
        raise VoiceError("Recording duration must be between 1 and 30 seconds.")
    sd = _sounddevice()
    chunks = []
    received = 0
    done = threading.Event()
    overflow = False
    try:
        info = sd.query_devices(device, "input")
        rate = int(info["default_samplerate"])
        if info["max_input_channels"] < 1 or not 8_000 <= rate <= 192_000:
            raise VoiceError("The selected device is not a supported microphone.")
        sd.check_input_settings(device=device, channels=1, dtype="int16", samplerate=rate)
        limit = rate * seconds * 2

        def collect(data, frames, timing, status):
            nonlocal received, overflow
            overflow = overflow or bool(status)
            remaining = limit - received
            chunk = bytes(data)[:max(0, remaining)]
            if chunk:
                chunks.append(chunk)
                received += len(chunk)
            if received >= limit:
                done.set()
                raise sd.CallbackStop

        # Opening/closing this context is the entire lifetime of microphone use.
        with sd.RawInputStream(device=device, samplerate=rate, channels=1, dtype="int16", callback=collect):
            print(f"KM-Lone: Recording {seconds} seconds. Speak now. Ctrl+C cancels.", flush=True)
            done.wait(seconds + 2)
    except VoiceError:
        raise
    except Exception as error:
        LOGGER.debug("Microphone read failed: %s", error)
        code = error.args[1] if len(error.args) > 1 and isinstance(error.args[1], int) else None
        detail = f" Audio error {code}." if code is not None else ""
        raise VoiceError("Could not record." + detail + " Check the microphone, Windows microphone access, or 'voice devices'.") from error
    if overflow:
        raise VoiceError("Audio was interrupted or overflowed. Please try recording again.")
    if not done.is_set():
        raise VoiceError("The microphone stopped delivering audio. Check the device and try again.")
    pcm = b"".join(chunks)
    samples = array("h", pcm)
    rms = math.sqrt(sum(sample * sample for sample in samples) / max(1, len(samples)))
    if rms < 30:
        raise VoiceError("No audible input detected. Speak closer to the microphone or select another input.")
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(rate)
        wav.writeframes(pcm)
    return buffer.getvalue()


def normalise_voice_command(text: str) -> str:
    """Map a few spoken command forms onto the existing terminal commands."""
    clean = " ".join("".join(c for c in text if not unicodedata.category(c).startswith("C") or c.isspace()).split())
    clean = clean.strip(" .!?。！？")
    number_words = {"one": "1", "two": "2", "three": "3", "four": "4", "five": "5",
                    "six": "6", "seven": "7", "eight": "8", "nine": "9", "ten": "10",
                    "一": "1", "二": "2", "两": "2", "三": "3", "四": "4", "五": "5",
                    "六": "6", "七": "7", "八": "8", "九": "9", "十": "10"}
    normal = re.sub(r"^(?:(?:can|could|would) you\s+|please\s+)", "", clean, flags=re.I)
    normal = re.sub(r"\s+please$", "", normal, flags=re.I)
    match = re.fullmatch(r"(?:summari[sz]e|summary of)\s+(?:(?:link|number)\s+)?([a-z]+|[0-9]+)", normal, re.I)
    if match:
        number = number_words.get(match.group(1).lower(), match.group(1))
        if number.isascii() and number.isdigit():
            return f"summarise {number}"
    match = re.fullmatch(r"(?:请|請)?(?:总结|總結|摘要)(?:第)?\s*([一二两三四五六七八九十]|[0-9]+)\s*(?:个|個)?(?:链接|連結|条|條)?", normal)
    if match:
        return "summarise " + number_words.get(match.group(1), match.group(1))
    if normal.startswith(("搜索", "搜尋")):
        return "search " + normal[2:].strip()
    match = re.fullmatch(r"(?:open\s+|打开|打開)\s*(.+)", normal, re.I)
    if match:
        app = match.group(1).strip()
        aliases = {"google chrome": "chrome", "谷歌浏览器": "chrome", "谷歌瀏覽器": "chrome",
                   "visual studio code": "vscode", "vs code": "vscode", "vs. code": "vscode",
                   "微软word": "word"}
        return "open " + aliases.get(app.lower(), app)
    return normal


class VoiceInput:
    """Keep one lazily loaded CPU model for this terminal session."""
    def __init__(self):
        self._model = None

    def prepare(self):
        if self._model is None:
            if not all((MODEL_DIR / name).is_file() for name in REQUIRED_MODEL_FILES):
                raise VoiceError("Offline model not installed. Run 'voice setup' once while online.")
            factory = _whisper_class()
            print("KM-Lone: Loading offline speech model...", flush=True)
            try:
                self._model = factory(str(MODEL_DIR), device="cpu", compute_type="int8",
                                      cpu_threads=min(4, os.cpu_count() or 1), local_files_only=True)
            except Exception as error:
                LOGGER.debug("Voice model load failed: %s", type(error).__name__)
                raise VoiceError("Could not load the offline model. Check the voice installation or run 'voice setup' again.") from error

    def transcribe(self, audio: bytes, language: str | None = None) -> str:
        if language not in (None, "en", "zh"):
            raise VoiceError("Voice language must be auto, en or zh.")
        self.prepare()
        try:
            segments, info = self._model.transcribe(
                io.BytesIO(audio), language=language, task="transcribe", beam_size=5,
                vad_filter=True, vad_parameters={"min_silence_duration_ms": 500},
                condition_on_previous_text=False,
            )
            text = " ".join(segment.text.strip() for segment in segments)
        except Exception as error:
            LOGGER.debug("Voice transcription failed: %s", type(error).__name__)
            raise VoiceError("Could not recognise this recording. Please try again or type your command.") from error
        text = normalise_voice_command(text)
        if not text:
            raise VoiceError("No speech was recognised. Please speak clearly and try again.")
        LOGGER.debug("Offline voice recognised: language=%s chars=%s", info.language, len(text))
        return text

    def listen(self, language: str | None = None) -> str:
        seconds = _seconds()
        device = _device()
        self.prepare()  # Model loading finishes before the microphone opens.
        audio = record_audio(seconds, device)
        print("KM-Lone: Recognising locally...", flush=True)
        return self.transcribe(audio, language)


def cli():
    parser = argparse.ArgumentParser(description="KM-Lone offline voice setup and diagnostics")
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--setup", action="store_true", help="Download the speech model; no recording")
    modes.add_argument("--devices", action="store_true", help="List input devices; no recording")
    modes.add_argument("--check", action="store_true", help="Load the local model and list microphones; no recording")
    args = parser.parse_args()
    try:
        if args.setup:
            setup_voice()
        elif args.devices:
            print(list_microphones())
        elif args.check:
            VoiceInput().prepare()
            print(list_microphones())
            print("KM-Lone: Model check completed; microphone recording has not started.")
        else:
            print("You (voice): " + VoiceInput().listen())
    except (VoiceError, KeyboardInterrupt) as error:
        print(f"KM-Lone: {error or 'Voice cancelled.'}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(cli())
