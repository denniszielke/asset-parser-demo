import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from asset_parser.runtime import MODEL_INPUT_CHARACTERS, _extract_pdf, _llm_enrich, parse_urls


class PdfExtractionTests(unittest.TestCase):
    def setUp(self) -> None:
        import pymupdf

        self.pymupdf = pymupdf
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.path = Path(self.temp_dir.name) / "report.pdf"

    def test_preserves_page_numbers_and_final_page(self) -> None:
        with self.pymupdf.open() as document:
            document.new_page().insert_text((72, 72), "First page")
            document.new_page()
            document.new_page().insert_text((72, 72), "Final page finding: 73%")
            document.save(self.path)

        self.assertEqual(
            _extract_pdf(self.path),
            "Page 1:\nFirst page\n\nPage 3:\nFinal page finding: 73%",
        )

    def test_extracts_in_reading_order(self) -> None:
        with self.pymupdf.open() as document:
            page = document.new_page()
            page.insert_text((72, 200), "Bottom")
            page.insert_text((72, 72), "Top")
            document.save(self.path)

        text = _extract_pdf(self.path)
        self.assertLess(text.index("Top"), text.index("Bottom"))

    def test_empty_pdf_reports_ocr_requirement(self) -> None:
        with self.pymupdf.open() as document:
            document.new_page()
            document.save(self.path)

        with self.assertRaisesRegex(ValueError, "OCR may be required"):
            _extract_pdf(self.path)

    def test_password_protected_pdf_fails_explicitly(self) -> None:
        with self.pymupdf.open() as document:
            document.new_page().insert_text((72, 72), "Protected")
            document.save(
                self.path,
                encryption=self.pymupdf.PDF_ENCRYPT_AES_256,
                owner_pw="owner-password",
                user_pw="reader-password",
            )

        with self.assertRaisesRegex(ValueError, "requires a password"):
            _extract_pdf(self.path)

    def test_corrupt_pdf_is_not_returned_as_empty_content(self) -> None:
        self.path.write_bytes(b"%PDF-1.7\ninvalid document")
        with self.assertRaises(self.pymupdf.FileDataError):
            _extract_pdf(self.path)

    def test_no_model_preserves_all_pdf_text_and_output_schema(self) -> None:
        with self.pymupdf.open() as document:
            for index in range(100):
                page = document.new_page()
                page.insert_textbox(
                    self.pymupdf.Rect(72, 72, 500, 700),
                    f"Page finding {index}\n" + "Detailed evidence for this report.\n" * 12,
                )
            document.save(self.path)

        with (
            patch("asset_parser.runtime._download", return_value=(self.path, "application/pdf")),
            patch("asset_parser.runtime.extract_json_with_model") as model,
        ):
            result = parse_urls(
                ["https://example.com/report.pdf"], self.temp_dir.name, "", use_model=False
            )

        model.assert_not_called()
        self.assertEqual(len(result), 1)
        self.assertEqual(set(result[0]), {"name", "url", "tags", "content", "type"})
        self.assertEqual(result[0]["content"], _extract_pdf(self.path))
        self.assertGreater(len(result[0]["content"]), MODEL_INPUT_CHARACTERS)
        self.assertIn("Page finding 99", result[0]["content"])
        self.assertEqual(result[0]["type"], "pdf")


