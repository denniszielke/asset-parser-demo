import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pymupdf

from asset_parser.runtime import (
    MODEL_CHUNK_CHARACTERS,
    _extract_pdf,
    _llm_enrich,
    main,
    parse_urls,
)


class PDFExtractionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "report.pdf"

    def make_pdf(self, texts: list[str], *, encrypted: bool = False) -> None:
        with pymupdf.open() as document:
            for text in texts:
                page = document.new_page()
                if text:
                    page.insert_text((72, 72), text)
            if encrypted:
                document.save(
                    self.path,
                    encryption=pymupdf.PDF_ENCRYPT_AES_256,
                    owner_pw="owner",
                    user_pw="reader",
                )
            else:
                document.save(self.path)

    def test_extracts_every_text_page_with_original_page_numbers(self) -> None:
        self.make_pdf(["First page", "", "Last page"])
        with self.assertLogs("asset_parser.runtime", level="WARNING") as logs:
            result = _extract_pdf(self.path)
        self.assertEqual(result, "Page 1:\nFirst page\n\nPage 3:\nLast page")
        self.assertIn("2", logs.output[0])
        self.assertIn("OCR is not performed", logs.output[0])

    def test_text_pdf_does_not_warn(self) -> None:
        self.make_pdf(["First", "Second"])
        with self.assertNoLogs("asset_parser.runtime", level="WARNING"):
            self.assertEqual(_extract_pdf(self.path), "Page 1:\nFirst\n\nPage 2:\nSecond")

    def test_retains_pdf_content_stream_order(self) -> None:
        with pymupdf.open() as document:
            page = document.new_page()
            page.insert_text((72, 150), "First paragraph")
            page.insert_text((300, 72), "Sidebar")
            document.save(self.path)
        self.assertEqual(_extract_pdf(self.path), "Page 1:\nFirst paragraph\nSidebar")

    def test_rejects_pdf_without_text(self) -> None:
        self.make_pdf([""])
        with self.assertRaisesRegex(ValueError, "no extractable text.*OCR"):
            _extract_pdf(self.path)

    def test_rejects_password_protected_pdf(self) -> None:
        self.make_pdf(["Secret"], encrypted=True)
        with self.assertRaisesRegex(ValueError, "requires a password"):
            _extract_pdf(self.path)

    def test_corrupt_pdf_error_is_not_hidden(self) -> None:
        self.path.write_bytes(b"not a PDF")
        with self.assertRaises(pymupdf.FileDataError):
            _extract_pdf(self.path)

    def test_no_enrich_returns_complete_pdf_without_model(self) -> None:
        self.make_pdf([
            f"Report page {i}\n" + "Long content repeated on this page.\n" * 30
            for i in range(1, 31)
        ])
        expected = _extract_pdf(self.path)
        self.assertGreater(len(expected), MODEL_CHUNK_CHARACTERS)
        with (
            patch("asset_parser.runtime._download", return_value=(self.path, "application/pdf")),
            patch("asset_parser.runtime.extract_json_with_model") as model,
        ):
            result = parse_urls(
                ["https://example.com/report.pdf"], self.temp.name, "unused", enrich=False
            )
        model.assert_not_called()
        self.assertEqual(result, [{
            "name": "report.pdf",
            "url": "https://example.com/report.pdf",
            "tags": ["pdf"],
            "content": expected,
            "type": "pdf",
        }])
        self.assertIn("Page 30:\nReport page 30", result[0]["content"])

    def test_no_enrich_works_for_other_asset_types(self) -> None:
        for content_type, asset_type, extractor in [
            ("text/html", "website", "_extract_website"),
            ("image/png", "image", "_extract_image"),
        ]:
            with (
                self.subTest(asset_type=asset_type),
                patch(
                    "asset_parser.runtime._download",
                    return_value=(Path(self.temp.name) / "asset.bin", content_type),
                ),
                patch(f"asset_parser.runtime.{extractor}", return_value="Complete content"),
                patch("asset_parser.runtime.extract_json_with_model") as model,
            ):
                result = parse_urls(
                    ["https://example.com/asset"], self.temp.name, "unused", enrich=False
                )
                self.assertEqual(result[0]["content"], "Complete content")
                self.assertEqual(result[0]["type"], asset_type)
                model.assert_not_called()

    def test_default_still_enriches(self) -> None:
        self.make_pdf(["Source text"])
        with (
            patch("asset_parser.runtime._download", return_value=(self.path, "application/pdf")),
            patch(
                "asset_parser.runtime.extract_json_with_model",
                return_value={"name": "Title", "tags": ["pdf"], "content": "Summary"},
            ) as model,
        ):
            result = parse_urls(["https://example.com/report.pdf"], self.temp.name, "test-model")
        self.assertEqual(result[0]["content"], "Summary")
        self.assertEqual(model.call_args.kwargs["model"], "test-model")

    def test_cli_writes_same_full_text_json_to_stdout_and_output(self) -> None:
        self.make_pdf(["Report text"])
        output = Path(self.temp.name) / "result.json"
        stdout = io.StringIO()
        with (
            patch("asset_parser.runtime._download", return_value=(self.path, "application/pdf")),
            patch("asset_parser.runtime.extract_json_with_model") as model,
            patch("sys.argv", [
                "main.py", "--no-enrich", "--working-dir", self.temp.name,
                "--output", str(output), "https://example.com/report.pdf",
            ]),
            contextlib.redirect_stdout(stdout),
        ):
            main()
        model.assert_not_called()
        result = json.loads(output.read_text(encoding="utf-8"))
        self.assertEqual(result, json.loads(stdout.getvalue()))
        self.assertEqual(result[0]["content"], "Page 1:\nReport text")


