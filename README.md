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

Multiple URLs are supported in a single invocation:

```bash
python main.py \
  --working-dir ./working \
  --output ./result.json \
  https://example.com/report.pdf \
  https://example.com/page \
  https://example.com/logo.png
```

### Parameters
- `urls` (positional): one or more remote URLs
- `--working-dir`: local download folder (created if missing)
- `--model`: model id/deployment name
- `--output`: optional output JSON file path

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

## PDF extraction

The PDF extractor uses [PyMuPDF](https://pymupdf.readthedocs.io/) (`fitz`) and produces:

- **Metadata header** — document title, author, subject, keyword, creation date, and page count sourced from the PDF's embedded metadata fields.
- **Per-page text** — blocks are sorted by vertical then horizontal position to preserve the natural reading order of multi-column layouts.

Example output (excerpt from the [2026 Work Trend Index Annual Report](https://assets-c4akfrf5b4d3f4b7.z01.azurefd.net/assets/2026/05/2026_Work_Trend_Index_Annual_Report_050526-7_69fc5b1c4e265.pdf)):

```
Metadata:
Pages: 29
Title: 2026 Work Trend Index Annual Report
Author: Microsoft WorkLab
Creationdate: D:20260505050728-07'00'
Subject: Agents, human agency, and the opportunity for every organization

Page 1:
May 2026
2026 Work Trend Index Annual Report
Agents, human agency, and the opportunity for every organization
...
```

## Reliability

### SSL handling
Downloads first attempt full SSL certificate verification. If the connection fails due to a certificate error (e.g. in environments with self-signed or missing CA bundles), the download is automatically retried with verification disabled and a warning is logged. This keeps the tool usable in corporate or constrained network environments without hiding problems in standard environments.

### Streaming downloads
Files are streamed to disk in 64 KB chunks rather than buffered entirely in memory, so large PDFs (20 MB+) are handled without pressure on the heap.

## Running tests

```bash
source .venv/bin/activate
python -m pytest tests/ -v
```

The test suite covers type detection, URL filename derivation, website extraction, PDF text and metadata extraction, and image metadata extraction.

## Skills
A dedicated parsing skill prompt exists at:
- `skills/asset-content-parser/SKILL.md`

Prompt templates used by the runtime are in:
- `asset_parser/prompts/website_prompt.md`
- `asset_parser/prompts/pdf_prompt.md`
- `asset_parser/prompts/image_prompt.md`