class EnrichmentTests(unittest.TestCase):
    def enrich(self, text: str):
        return _llm_enrich("test-model", "pdf_prompt.md", "pdf", "https://example.com/doc.pdf", text)

    def test_every_character_reaches_model_and_summaries_are_combined(self) -> None:
        text = "A" * MODEL_INPUT_CHARACTERS + "B" * MODEL_INPUT_CHARACTERS + "Final finding"
        responses = [
            {"name": "Report", "tags": ["pdf", f"part-{index}"], "content": f"Summary {index}"}
            for index in range(1, 4)
        ]
        with patch("asset_parser.runtime.extract_json_with_model", side_effect=responses) as model:
            result = self.enrich(text)

        payloads = [call.kwargs["user_payload"] for call in model.call_args_list]
        self.assertEqual("".join(payload["raw_content"] for payload in payloads), text)
        self.assertTrue(all(len(payload["raw_content"]) <= MODEL_INPUT_CHARACTERS for payload in payloads))
        self.assertEqual([payload["chunk_index"] for payload in payloads], [1, 2, 3])
        self.assertTrue(all(payload["chunk_count"] == 3 for payload in payloads))
        self.assertEqual(result.name, "Report")
        self.assertEqual(result.tags, ["pdf", "part-1", "part-2", "part-3"])
        self.assertEqual(result.content, "Summary 1\n\nSummary 2\n\nSummary 3")

    def test_exact_boundary_uses_one_call(self) -> None:
        with patch(
            "asset_parser.runtime.extract_json_with_model",
            return_value={"name": "Report", "tags": [], "content": "Summary"},
        ) as model:
            self.enrich("A" * MODEL_INPUT_CHARACTERS)
        model.assert_called_once()

    def test_model_failure_is_not_disguised_as_success(self) -> None:
        with patch("asset_parser.runtime.extract_json_with_model", side_effect=RuntimeError("No auth")):
            with self.assertRaisesRegex(RuntimeError, "No auth"):
                self.enrich("Report text")

    def test_invalid_model_output_is_rejected(self) -> None:
        invalid_responses = [
            [],
            {},
            {"name": "Report", "tags": "pdf", "content": "Summary"},
            {"name": "Report", "tags": [42], "content": "Summary"},
            {"name": "Report", "tags": ["pdf"] * 11, "content": "Summary"},
            {"name": " ", "tags": [], "content": "Summary"},
            {"name": "Report", "tags": [], "content": {}},
            {"name": "Report", "tags": [], "content": " "},
        ]
        for response in invalid_responses:
            with self.subTest(response=response):
                with patch("asset_parser.runtime.extract_json_with_model", return_value=response):
                    with self.assertRaisesRegex(ValueError, "Invalid model response"):
                        self.enrich("Report text")

    def test_empty_content_does_not_call_model(self) -> None:
        with patch("asset_parser.runtime.extract_json_with_model") as model:
            with self.assertRaisesRegex(ValueError, "No extractable content"):
                self.enrich("")
        model.assert_not_called()

    def test_merged_tags_stay_within_schema_limit(self) -> None:
        with patch(
            "asset_parser.runtime.extract_json_with_model",
            side_effect=[
                {"name": "Report", "tags": [f"tag-{i}" for i in range(10)], "content": "First"},
                {"name": "Report", "tags": ["another"], "content": "Last"},
            ],
        ):
            result = self.enrich("A" * (MODEL_INPUT_CHARACTERS + 1))
        self.assertEqual(len(result.tags), 10)
        self.assertIn("Last", result.content)


@unittest.skipUnless(os.getenv("PDF_TEST_URL"), "Set PDF_TEST_URL to run the live PDF test")
class LivePdfTests(unittest.TestCase):
    def test_remote_report_extracts_every_text_page(self) -> None:
        import pymupdf

        url = os.environ["PDF_TEST_URL"]
        with tempfile.TemporaryDirectory() as working_dir:
            result = parse_urls([url], working_dir, "", use_model=False)
            self.assertEqual(len(result), 1)
            context = result[0]
            self.assertEqual(context["url"], url)
            self.assertEqual(context["type"], "pdf")
            self.assertGreater(len(context["content"]), MODEL_INPUT_CHARACTERS)
            downloaded_files = list(Path(working_dir).iterdir())
            self.assertEqual(len(downloaded_files), 1)
            with pymupdf.open(downloaded_files[0]) as document:
                expected_pages = [
                    f"Page {index}:\n{text}"
                    for index, page in enumerate(document, start=1)
                    if (text := page.get_text("text", sort=True).strip())
                ]
                page_count = document.page_count
            self.assertEqual(context["content"], "\n\n".join(expected_pages))
            self.assertEqual(json.loads(json.dumps(result)), result)
            normalized = " ".join(context["content"].lower().split())
            self.assertIn("work trend index", normalized)
            self.assertIn("2026", normalized)
            print(
                f"\nLive PDF: {page_count} pages, {len(expected_pages)} text pages, "
                f"{len(context['content'])} extracted characters"
            )


if __name__ == "__main__":
    unittest.main()
