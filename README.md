# asset-parser-demo

Python runtime to download remote assets and extract relevant context for:
- websites
- PDFs
- images

## Installation

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Configuration

For model-generated summaries, use one of the following model providers.
You can copy `.env.example` to `.env` and fill in the values.
No model credentials are needed when using `--no-enrich` to return full extracted text.

### GitHub Models
- `GITHUB_TOKEN` (required)
- `MODEL_NAME` (optional, default: `openai/gpt-4.1-mini`)

### Foundry Models
- `FOUNDRY_PROJECT_ENDPOINT` (required)
- `FOUNDRY_API_KEY` (optional when using Entra auth)
- `MODEL_NAME` (model deployment name)

If `FOUNDRY_API_KEY` is not set, `DefaultAzureCredential` is used.

## Usage

```bash
python main.py \
  --working-dir ./working \
  --model openai/gpt-4.1-mini \
  --output ./result.json \
  https://example.com
```

### Parameters
- `urls` (positional): one or more remote URLs
- `--working-dir`: local download folder (created if missing)
- `--model`: model id/deployment name
- `--output`: optional output JSON file path
- `--no-enrich`: skip model calls and return full extracted text (or image dimensions/mode)

### Full PDF text without a model

```bash
python main.py \
  --no-enrich \
  --working-dir ./working \
  --output ./working/report.json \
  'https://assets-c4akfrf5b4d3f4b7.z01.azurefd.net/assets/2026/05/2026_Work_Trend_Index_Annual_Report_050526-7_69fc5b1c4e265.pdf'
```

The Python API also supports this mode:

```python
from asset_parser import parse_urls

contexts = parse_urls(
    ["https://example.com/report.pdf"],
    working_dir="./working",
    model="unused",
    enrich=False,
)
```

PDF text retains `Page N:` markers and the PDF's content-stream order. Blank or
image-only pages are omitted with a warning on stderr, preserving original page
numbers. OCR is not performed: scanned/image-only PDFs and password-protected
PDFs raise explicit errors. Complex layouts can still require manual review.

### Model summaries and errors

By default, extracted content is sent to the configured model in ordered chunks
of at most 24,000 characters. Each chunk is summarized separately; the output
joins those summaries in source order, uses the first chunk's title, and merges
up to 10 unique lowercase tags. Long assets require multiple model requests,
with corresponding latency, cost, and rate-limit considerations. Chunking covers
the whole extracted input, but model summaries are not lossless full-text output.

Provider/authentication failures, invalid JSON, and invalid context fields now
raise errors instead of silently returning a truncated raw-text fallback. A
later-chunk failure fails the operation rather than returning a partial summary.
Use `--no-enrich` explicitly when full text without model access is desired.

## Output format
The runtime returns a JSON list of extracted contexts:

```json
[
  {
    "name": "...",
    "url": "...",
    "tags": ["..."],
    "content": "...",
    "type": "website|pdf|image"
  }
]
```

`content` is a model-generated summary by default, or the complete locally
extracted text/metadata with `--no-enrich`. The output schema is the same in both
modes; raw-mode `name` is the URL filename (or URL) and `tags` contains the asset
type. Image extraction currently provides dimensions and color mode, not visual
recognition.

## Tests

After installing dependencies:

```bash
python -m unittest discover -s tests -v
```

An opt-in integration test downloads the public report above (approximately
20 MB) and verifies the output schema, every text-bearing page's complete text,
the final text page, and methodology coverage without requiring model access:

```bash
RUN_PDF_INTEGRATION=1 python -m unittest discover -s tests -p test_report_integration.py -v
```

### Report extraction results

The linked report was tested on October 16, 2026 with Python 3.14 and PyMuPDF:

| Check | Result |
| --- | --- |
| PDF pages | 29 |
| Text-bearing pages preserved | 28 (pages 1-28) |
| Full extracted text, including page markers | 54,176 characters |
| Page 29 | No extractable text; warning emitted |
| Full-text CLI JSON output | Matches output file; methodology and page 28 included |
| Previous model input limit | Only the first 24,000 characters |
| Updated model input coverage | All text in three bounded chunks; regression-tested with mocked responses |
| Live model enrichment | Blocked: configured GitHub Models credentials returned HTTP 403 |

The live integration test makes no model calls. Model response handling, complete
chunk coverage, and error propagation are covered separately by offline tests.
The PDF and extracted report text are not committed to the repository.

## Skills
A dedicated parsing skill prompt exists at:
- `skills/asset-content-parser/SKILL.md`

Prompt templates used by the runtime are in:
- `asset_parser/prompts/website_prompt.md`
- `asset_parser/prompts/pdf_prompt.md`
- `asset_parser/prompts/image_prompt.md`
