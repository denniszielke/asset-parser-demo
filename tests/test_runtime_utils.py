import tempfile
import unittest
from pathlib import Path

from asset_parser.runtime import (
    _detect_type,
    _extract_image,
    _extract_pdf,
    _extract_website,
    _file_name_from_url,
)


def _make_minimal_pdf(path: Path) -> None:
    """Write a minimal but valid single-page PDF with some text."""
    import fitz

    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 100), "Hello PDF World", fontsize=12)
    doc.save(str(path))
    doc.close()


def _make_minimal_image(path: Path) -> None:
    """Write a minimal PNG image."""
    from PIL import Image

    img = Image.new("RGB", (64, 32), color=(255, 0, 0))
    img.save(str(path), format="PNG")


class DetectTypeTests(unittest.TestCase):
    def test_pdf_by_extension(self) -> None:
        self.assertEqual(_detect_type(Path("doc.pdf"), "application/octet-stream"), "pdf")

    def test_pdf_by_content_type(self) -> None:
        self.assertEqual(_detect_type(Path("file.bin"), "application/pdf"), "pdf")

    def test_image_by_content_type_header(self) -> None:
        self.assertEqual(_detect_type(Path("blob.bin"), "image/png"), "image")

    def test_image_by_extension(self) -> None:
        for ext in (".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".tif", ".tiff"):
            with self.subTest(ext=ext):
                self.assertEqual(_detect_type(Path(f"photo{ext}"), None), "image")

    def test_website_fallback(self) -> None:
        self.assertEqual(_detect_type(Path("page.html"), "text/html"), "website")

    def test_unknown_fallback(self) -> None:
        self.assertEqual(_detect_type(Path("data.bin"), None), "website")


class FileNameFromUrlTests(unittest.TestCase):
    def test_includes_basename(self) -> None:
        name = _file_name_from_url("https://example.com/path/report.pdf")
        self.assertTrue(name.endswith("report.pdf"), name)

    def test_adds_bin_extension_when_missing(self) -> None:
        name = _file_name_from_url("https://example.com/download")
        self.assertTrue(name.endswith(".bin"), name)

    def test_hash_prefix_is_8_chars(self) -> None:
        name = _file_name_from_url("https://example.com/file.pdf")
        prefix = name.split("_")[0]
        self.assertEqual(len(prefix), 8)

    def test_different_urls_produce_different_names(self) -> None:
        a = _file_name_from_url("https://example.com/a.pdf")
        b = _file_name_from_url("https://example.com/b.pdf")
        self.assertNotEqual(a, b)


class ExtractWebsiteTests(unittest.TestCase):
    def test_removes_script_tags(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            f = Path(tmp) / "index.html"
            f.write_text(
                "<html><body><h1>Hello</h1><script>alert('x')</script><p>World</p></body></html>",
                encoding="utf-8",
            )
            text = _extract_website(f)
            self.assertIn("Hello", text)
            self.assertIn("World", text)
            self.assertNotIn("alert", text)

    def test_removes_style_tags(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            f = Path(tmp) / "styled.html"
            f.write_text(
                "<html><head><style>body{color:red}</style></head><body><p>Content</p></body></html>",
                encoding="utf-8",
            )
            text = _extract_website(f)
            self.assertIn("Content", text)
            self.assertNotIn("color", text)

    def test_strips_blank_lines(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            f = Path(tmp) / "blank.html"
            f.write_text("<html><body><p>A</p><p></p><p>B</p></body></html>", encoding="utf-8")
            text = _extract_website(f)
            lines = [ln for ln in text.splitlines() if not ln.strip()]
            self.assertEqual(lines, [], "Expected no blank lines in output")


class ExtractPdfTests(unittest.TestCase):
    def test_extracts_text(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pdf_path = Path(tmp) / "test.pdf"
            _make_minimal_pdf(pdf_path)
            text = _extract_pdf(pdf_path)
            self.assertIn("Hello PDF World", text)

    def test_includes_page_number(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pdf_path = Path(tmp) / "test.pdf"
            _make_minimal_pdf(pdf_path)
            text = _extract_pdf(pdf_path)
            self.assertIn("Page 1", text)

    def test_includes_metadata_section(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pdf_path = Path(tmp) / "test.pdf"
            _make_minimal_pdf(pdf_path)
            text = _extract_pdf(pdf_path)
            self.assertIn("Metadata:", text)
            self.assertIn("Pages:", text)

    def test_empty_pdf_returns_metadata_only(self) -> None:
        import fitz

        with tempfile.TemporaryDirectory() as tmp:
            pdf_path = Path(tmp) / "empty.pdf"
            doc = fitz.open()
            doc.new_page()
            doc.save(str(pdf_path))
            doc.close()
            text = _extract_pdf(pdf_path)
            self.assertIn("Metadata:", text)
            self.assertNotIn("Page 1:", text)


class ExtractImageTests(unittest.TestCase):
    def test_returns_dimensions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            img_path = Path(tmp) / "test.png"
            _make_minimal_image(img_path)
            text = _extract_image(img_path)
            self.assertIn("64x32", text)

    def test_returns_color_mode(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            img_path = Path(tmp) / "test.png"
            _make_minimal_image(img_path)
            text = _extract_image(img_path)
            self.assertIn("RGB", text)

    def test_returns_format(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            img_path = Path(tmp) / "test.png"
            _make_minimal_image(img_path)
            text = _extract_image(img_path)
            self.assertIn("PNG", text)


if __name__ == "__main__":
    unittest.main()
