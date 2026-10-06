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

Use one of the following model providers.
You can copy `.env.example` to `.env` and fill in the values.

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
- `--verbose`: enable DEBUG logging, including the reason behind any model enrichment fallback

## Error handling and resilience
- Each URL is processed independently. If a download or extraction step fails for one
  URL, the error is logged and recorded as a `type: "error"` entry in the output instead
  of aborting the whole batch.
- If model enrichment fails (e.g. missing/invalid credentials, rate limiting, network
  issues), the runtime logs a warning with the underlying exception and falls back to a
  truncated version of the raw extracted content so you still get a result. Run with
  `--verbose` to see the enrichment failure details.
- PDF text is extracted per page with [PyMuPDF](https://pymupdf.readthedocs.io/); only the
  first `MAX_RAW_CONTENT_CHARS` (24,000) characters of extracted content are sent to the
  model for enrichment to stay within typical context limits. The fallback content (used
  when enrichment fails) is truncated to the first 4,000 characters.

## Verified sample
This runtime has been tested end-to-end against a real-world multi-page PDF:
[2026 Work Trend Index Annual Report](https://assets-c4akfrf5b4d3f4b7.z01.azurefd.net/assets/2026/05/2026_Work_Trend_Index_Annual_Report_050526-7_69fc5b1c4e265.pdf)
(29 pages). The PDF is downloaded and its text extracted correctly across all pages; when
no model credentials are configured, the tool still returns a usable fallback result
instead of crashing.

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

## Skills
A dedicated parsing skill prompt exists at:
- `skills/asset-content-parser/SKILL.md`

Prompt templates used by the runtime are in:
- `asset_parser/prompts/website_prompt.md`
- `asset_parser/prompts/pdf_prompt.md`
- `asset_parser/prompts/image_prompt.md`
