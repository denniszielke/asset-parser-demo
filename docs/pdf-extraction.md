# PDF extraction validation

This project downloads remote PDF assets, extracts text page by page, and passes the full extracted content into the model prompt.

## Behavior

- PDF files are detected from either the HTTP `Content-Type` header or the file extension.
- Extraction uses PyMuPDF (`pymupdf`) and keeps page markers in the final text as `[Page N]`.
- The runtime sends up to `MAX_PROMPT_CHARS` of PDF text to the model.
- If model enrichment fails, the runtime falls back to a deterministic summary using the first `MAX_FALLBACK_CONTENT_CHARS` of extracted text.

## Validation fixture

The repository includes a real-world PDF fixture:

- `tests/fixtures/work_trend_index_2026.pdf`

This fixture is used to verify that multi-page reports extract with page markers and sufficient text volume.

## Example

```bash
python main.py \
  --working-dir ./working \
  --output ./result.json \
  https://assets-c4akfrf5b4d3f4b7.z01.azurefd.net/assets/2026/05/2026_Work_Trend_Index_Annual_Report_050526-7_69fc5b1c4e265.pdf
```
