import tempfile
import unittest
from pathlib import Path

from asset_parser.runtime import _detect_type, _extract_website, _file_name_from_url, _extract_pdf


class RuntimeUtilsTests(unittest.TestCase):
    def test_detect_type_pdf_by_extension(self) -> None:
        self.assertEqual(_detect_type(Path('doc.pdf'), 'application/octet-stream'), 'pdf')

    def test_detect_type_image_by_header(self) -> None:
        self.assertEqual(_detect_type(Path('blob.bin'), 'image/png'), 'image')

    def test_file_name_from_url_preserves_pdf_extension(self) -> None:
        name = _file_name_from_url('https://example.com/path/report.pdf')
        self.assertTrue(name.endswith('_report.pdf'))

    def test_extract_pdf_reads_page_text(self) -> None:
        import fitz

        with tempfile.TemporaryDirectory() as temp_dir:
            file_path = Path(temp_dir) / 'sample.pdf'
            doc = fitz.open()
            page = doc.new_page()
            page.insert_text((72, 72), 'Hello PDF')
            doc.save(file_path)
            doc.close()
            text = _extract_pdf(file_path)
            self.assertIn('Page 1:', text)
            self.assertIn('Hello PDF', text)

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


if __name__ == '__main__':
    unittest.main()
