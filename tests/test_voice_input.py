import io
import os
import struct
import unittest
import wave
from contextlib import redirect_stdout
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import main
import voice_input as voice
from material_search import Material, SearchReport
from material_summary import Summary


class VoiceNormalisationTests(unittest.TestCase):
    def test_spoken_commands_map_to_existing_commands(self):
        examples = {
            "Open Chrome.": "open Chrome",
            "Please open Google Chrome!": "open chrome",
            "Open Visual Studio Code.": "open vscode",
            "Summarize three.": "summarise 3",
            "Can you summarise link ten?": "summarise 10",
            "总结第三个链接。": "summarise 3",
            "總結第六個連結": "summarise 6",
            "搜索神经网络": "search 神经网络",
            "打開谷歌瀏覽器": "open chrome",
            "Can you help me to get the materials about Neural Network?":
                "help me to get the materials about Neural Network",
            "Search C++ tutorials.": "Search C++ tutorials",
            "\x1bhello\x07": "hello",
        }
        for text, expected in examples.items():
            with self.subTest(text=text):
                self.assertEqual(voice.normalise_voice_command(text), expected)

    def test_config_has_safe_bounds_and_readable_errors(self):
        for setting in ["0", "31", "not a number"]:
            with patch.dict(os.environ, {"KM_LONE_VOICE_SECONDS": setting}), self.assertRaises(voice.VoiceError):
                voice._seconds()
        with patch.dict(os.environ, {"KM_LONE_VOICE_SECONDS": "8", "KM_LONE_MIC_DEVICE": "3"}):
            self.assertEqual(voice._seconds(), 8)
            self.assertEqual(voice._device(), 3)
        with patch.dict(os.environ, {"KM_LONE_MIC_DEVICE": "-1"}), self.assertRaises(voice.VoiceError):
            voice._device()


class TranscriptionTests(unittest.TestCase):
    def test_missing_model_does_not_download_or_touch_microphone(self):
        engine = voice.VoiceInput()
        with patch.object(voice, "MODEL_DIR") as directory, patch.object(voice, "_whisper_class") as factory, \
                patch.object(voice, "record_audio") as record:
            directory.__truediv__.return_value.is_file.return_value = False
            with self.assertRaisesRegex(voice.VoiceError, "voice setup"):
                engine.listen()
            factory.assert_not_called()
            record.assert_not_called()

    def test_model_is_local_only_and_loaded_once(self):
        engine = voice.VoiceInput()
        with patch.object(voice, "MODEL_DIR") as directory, patch.object(voice, "_whisper_class") as factory, \
                redirect_stdout(io.StringIO()):
            directory.__truediv__.return_value.is_file.return_value = True
            engine.prepare()
            engine.prepare()
        factory.return_value.assert_called_once()
        self.assertTrue(factory.return_value.call_args.kwargs["local_files_only"])
        self.assertEqual(factory.return_value.call_args.kwargs["device"], "cpu")

    def test_audio_transcribed_locally_and_generator_is_consumed(self):
        engine = voice.VoiceInput()
        engine._model = MagicMock()
        engine._model.transcribe.return_value = (
            iter([SimpleNamespace(text="Summarise three.")]), SimpleNamespace(language="en"))
        self.assertEqual(engine.transcribe(b"test WAV", "en"), "summarise 3")
        args, kwargs = engine._model.transcribe.call_args
        self.assertEqual(args[0].getvalue(), b"test WAV")
        self.assertTrue(kwargs["vad_filter"])
        self.assertEqual(kwargs["language"], "en")
        self.assertEqual(kwargs["task"], "transcribe")

    def test_silence_and_failed_recognition_return_voice_errors(self):
        engine = voice.VoiceInput()
        engine._model = MagicMock()
        engine._model.transcribe.return_value = (iter([]), SimpleNamespace(language="en"))
        with self.assertRaisesRegex(voice.VoiceError, "No speech"):
            engine.transcribe(b"silence")
        engine._model.transcribe.side_effect = RuntimeError("decoder unavailable")
        with self.assertRaisesRegex(voice.VoiceError, "Could not recognise"):
            engine.transcribe(b"invalid")

    def test_model_ready_before_recording_and_cancel_propagates(self):
        engine = voice.VoiceInput()
        order = []
        with patch.object(engine, "prepare", side_effect=lambda: order.append("prepare")), \
                patch.object(voice, "record_audio", side_effect=lambda *args: order.append("record") or b"wav"), \
                patch.object(engine, "transcribe", return_value="hello"), redirect_stdout(io.StringIO()):
            self.assertEqual(engine.listen(), "hello")
        self.assertEqual(order, ["prepare", "record"])


