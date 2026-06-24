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
- `/home/runner/work/asset-parser-demo/asset-parser-demo/skills/asset-content-parser/SKILL.md`

Prompt templates used by the runtime are in:
- `/home/runner/work/asset-parser-demo/asset-parser-demo/asset_parser/prompts/website_prompt.md`
- `/home/runner/work/asset-parser-demo/asset-parser-demo/asset_parser/prompts/pdf_prompt.md`
- `/home/runner/work/asset-parser-demo/asset-parser-demo/asset_parser/prompts/image_prompt.md`
