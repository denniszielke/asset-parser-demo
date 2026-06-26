import io
import struct
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from asset_parser.runtime import (
    _detect_type,
    _extract_image,
    _extract_pdf,
    _extract_website,
    _file_name_from_url,
    _llm_enrich,
)


def _make_minimal_pdf(title: str = "Test PDF", author: str = "Test Author", text: str = "Hello PDF") -> bytes:
    """Return a minimal valid PDF with one page containing *text*."""
    import fitz

    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), text)
    doc.set_metadata({"title": title, "author": author})
    buf = io.BytesIO()
    doc.save(buf)
    doc.close()
    return buf.getvalue()


def _make_minimal_png(width: int = 8, height: int = 8) -> bytes:
    """Return a minimal 8x8 white PNG image."""
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (width, height), color=(255, 255, 255)).save(buf, format="PNG")
    return buf.getvalue()


class FileNameFromUrlTests(unittest.TestCase):
    def test_preserves_extension(self) -> None:
        name = _file_name_from_url("https://example.com/report.pdf")
        self.assertTrue(name.endswith("_report.pdf"))

    def test_adds_bin_extension_for_extensionless_path(self) -> None:
        name = _file_name_from_url("https://example.com/file")
        self.assertTrue(name.endswith(".bin"))

    def test_uses_downloaded_asset_for_empty_path(self) -> None:
        name = _file_name_from_url("https://example.com/")
        self.assertIn("downloaded_asset", name)

    def test_hash_prefix_differs_for_different_urls(self) -> None:
        name1 = _file_name_from_url("https://example.com/a.pdf")
        name2 = _file_name_from_url("https://example.com/b.pdf")
        self.assertNotEqual(name1[:8], name2[:8])

    def test_same_url_produces_same_name(self) -> None:
        url = "https://example.com/doc.pdf"
        self.assertEqual(_file_name_from_url(url), _file_name_from_url(url))


class DetectTypeTests(unittest.TestCase):
    def test_pdf_by_extension(self) -> None:
        self.assertEqual(_detect_type(Path("doc.pdf"), "application/octet-stream"), "pdf")

    def test_pdf_by_content_type(self) -> None:
        self.assertEqual(_detect_type(Path("blob.bin"), "application/pdf"), "pdf")

    def test_image_by_content_type_header(self) -> None:
        self.assertEqual(_detect_type(Path("blob.bin"), "image/png"), "image")

    def test_image_by_extension_jpeg(self) -> None:
        self.assertEqual(_detect_type(Path("photo.jpeg"), None), "image")

    def test_image_by_extension_webp(self) -> None:
        self.assertEqual(_detect_type(Path("photo.webp"), None), "image")

    def test_website_fallback(self) -> None:
        self.assertEqual(_detect_type(Path("page.html"), "text/html"), "website")

    def test_website_fallback_no_content_type(self) -> None:
        self.assertEqual(_detect_type(Path("unknown.bin"), None), "website")


