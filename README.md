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
- `--verbose`: enable debug-level logging (HTTP traces, extraction warnings)

### Behavior & safeguards
- Only `http`/`https` URLs are accepted; other schemes (e.g. `file://`) are rejected.
- Downloads are streamed to disk with a 200 MB size cap to avoid exhausting memory/disk on
  unexpectedly large or malicious files.
- PDF extraction uses `pymupdf` directly (the `fitz` alias is deprecated), skips
  password-protected files with a clear error, and continues past per-page failures
  instead of aborting the whole document.
- If a URL fails to download/parse, or the LLM enrichment call fails (e.g. auth/model
  errors), the runtime logs a warning/error and falls back to a best-effort result
  instead of crashing the whole batch. Failed URLs are reported with `"type": "error"`
  in the output and the raw extracted text is still used as `content` when enrichment
  fails.

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

## Testing

```bash
python -m unittest discover -s tests -v
```

PDF extraction was additionally verified end-to-end against a real-world 20 MB / 24-page
PDF (Microsoft's 2026 Work Trend Index Annual Report), successfully streaming the download,
detecting the asset type, and extracting ~54k characters of page-by-page text.
