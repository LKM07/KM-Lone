import gzip
import io
import json
import unittest
from http.client import IncompleteRead
from contextlib import redirect_stdout
from datetime import datetime, timezone
from email.message import Message
from unittest.mock import MagicMock, patch
from urllib.error import HTTPError, URLError

import main
import material_summary as summary
from material_search import Material, SearchReport, format_material_report


PROSE = (
    "Neural networks learn useful patterns by adjusting the weights between connected units. "
    "Training compares the network predictions with known examples to measure errors. "
    "Gradient descent changes network weights to reduce those prediction errors. "
    "Validation data checks whether the learned patterns work on previously unseen examples. "
    "Regularisation reduces overfitting so that a network can generalise beyond its training data."
)


def material(number=1, url=None):
    return Material(f"Neural networks {number}", url or f"https://github.com/example/repo{number}",
                    "GitHub", 10, "stars", datetime(2025, 1, 1, tzinfo=timezone.utc))


def report():
    return SearchReport("neural networks", [material(i) for i in range(1, 6)],
                        [material(i) for i in range(6, 11)], ["GitHub"], [])


class SelectionTests(unittest.TestCase):
    def test_summary_commands_and_other_intents(self):
        cases = {
            "summarise 3": "3", "summarize 3": "3", "总结第3个链接": "3",
            "Can you summarise link 3?": "3", "give me a summary of 3": "3",
            "summarise": "", "summarize https://github.com/X/Y?Ref=Ab": "https://github.com/X/Y?Ref=Ab",
            "search materials about neural networks": None, "open chrome": None,
            "how do I summarise my notes": None,
        }
        for command, expected in cases.items():
            with self.subTest(command=command):
                self.assertEqual(summary.extract_summary_target(command), expected)

    def test_displayed_numbers_and_selection_agree(self):
        result = report()
        output = format_material_report(result)
        for number in range(1, 11):
            self.assertIn(f"{number}. Neural networks {number}\n", output)
            self.assertEqual(summary.resolve_material(str(number), result).title, f"Neural networks {number}")

    def test_partial_groups_still_have_contiguous_numbers(self):
        result = SearchReport("topic", [material()], [material(2)], [], [])
        self.assertIn("2. Neural networks 2", format_material_report(result))
        self.assertEqual(summary.resolve_material("2", result), result.recent[0])

    def test_no_history_invalid_numbers_and_unlisted_urls(self):
        for target, previous in [("1", None), ("", report()), ("0", report()), ("11", report()),
                                 ("9" * 5000, report()), ("https://127.0.0.1/", report())]:
            with self.subTest(target=target[:50]), self.assertRaises(summary.SummaryError):
                summary.resolve_material(target, previous)

    def test_selected_url_keeps_case_sensitive_path(self):
        selected = material(url="https://github.com/Owner/Project")
        result = SearchReport("topic", [selected], [], [], [])
        self.assertEqual(summary.resolve_material("https://GITHUB.COM/Owner/Project/#readme", result), selected)
        with self.assertRaises(summary.SummaryError):
            summary.resolve_material("https://github.com/owner/project", result)


