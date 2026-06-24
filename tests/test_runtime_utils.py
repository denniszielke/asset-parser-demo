import tempfile
import unittest
from pathlib import Path

from asset_parser.runtime import _detect_type, _extract_website


class RuntimeUtilsTests(unittest.TestCase):
    def test_detect_type_pdf_by_extension(self) -> None:
        self.assertEqual(_detect_type(Path('/tmp/doc.pdf'), 'application/octet-stream'), 'pdf')

    def test_detect_type_image_by_header(self) -> None:
        self.assertEqual(_detect_type(Path('/tmp/blob.bin'), 'image/png'), 'image')

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
