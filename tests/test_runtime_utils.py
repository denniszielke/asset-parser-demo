import tempfile
import unittest
from pathlib import Path

from asset_parser.runtime import _detect_type, _extract_pdf, _extract_website


class RuntimeUtilsTests(unittest.TestCase):
    def test_detect_type_pdf_by_extension(self) -> None:
        self.assertEqual(_detect_type(Path('doc.pdf'), 'application/octet-stream'), 'pdf')

    def test_detect_type_image_by_header(self) -> None:
        self.assertEqual(_detect_type(Path('blob.bin'), 'image/png'), 'image')

    def test_extract_website_removes_script(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            file_path = Path(temp_dir) / 'index.html'
            file_path.write_text(
                "<html><body><h1>Hello</h1><script>alert('x')</script><p>World</p></body></html>",
                encoding='utf-8',
            )
            text = _extract_website(file_path)
            self.assertIn('Hello', text)
            self.assertIn('World', text)
            self.assertNotIn('alert', text)

    def test_extract_pdf_includes_page_markers(self) -> None:
        pdf_path = Path('tests/fixtures/work_trend_index_2026.pdf')
        self.assertTrue(pdf_path.exists(), 'Expected test PDF fixture to exist')
        extracted = _extract_pdf(pdf_path)
        self.assertIn('[Page 1]', extracted)
        self.assertIn('2026 Work Trend Index Annual Report', extracted)


if __name__ == '__main__':
    unittest.main()
