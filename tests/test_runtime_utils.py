import tempfile
import unittest
from pathlib import Path

from asset_parser.runtime import (
    ParsedContext,
    _detect_type,
    _download,
    _extract_pdf,
    _extract_website,
    _llm_enrich,
    parse_urls,
)


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

    def test_download_rejects_non_http_scheme(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            with self.assertRaises(ValueError):
                _download('file:///etc/passwd', Path(temp_dir))

    def test_extract_pdf_returns_page_text(self) -> None:
        import pymupdf

        with tempfile.TemporaryDirectory() as temp_dir:
            pdf_path = Path(temp_dir) / 'sample.pdf'
            document = pymupdf.open()
            page = document.new_page()
            page.insert_text((72, 72), "Hello PDF World")
            document.save(pdf_path)
            document.close()

            text = _extract_pdf(pdf_path)
            self.assertIn('Page 1:', text)
            self.assertIn('Hello PDF World', text)

    def test_extract_pdf_empty_document_returns_empty_string(self) -> None:
        import pymupdf

        with tempfile.TemporaryDirectory() as temp_dir:
            pdf_path = Path(temp_dir) / 'blank.pdf'
            document = pymupdf.open()
            document.new_page()
            document.save(pdf_path)
            document.close()

            self.assertEqual(_extract_pdf(pdf_path), '')

    def test_llm_enrich_falls_back_on_model_failure(self) -> None:
        import asset_parser.runtime as runtime_module

        def _raise(*_args, **_kwargs):
            raise RuntimeError('model unavailable')

        original = runtime_module.extract_json_with_model
        runtime_module.extract_json_with_model = _raise
        try:
            context = _llm_enrich(
                model='test-model',
                prompt_name='pdf_prompt.md',
                source_type='pdf',
                source_url='https://example.com/report.pdf',
                extracted_content='Some extracted text content.',
            )
        finally:
            runtime_module.extract_json_with_model = original

        self.assertIsInstance(context, ParsedContext)
        self.assertEqual(context.name, 'report.pdf')
        self.assertEqual(context.tags, ['pdf'])
        self.assertIn('Some extracted text content.', context.content)

    def test_parse_urls_isolates_failures(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            result = parse_urls(
                urls=['ftp://unsupported.example/file'],
                working_dir=temp_dir,
                model='test-model',
            )
            self.assertEqual(len(result), 1)
            self.assertEqual(result[0]['type'], 'error')
            self.assertIn('ftp', result[0]['content'].lower())


if __name__ == '__main__':
    unittest.main()