class EnrichmentTests(unittest.TestCase):
    def enrich(self, text: str):
        return _llm_enrich(
            "test-model", "pdf_prompt.md", "pdf", "https://example.com/report.pdf", text
        )

    def test_all_characters_reach_model_in_bounded_ordered_chunks(self) -> None:
        text = "Beginning\n" + "x" * (MODEL_CHUNK_CHARACTERS * 2) + "\nFinal-page findings"
        replies = [
            {"name": "Report", "tags": ["AI", "work"], "content": "First summary"},
            {"name": "Part two", "tags": ["ai", "agents"], "content": "Second summary"},
            {"name": "Part three", "tags": ["data"], "content": "Final-page findings"},
        ]
        with patch("asset_parser.runtime.extract_json_with_model", side_effect=replies) as model:
            result = self.enrich(text)
        payloads = [call.kwargs["user_payload"] for call in model.call_args_list]
        self.assertEqual(len(payloads), 3)
        self.assertEqual("".join(payload["raw_content"] for payload in payloads), text)
        self.assertTrue(all(len(p["raw_content"]) <= MODEL_CHUNK_CHARACTERS for p in payloads))
        self.assertEqual([p["chunk_index"] for p in payloads], [1, 2, 3])
        self.assertTrue(all(p["chunk_count"] == 3 for p in payloads))
        self.assertEqual(result.name, "Report")
        self.assertEqual(result.tags, ["ai", "work", "agents", "data"])
        self.assertEqual(result.content, "First summary\n\nSecond summary\n\nFinal-page findings")

    def test_exact_chunk_boundary_makes_no_extra_call(self) -> None:
        with patch(
            "asset_parser.runtime.extract_json_with_model",
            return_value={"name": "Title", "tags": [], "content": "Summary"},
        ) as model:
            self.enrich("x" * MODEL_CHUNK_CHARACTERS)
        model.assert_called_once()

    def test_combined_tags_are_limited_to_ten(self) -> None:
        with patch("asset_parser.runtime.extract_json_with_model", side_effect=[
            {"name": "Title", "tags": [f"tag{i}" for i in range(10)], "content": "First"},
            {"name": "Title", "tags": ["extra"], "content": "Last"},
        ]):
            result = self.enrich("x" * (MODEL_CHUNK_CHARACTERS + 1))
        self.assertEqual(result.tags, [f"tag{i}" for i in range(10)])
        self.assertIn("Last", result.content)

    def test_invalid_model_shapes_fail_explicitly(self) -> None:
        valid = {"name": "Title", "tags": ["pdf"], "content": "Summary"}
        invalid = [
            None, [], "text", {},
            {**valid, "name": 123},
            {**valid, "name": " "},
            {**valid, "content": ""},
            {**valid, "content": {"nested": "object"}},
            {**valid, "tags": "pdf"},
            {**valid, "tags": [None]},
            {**valid, "tags": [" "]},
            {**valid, "tags": ["tag"] * 11},
        ]
        for reply in invalid:
            with (
                self.subTest(reply=reply),
                patch("asset_parser.runtime.extract_json_with_model", return_value=reply),
                self.assertRaisesRegex(ValueError, "Invalid model context.*chunk 1/1"),
            ):
                self.enrich("Source text")

    def test_provider_failure_is_not_a_success_shaped_fallback(self) -> None:
        with (
            patch(
                "asset_parser.runtime.extract_json_with_model",
                side_effect=RuntimeError("Provider unavailable"),
            ),
            self.assertRaisesRegex(RuntimeError, "Provider unavailable"),
        ):
            self.enrich("x" * 5000)

    def test_later_chunk_failure_does_not_return_partial_summary(self) -> None:
        with (
            patch("asset_parser.runtime.extract_json_with_model", side_effect=[
                {"name": "Title", "tags": [], "content": "First"},
                RuntimeError("Second chunk failed"),
            ]),
            self.assertRaisesRegex(RuntimeError, "Second chunk failed"),
        ):
            self.enrich("x" * (MODEL_CHUNK_CHARACTERS + 1))

    def test_empty_content_fails_before_model_call(self) -> None:
        with (
            patch("asset_parser.runtime.extract_json_with_model") as model,
            self.assertRaisesRegex(ValueError, "No content to enrich"),
        ):
            self.enrich("")
        model.assert_not_called()


if __name__ == "__main__":
    unittest.main()