class RecordingTests(unittest.TestCase):
    def fake_device(self, samples=1000, status=False):
        sd = MagicMock()
        sd.CallbackStop = type("CallbackStop", (Exception,), {})
        sd.query_devices.return_value = {"default_samplerate": 16000, "max_input_channels": 1}
        closed = []

        def stream(**kwargs):
            class Stream:
                def __enter__(self):
                    # Deliberately supply too many samples: capture must cap them.
                    try:
                        kwargs["callback"](struct.pack("<h", samples) * 17000, 17000, None, status)
                    except sd.CallbackStop:
                        pass
                    return self

                def __exit__(self, *args):
                    closed.append(True)
            return Stream()

        sd.RawInputStream.side_effect = stream
        return sd, closed

    def test_recording_is_bounded_wav_and_stream_closes(self):
        sd, closed = self.fake_device()
        with patch.object(voice, "_sounddevice", return_value=sd), redirect_stdout(io.StringIO()):
            audio = voice.record_audio(1)
        with wave.open(io.BytesIO(audio), "rb") as wav:
            self.assertEqual(wav.getnframes(), 16000)
            self.assertEqual(wav.getnchannels(), 1)
            self.assertEqual(wav.getsampwidth(), 2)
        self.assertEqual(closed, [True])

    def test_silent_microphone_and_overflows_do_not_create_commands(self):
        for samples, status, message in [(0, False, "No audible"), (1000, True, "interrupted")]:
            sd, closed = self.fake_device(samples, status)
            with patch.object(voice, "_sounddevice", return_value=sd), redirect_stdout(io.StringIO()), \
                    self.assertRaisesRegex(voice.VoiceError, message):
                voice.record_audio(1)
            self.assertEqual(closed, [True])

    def test_missing_or_denied_microphone_is_reported(self):
        sd = MagicMock()
        sd.query_devices.side_effect = RuntimeError("Access denied")
        with patch.object(voice, "_sounddevice", return_value=sd), self.assertRaisesRegex(voice.VoiceError, "Could not record"):
            voice.record_audio(1)

    def test_keyboard_interrupt_releases_microphone(self):
        sd = MagicMock()
        sd.query_devices.return_value = {"default_samplerate": 16000, "max_input_channels": 1}
        with patch.object(voice, "_sounddevice", return_value=sd), \
                patch.object(voice.threading, "Event") as event, redirect_stdout(io.StringIO()):
            event.return_value.wait.side_effect = KeyboardInterrupt
            with self.assertRaises(KeyboardInterrupt):
                voice.record_audio(1)
        sd.RawInputStream.return_value.__exit__.assert_called_once()


class VoiceTerminalTests(unittest.TestCase):
    def test_voice_search_and_summary_share_keyboard_result_history(self):
        item = Material("Example", "https://github.com/a/b", "GitHub", 1, "stars", None)
        result = SearchReport("Neural Network", [item], [], [], [])
        with patch("builtins.input", side_effect=["voice en", "voice", "hello", "exit"]), \
                patch.object(main.VoiceInput, "listen", side_effect=["search Neural Network", "summarise 1"]) as listen, \
                patch.object(main, "search_materials", return_value=result) as search, \
                patch.object(main, "summarise_material", return_value=Summary("Example", item.url, "README", ["Original text."])) as summarise, \
                redirect_stdout(io.StringIO()) as output:
            main.main()
        search.assert_called_once_with("Neural Network")
        summarise.assert_called_once_with(item)
        self.assertEqual(listen.call_args_list[0].args, ("en",))
        self.assertEqual(listen.call_args_list[1].args, (None,))
        self.assertIn("You (voice): summarise 1", output.getvalue())
        self.assertIn("Hello! I am KM-Lone", output.getvalue())

    def test_voice_can_open_app_using_existing_dispatch(self):
        with patch("builtins.input", side_effect=["voice", "exit"]), \
                patch.object(main.VoiceInput, "listen", return_value="open chrome"), \
                patch.object(main.subprocess, "Popen") as launch, redirect_stdout(io.StringIO()):
            main.main()
        launch.assert_called_once_with(main.apps["chrome"])

    def test_failed_or_cancelled_voice_returns_to_typing(self):
        for error in [voice.VoiceError("No microphone"), KeyboardInterrupt()]:
            with patch("builtins.input", side_effect=["voice", "hello", "exit"]), \
                    patch.object(main.VoiceInput, "listen", side_effect=error), \
                    redirect_stdout(io.StringIO()) as output:
                main.main()
            self.assertIn("Hello! I am KM-Lone", output.getvalue())

    def test_keyboard_mode_never_loads_model_or_records(self):
        with patch("builtins.input", side_effect=["hello", "exit"]), \
                patch.object(voice, "_whisper_class") as model, patch.object(voice, "record_audio") as record, \
                redirect_stdout(io.StringIO()):
            main.main()
        model.assert_not_called()
        record.assert_not_called()

    def test_setup_and_devices_do_not_record(self):
        with patch("builtins.input", side_effect=["voice devices", "voice setup", "exit"]), \
                patch.object(main, "list_microphones", return_value="1: Test microphone"), \
                patch.object(main, "setup_voice") as setup, patch.object(main.VoiceInput, "listen") as listen, \
                redirect_stdout(io.StringIO()):
            main.main()
        setup.assert_called_once()
        listen.assert_not_called()


if __name__ == "__main__":
    unittest.main()
