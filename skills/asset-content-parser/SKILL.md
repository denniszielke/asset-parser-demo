---
name: asset-content-parser
description: Parse remote website, PDF, and image sources into structured context JSON.
---

# Asset Content Parser Skill

Use this skill when you need to parse URLs that point to:
- Websites (HTML)
- PDF documents
- Images

## Output schema
Each extracted context must contain:
- `name`
- `url`
- `tags`
- `content`
- `type`

## Runtime behavior

- By default, the runtime summarizes all extracted content in ordered chunks of
  at most 24,000 characters, joins chunk summaries, retains the first title, and
  merges up to 10 unique lowercase tags.
- Use CLI `--no-enrich` or Python `parse_urls(..., enrich=False)` for complete
  extracted text/metadata without model calls or credentials. The schema stays
  unchanged; the name comes from the URL and tags contain the asset type.
- PDF output retains original page numbers. Pages without text emit a warning;
  OCR is not performed. Entirely textless or password-protected PDFs fail
  explicitly.
- Model/provider and invalid-output errors propagate instead of silently
  substituting truncated text.
- Image extraction currently supplies dimensions and mode, not visual content.

## Extraction prompts

### Website prompt
```
You extract relevant website context as JSON.
Return only one JSON object with keys: name, tags, content.
- name: short title for the page
- tags: list of up to 10 concise lowercase tags
- content: concise but information-rich summary focused on business or technical facts
```

### PDF prompt
```
You extract relevant PDF context as JSON.
Return only one JSON object with keys: name, tags, content.
- name: concise document title
- tags: list of up to 10 concise lowercase tags
- content: summary of key points, entities, and actionable information found in the PDF text
- Input may be one of several ordered chunks (chunk_index/chunk_count). Summarize all relevant information in the supplied chunk, including later-page findings and methodology; do not invent missing context.
```

### Image prompt
```
You extract relevant image context as JSON.
Return only one JSON object with keys: name, tags, content.
- name: concise name of what the image represents
- tags: list of up to 10 concise lowercase tags
- content: summary of relevant information visible in the image and inferred context
```
