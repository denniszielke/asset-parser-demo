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

Use `--no-model` to return all locally extracted text without model credentials.
PDF text includes source page numbers and is sorted into reading order; this is
not OCR or guaranteed layout/table reconstruction. Password-protected and
textless PDFs fail explicitly. Model enrichment processes every 24,000-character
chunk and concatenates the chunk summaries; failures are not silently replaced
with truncated source text.

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
- Input may be one chunk of a longer PDF. Summarize all supplied text, including later findings and methodology, without inventing missing context.
- Preserve important numbers, qualifications, and source page numbers when available.
```

### Image prompt
```
You extract relevant image context as JSON.
Return only one JSON object with keys: name, tags, content.
- name: concise name of what the image represents
- tags: list of up to 10 concise lowercase tags
- content: summary of relevant information visible in the image and inferred context
```