class ExtractionTests(unittest.TestCase):
    def test_source_line_wrapping_keeps_paragraph_sentences_together(self):
        text = summary.html_to_text('<p>Neural networks learn patterns\nfrom examples and generalise to unseen data.</p>')
        self.assertEqual(text, 'Neural networks learn patterns from examples and generalise to unseen data.')

    def test_configuration_names_and_headings_do_not_become_key_sentences(self):
        content = ('OCTOKIT_TEST_GITHUB_TOKEN\nOCTOKIT_TEST_GITHUB_CLIENT_SECRET\n'
                   'OCTOKIT_TEST_GITHUB_CLIENT_ID Test OAuth application client id.\n'
                   'How to use the client with a server\n' + PROSE)
        points = summary.extract_key_sentences(content, 'GitHub client')
        self.assertTrue(points)
        self.assertTrue(all(point in PROSE for point in points))

    def test_html_prose_excludes_hidden_elements_navigation_scripts_and_code(self):
        text = summary.html_to_text(
            '<nav>Navigation menu</nav><script>execute_bad_command()</script>'
            '<p>Neural <em>networks</em> &amp; learning are useful.</p>'
            '<pre>subprocess.Popen(bad)</pre><div hidden><p>Hidden secret</p></div>'
            '<p>Another sentence describes useful training examples.</p>'
        )
        self.assertIn("Neural networks & learning are useful.", text)
        for omitted in ["Navigation", "execute_bad", "subprocess", "Hidden secret"]:
            self.assertNotIn(omitted, text)

    def test_summary_uses_only_original_sentences_and_preserves_order(self):
        points = summary.extract_key_sentences(PROSE, "Neural networks", count=3)
        self.assertEqual(len(points), 3)
        self.assertTrue(all(point in PROSE for point in points))
        self.assertEqual([PROSE.index(point) for point in points], sorted(PROSE.index(point) for point in points))
        self.assertEqual(len(points), len(set(points)))

    def test_chinese_sentence_boundaries_and_no_translation(self):
        text = (
            "神经网络通过调整连接权重来学习输入数据与目标输出之间的重要关系。"
            "训练过程会不断比较模型预测和真实结果以便逐步降低预测误差。"
            "验证数据可以帮助检查模型对未见过的新样本是否仍然表现良好。"
        )
        points = summary.extract_key_sentences(text, "神经网络", count=2)
        self.assertEqual(len(points), 2)
        self.assertTrue(all(point in text and point.endswith("。") for point in points))

    def test_no_fabricated_summary_from_empty_body(self):
        with patch.object(summary, "_read_material", return_value=("", "README", ())):
            with self.assertRaisesRegex(summary.SummaryError, "not enough readable prose"):
                summary.summarise_material(material())

    def test_stop_words_only_do_not_crash_scoring(self):
        with self.assertRaises(summary.SummaryError):
            summary.extract_key_sentences('This is what we could do with all of those other.')

    def test_terminal_controls_are_removed(self):
        result = summary.Summary("Title\x1b[2J", "https://example.com", "README", ["Text\x07\u202e"])
        output = summary.format_summary(result)
        self.assertNotIn("\x1b", output)
        self.assertNotIn("\x07", output)
        self.assertNotIn("\u202e", output)


class SourceTests(unittest.TestCase):
    def setUp(self):
        summary._cooldowns.clear()

    def test_github_reads_readme_from_fixed_official_endpoint(self):
        with patch.object(summary, "_fetch", return_value=f"<p>{PROSE}</p>") as fetch:
            result = summary.summarise_material(material())
        self.assertEqual(result.scope, "Repository README only")
        fetch.assert_called_once_with("https://api.github.com/repos/example/repo1/readme", "application/vnd.github.html+json")

    def test_stackoverflow_reads_body_and_answers(self):
        payloads = [{"items": [{"body": "<p>Why do neural networks require adjustable weights?</p>"}]},
                    {"items": [{"body": f"<p>{PROSE}</p>"}]}]
        with patch.object(summary, "_json", side_effect=payloads):
            result = summary.summarise_material(material(url="https://stackoverflow.com/questions/2480650/example"))
        self.assertIn("answers", result.scope)
        self.assertTrue(result.points)

    def test_answer_failure_returns_labelled_question_only_summary(self):
        with patch.object(summary, "_json", side_effect=[{"items": [{"body": f"<p>{PROSE}</p>"}]},
                                                        summary.SummaryError("Rate limited")]):
            result = summary.summarise_material(material(url="https://stackoverflow.com/questions/2480650/example"))
        self.assertEqual(result.scope, "Question body only")
        self.assertIn("Rate limited", result.notes[0])

    def test_openalex_abstract_is_reconstructed_in_word_order(self):
        inverted = {}
        for position, word in enumerate(PROSE.split()):
            inverted.setdefault(word, []).append(position)
        with patch.object(summary, "_json", return_value={"abstract_inverted_index": inverted}) as read:
            result = summary.summarise_material(material(url="https://doi.org/10.1234/example"))
        self.assertIn("abstract only", result.scope)
        self.assertTrue(all(point in PROSE for point in result.points))
        self.assertTrue(read.call_args.args[0].startswith("https://api.openalex.org/works/"))

    def test_missing_abstract_and_unsupported_links_fail_without_guessing(self):
        with patch.object(summary, "_json", return_value={"abstract_inverted_index": None}):
            with self.assertRaisesRegex(summary.SummaryError, "no readable abstract"):
                summary.summarise_material(material(url="https://openalex.org/W123"))
        with patch.object(summary, "_fetch") as fetch:
            for url in ["https://127.0.0.1/", "file:///C:/secret", "https://github.com.evil.test/x/y",
                        "https://user:pass@github.com/x/y", "https://github.com:8443/x/y"]:
                with self.subTest(url=url), self.assertRaises(summary.SummaryError):
                    summary.summarise_material(material(url=url))
            fetch.assert_not_called()

    def test_network_transport_is_allowlisted_and_redirects_disabled(self):
        with patch.object(summary, "build_opener") as opener:
            for url in ["http://api.github.com/repos/a/b", "https://localhost/", "file:///secret",
                        "https://api.github.com.evil.test/"]:
                with self.assertRaises(summary.SummaryError):
                    summary._fetch(url)
            opener.assert_not_called()
        self.assertIsNone(summary._NoRedirect().redirect_request(None, None, 302, "", {}, "http://127.0.0.1/"))

    def test_timeouts_and_rate_limits_are_readable_errors(self):
        for error in [URLError(TimeoutError()), EOFError(), IncompleteRead(b'partial'),
                      HTTPError("https://api.github.com", 429, "Too many", Message(), None)]:
            with patch.object(summary, "build_opener") as opener:
                opener.return_value.open.side_effect = error
                with self.assertRaises(summary.SummaryError):
                    summary._fetch("https://api.github.com/repos/a/b/readme")
        with patch.object(summary, "build_opener") as opener:
            with self.assertRaisesRegex(summary.SummaryError, "requested a pause"):
                summary._fetch("https://api.github.com/repos/a/b/readme")
            opener.assert_not_called()

    def test_stackexchange_backoff_stops_followup_requests(self):
        with patch.object(summary, "_fetch", return_value=json.dumps({"items": [], "backoff": 60})):
            summary._json("https://api.stackexchange.com/2.3/questions/1")
        with patch.object(summary, "build_opener") as opener:
            with self.assertRaisesRegex(summary.SummaryError, "requested a pause"):
                summary._fetch("https://api.stackexchange.com/2.3/questions/1/answers")
            opener.assert_not_called()

    def test_gzip_and_oversized_responses(self):
        for compressed in [False, True]:
            with self.subTest(compressed=compressed), patch.object(summary, "MAX_BYTES", 100):
                response = MagicMock()
                response.headers = Message()
                response.headers["Content-Type"] = "application/json; charset=utf-8"
                raw = b"x" * 101
                if compressed:
                    response.headers["Content-Encoding"] = "gzip"
                    raw = gzip.compress(raw)
                response.read.return_value = raw
                with patch.object(summary, "build_opener") as opener:
                    opener.return_value.open.return_value.__enter__.return_value = response
                    with self.assertRaisesRegex(summary.SummaryError, "too large"):
                        summary._fetch("https://api.github.com/repos/a/b/readme")


