import os
import tempfile
import unittest
from pathlib import Path

import pymupdf

from asset_parser.runtime import parse_urls


REPORT_URL = (
    "https://assets-c4akfrf5b4d3f4b7.z01.azurefd.net/assets/2026/05/"
    "2026_Work_Trend_Index_Annual_Report_050526-7_69fc5b1c4e265.pdf"
)


@unittest.skipUnless(
    os.getenv("RUN_PDF_INTEGRATION") == "1",
    "Set RUN_PDF_INTEGRATION=1 to download the public 20 MB report",
)
class ReportIntegrationTests(unittest.TestCase):
    def test_full_report_extraction_without_model(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with self.assertLogs("asset_parser.runtime", level="WARNING") as logs:
                result = parse_urls([REPORT_URL], directory, "unused", enrich=False)
            self.assertEqual(len(result), 1)
            context = result[0]
            self.assertEqual(set(context), {"name", "url", "tags", "content", "type"})
            self.assertEqual(context["url"], REPORT_URL)
            self.assertEqual(context["type"], "pdf")
            self.assertEqual(context["tags"], ["pdf"])
            self.assertGreater(len(context["content"]), 50000)
            self.assertIn("methodology", context["content"].lower())
            self.assertIn("Page 28:\n", context["content"])
            self.assertIn("29", logs.output[0])
            downloaded = list(Path(directory).glob("*.pdf"))
            self.assertEqual(len(downloaded), 1)
            with pymupdf.open(downloaded[0]) as document:
                self.assertEqual(len(document), 29)
                expected_pages = [
                    f"Page {index}:\n{text}"
                    for index, page in enumerate(document, 1)
                    if (text := page.get_text("text").strip())
                ]
            self.assertEqual(len(expected_pages), 28)
            self.assertEqual(context["content"], "\n\n".join(expected_pages))


if __name__ == "__main__":
    unittest.main()
