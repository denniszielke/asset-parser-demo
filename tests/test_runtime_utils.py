import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from asset_parser.runtime import (
    _detect_type,
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

    def test_extract_pdf_returns_text_per_page(self) -> None:
        import pymupdf

        with tempfile.TemporaryDirectory() as temp_dir:
            file_path = Path(temp_dir) / 'sample.pdf'
            document = pymupdf.open()
            page_one = document.new_page()
            page_one.insert_text((72, 72), 'Hello from page one')
            page_two = document.new_page()
            page_two.insert_text((72, 72), 'Hello from page two')
            document.save(file_path)
            document.close()

            text = _extract_pdf(file_path)
            self.assertIn('Page 1:', text)
            self.assertIn('Hello from page one', text)
            self.assertIn('Page 2:', text)
            self.assertIn('Hello from page two', text)

    def test_extract_pdf_skips_blank_pages(self) -> None:
        import pymupdf

        with tempfile.TemporaryDirectory() as temp_dir:
            file_path = Path(temp_dir) / 'blank.pdf'
            document = pymupdf.open()
            document.new_page()
            document.save(file_path)
            document.close()

            text = _extract_pdf(file_path)
            self.assertEqual(text, '')


class LlmEnrichFallbackTests(unittest.TestCase):
    def test_llm_enrich_falls_back_on_model_failure(self) -> None:
        with patch(
            'asset_parser.runtime.extract_json_with_model',
            side_effect=RuntimeError('simulated model failure'),
        ), self.assertLogs('asset_parser.runtime', level='WARNING') as log_context:
            context = _llm_enrich(
                model='fake-model',
                prompt_name='pdf_prompt.md',
                source_type='pdf',
                source_url='https://example.com/report.pdf',
                extracted_content='Page 1:\nSome extracted PDF content.',
            )

        self.assertEqual(context.name, 'report.pdf')
        self.assertEqual(context.tags, ['pdf'])
        self.assertIn('Some extracted PDF content.', context.content)
        self.assertTrue(any('Model enrichment failed' in message for message in log_context.output))


class ParseUrlsResilienceTests(unittest.TestCase):
    def test_parse_urls_records_error_without_aborting_batch(self) -> None:
        def fake_download(url: str, working_dir: Path):
            if 'bad' in url:
                raise RuntimeError('boom')
            path = working_dir / 'ok.html'
            path.write_text('<html><body>ok</body></html>', encoding='utf-8')
            return path, 'text/html'

        with tempfile.TemporaryDirectory() as temp_dir, patch(
            'asset_parser.runtime._download', side_effect=fake_download
        ), patch(
            'asset_parser.runtime.extract_json_with_model',
            side_effect=RuntimeError('no model configured'),
        ):
            results = parse_urls(
                urls=['https://example.com/bad', 'https://example.com/ok'],
                working_dir=temp_dir,
                model='fake-model',
            )

        self.assertEqual(len(results), 2)
        self.assertEqual(results[0]['type'], 'error')
        self.assertIn('boom', results[0]['content'])
        self.assertEqual(results[1]['type'], 'website')


if __name__ == '__main__':
    unittest.main()
