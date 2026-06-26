# asset-parser-demo

Python runtime to download remote assets and extract relevant context for:
- websites
- PDFs (with document metadata: title, author, subject, page count)
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

Parse a PDF directly:

```bash
python main.py \
  --model openai/gpt-4.1-mini \
  --output ./result.json \
  https://example.com/report.pdf
```

### Parameters
- `urls` (positional): one or more remote URLs
- `--working-dir`: local download folder (created if missing)
- `--model`: model id/deployment name
- `--output`: optional output JSON file path
- `--no-verify-ssl`: disable TLS certificate verification (e.g. for corporate
  proxies with self-signed certificates). Can also be set via
  `ASSET_PARSER_VERIFY_SSL=false` environment variable.

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

If a URL fails to download or parse, the entry contains an `"error"` key
instead of the usual fields so that the rest of the batch still completes:

```json
[
  { "url": "https://bad.example.com/file.pdf", "error": "HTTP 404" }
]
```

## PDF extraction

PDFs are parsed with [PyMuPDF](https://pymupdf.readthedocs.io/). The extractor
produces a structured string that starts with a **document metadata header**
(title, author, subject, page count) followed by the per-page text.  This
gives the LLM reliable document-level context even when individual page text is
sparse.

Example preamble:

```
--- Document Metadata ---
Page count: 29
Title: 2026 Work Trend Index Annual Report
Author: Microsoft WorkLab
Subject: Agents, human agency, and the opportunity for every organization

--- Document Text ---
Page 1:
...
```

## Error handling

- Download and extraction errors for individual URLs are caught, logged, and
  recorded in the output rather than aborting the whole batch.
- LLM enrichment failures fall back to raw extracted content automatically.

## Running tests

```bash
python -m pytest tests/ -v
```

The test suite includes unit tests for all extraction helpers and LLM
enrichment, as well as an integration test class
(`PdfExtractionIntegrationTest`) that validates extraction of the
[2026 Work Trend Index Annual Report](https://assets-c4akfrf5b4d3f4b7.z01.azurefd.net/assets/2026/05/2026_Work_Trend_Index_Annual_Report_050526-7_69fc5b1c4e265.pdf).
The integration tests are automatically skipped when the pre-downloaded file is
not present so CI is never blocked by external network access.

## Skills
A dedicated parsing skill prompt exists at:
- `skills/asset-content-parser/SKILL.md`

Prompt templates used by the runtime are in:
- `asset_parser/prompts/website_prompt.md`
- `asset_parser/prompts/pdf_prompt.md`
- `asset_parser/prompts/image_prompt.md`

