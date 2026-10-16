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

For model-enriched summaries, use one of the following model providers.
You can copy `.env.example` to `.env` and fill in the values.
Model credentials are not needed with `--no-model`.

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
- `--no-model`: return the full locally extracted content instead of a model summary

### Extract the 2026 Work Trend Index PDF

```bash
python main.py --no-model --working-dir ./working --output ./working/report.json \
  'https://assets-c4akfrf5b4d3f4b7.z01.azurefd.net/assets/2026/05/2026_Work_Trend_Index_Annual_Report_050526-7_69fc5b1c4e265.pdf'
```

Omit `--no-model` to generate summaries with the configured provider. PDF
extraction uses PyMuPDF's reading-order sorting and retains original page numbers.
Blank pages are omitted without renumbering subsequent pages. Scanned/image-only
PDFs require OCR, which is not implemented; password-protected PDFs and PDFs with
no extractable text fail explicitly. On mixed text/image PDFs, only embedded text
is extracted; image-only pages and figures are not transcribed. Reading order is
best effort, not guaranteed column or table reconstruction.

Model enrichment sends **every** 24,000-character chunk sequentially, then
concatenates the summaries in source order and deduplicates tags (up to 10).
Long documents therefore use multiple model calls and can incur additional cost.
Chunks use character rather than token limits; a provider's token limit may still
require adjusting `MODEL_INPUT_CHARACTERS` in `asset_parser/runtime.py`.
The raw `--no-model` output is never truncated. Its name is the source filename
and its tags contain only the detected asset type.

**Error behavior:** download, PDF, authentication, and model-response errors fail
the operation instead of returning a success-shaped, truncated fallback. Model
responses must contain nonempty `name`/`content` strings and a list of up to 10
nonempty string tags. This intentionally replaces the previous silent fallback;
use `--no-model` when full local extraction is desired without model access.

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

## Tests

```bash
python -m unittest discover -s tests -v
```

Tests generate small PDF fixtures locally, including blank, encrypted, corrupt,
and long documents. Model calls are mocked; no credentials are required.
The optional live test downloads the report and checks the JSON schema, title,
text length beyond the old truncation boundary, and exact coverage of every
extractable page, including the final text page:

```bash
PDF_TEST_URL='https://assets-c4akfrf5b4d3f4b7.z01.azurefd.net/assets/2026/05/2026_Work_Trend_Index_Annual_Report_050526-7_69fc5b1c4e265.pdf' \
  python -m unittest discover -s tests -p test_pdf_extraction.py -k LivePdfTests -v
```

GitHub Actions runs unit tests on pushes and pull requests, plus the live PDF
check as a separate pull-request job. The live check depends on the public PDF
remaining reachable; it exercises local text extraction, not model quality or OCR.