class TerminalFlowTests(unittest.TestCase):
    def test_search_then_number_then_url_reuses_summary_and_new_search_clears_selection(self):
        result = report()
        empty = SearchReport("missing", [], [], [], [])
        rendered = summary.Summary("Selected item 6", result.recent[0].url, "README", [PROSE.split(". ")[0]])
        commands = ["search neural networks", "summarise 6", f"summarise {result.recent[0].url}",
                    "search missing", "summarise 6", "hello", "exit"]
        output = io.StringIO()
        with patch("builtins.input", side_effect=commands) as input_fn, \
                patch.object(main, "search_materials", side_effect=[result, empty]), \
                patch.object(main, "summarise_material", return_value=rendered) as summarise, \
                redirect_stdout(output):
            main.main()
        summarise.assert_called_once_with(result.recent[0])
        self.assertEqual(output.getvalue().count("Summary of Selected item 6"), 2)
        self.assertIn("Search for materials first", output.getvalue())
        self.assertIn("Hello! I am KM-Lone", output.getvalue())
        self.assertEqual(input_fn.call_args.args, ("你： ",))

    def test_failed_summary_does_not_exit_or_cache_failure(self):
        commands = ["search neural networks", "summarise 1", "summarise 1", "exit"]
        with patch("builtins.input", side_effect=commands), patch.object(main, "search_materials", return_value=report()), \
                patch.object(main, "summarise_material", side_effect=summary.SummaryError("Source unavailable")) as summarise, \
                redirect_stdout(io.StringIO()) as output:
            main.main()
        self.assertEqual(summarise.call_count, 2)
        self.assertIn("Have a nice day", output.getvalue())

    def test_existing_app_open_branch_still_works(self):
        with patch("builtins.input", side_effect=["open chrome", "exit"]), \
                patch.object(main.subprocess, "Popen") as launch, redirect_stdout(io.StringIO()):
            main.main()
        launch.assert_called_once_with(main.apps["chrome"])


if __name__ == "__main__":
    unittest.main()