class ExtractWebsiteTests(unittest.TestCase):
    def test_removes_script_and_style(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            file_path = Path(tmp) / "index.html"
            file_path.write_text(
                "<html><body><h1>Hello</h1><script>alert('x')</script>"
                "<style>.a{color:red}</style><p>World</p></body></html>",
                encoding="utf-8",
            )
            text = _extract_website(file_path)
            self.assertIn("Hello", text)
            self.assertIn("World", text)
            self.assertNotIn("alert", text)
            self.assertNotIn("color:red", text)

    def test_collapses_blank_lines(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            file_path = Path(tmp) / "page.html"
            file_path.write_text("<html><body><p>A</p><p></p><p>B</p></body></html>", encoding="utf-8")
            text = _extract_website(file_path)
            self.assertNotIn("\n\n\n", text)


class ExtractPdfTests(unittest.TestCase):
    def test_extracts_text_and_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pdf_path = Path(tmp) / "test.pdf"
            pdf_path.write_bytes(_make_minimal_pdf(title="My Title", author="Jane Doe", text="Sample content here"))
            result = _extract_pdf(pdf_path)
            self.assertIn("My Title", result)
            self.assertIn("Jane Doe", result)
            self.assertIn("Sample content here", result)

    def test_metadata_preamble_present(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pdf_path = Path(tmp) / "doc.pdf"
            pdf_path.write_bytes(_make_minimal_pdf())
            result = _extract_pdf(pdf_path)
            self.assertIn("Document Metadata", result)
            self.assertIn("Page count:", result)

    def test_page_count_in_output(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pdf_path = Path(tmp) / "multi.pdf"
            pdf_path.write_bytes(_make_minimal_pdf())
            result = _extract_pdf(pdf_path)
            self.assertIn("Page count: 1", result)


class ExtractImageTests(unittest.TestCase):
    def test_returns_dimensions_and_mode(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            img_path = Path(tmp) / "img.png"
            img_path.write_bytes(_make_minimal_png(width=16, height=8))
            result = _extract_image(img_path)
            self.assertIn("16x8", result)
            self.assertIn("RGB", result)

    def test_returns_format(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            img_path = Path(tmp) / "img.png"
            img_path.write_bytes(_make_minimal_png())
            result = _extract_image(img_path)
            self.assertIn("PNG", result)


class LlmEnrichTests(unittest.TestCase):
    def _mock_result(self) -> dict:
        return {"name": "Test Doc", "tags": ["ai", "report"], "content": "Summary text"}

    def test_returns_parsed_context_on_success(self) -> None:
        with patch("asset_parser.runtime.extract_json_with_model", return_value=self._mock_result()):
            ctx = _llm_enrich("model", "pdf_prompt.md", "pdf", "https://example.com/doc.pdf", "raw text")
        self.assertEqual(ctx.name, "Test Doc")
        self.assertEqual(ctx.tags, ["ai", "report"])
        self.assertEqual(ctx.content, "Summary text")
        self.assertEqual(ctx.type, "pdf")

    def test_falls_back_on_exception(self) -> None:
        with patch("asset_parser.runtime.extract_json_with_model", side_effect=RuntimeError("API down")):
            ctx = _llm_enrich("model", "pdf_prompt.md", "pdf", "https://example.com/doc.pdf", "raw text")
        self.assertIn("doc.pdf", ctx.name)
        self.assertEqual(ctx.tags, ["pdf"])
        self.assertIn("raw text", ctx.content)

    def test_fallback_content_truncated_to_4000(self) -> None:
        long_text = "x" * 10_000
        with patch("asset_parser.runtime.extract_json_with_model", side_effect=RuntimeError("fail")):
            ctx = _llm_enrich("model", "pdf_prompt.md", "pdf", "https://example.com/doc.pdf", long_text)
        self.assertLessEqual(len(ctx.content), 4_000)

    def test_missing_llm_fields_use_fallback(self) -> None:
        with patch("asset_parser.runtime.extract_json_with_model", return_value={}):
            ctx = _llm_enrich("model", "pdf_prompt.md", "pdf", "https://example.com/doc.pdf", "fallback content")
        self.assertIn("doc.pdf", ctx.name)
        self.assertEqual(ctx.tags, ["pdf"])


class PdfExtractionIntegrationTest(unittest.TestCase):
    """Integration test that verifies extraction of the 2026 Work Trend Index PDF.

    Skipped when the pre-downloaded file is not available so CI is not blocked
    by external network access.
    """

    PDF_PATH = Path("/tmp/test_report.pdf")
    PDF_URL = (
        "https://assets-c4akfrf5b4d3f4b7.z01.azurefd.net/assets/2026/05/"
        "2026_Work_Trend_Index_Annual_Report_050526-7_69fc5b1c4e265.pdf"
    )

    @classmethod
    def setUpClass(cls) -> None:
        if not cls.PDF_PATH.exists():
            raise unittest.SkipTest(f"Pre-downloaded PDF not found at {cls.PDF_PATH}")

    def test_extracts_metadata_title(self) -> None:
        result = _extract_pdf(self.PDF_PATH)
        self.assertIn("2026 Work Trend Index", result)

    def test_extracts_metadata_author(self) -> None:
        result = _extract_pdf(self.PDF_PATH)
        self.assertIn("Microsoft WorkLab", result)

    def test_page_count_correct(self) -> None:
        result = _extract_pdf(self.PDF_PATH)
        self.assertIn("Page count: 29", result)

    def test_body_text_present(self) -> None:
        result = _extract_pdf(self.PDF_PATH)
        self.assertIn("AI", result)
        self.assertIn("Page 1:", result)

    def test_metadata_preamble_before_body(self) -> None:
        result = _extract_pdf(self.PDF_PATH)
        metadata_pos = result.index("Document Metadata")
        body_pos = result.index("Document Text")
        self.assertLess(metadata_pos, body_pos)


if __name__ == "__main__":
    unittest.main()
