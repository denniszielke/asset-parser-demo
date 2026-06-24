import argparse
import hashlib
import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .model_client import extract_json_with_model

logger = logging.getLogger(__name__)


@dataclass
class ParsedContext:
    name: str
    url: str
    tags: list[str]
    content: str
    type: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "url": self.url,
            "tags": self.tags,
            "content": self.content,
            "type": self.type,
        }


def _read_prompt(prompt_name: str) -> str:
    prompt_path = Path(__file__).parent / "prompts" / prompt_name
    return prompt_path.read_text(encoding="utf-8")


def _file_name_from_url(url: str) -> str:
    parsed = urlparse(url)
    candidate = os.path.basename(parsed.path) or "downloaded_asset"
    if "." not in candidate:
        candidate += ".bin"
    digest = hashlib.sha256(url.encode("utf-8")).hexdigest()[:8]
    return f"{digest}_{candidate}"


def _detect_type(file_path: Path, content_type: str | None) -> str:
    ctype = (content_type or "").lower()
    suffix = file_path.suffix.lower()
    if "pdf" in ctype or suffix == ".pdf":
        return "pdf"
    if "image" in ctype or suffix in {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".tif", ".tiff"}:
        return "image"
    return "website"


def _download(url: str, working_dir: Path) -> tuple[Path, str | None]:
    """Download *url* into *working_dir*, streaming to avoid large memory spikes.

    Falls back to ``verify=False`` when SSL certificate verification fails so
    the tool works in environments with self-signed or missing CA certificates.
    A warning is emitted in that case.
    """
    import httpx

    target = working_dir / _file_name_from_url(url)

    def _stream(verify: bool) -> tuple[str | None]:  # type: ignore[return]
        with httpx.Client(timeout=120.0, follow_redirects=True, verify=verify) as client:
            with client.stream("GET", url) as response:
                response.raise_for_status()
                content_type = response.headers.get("content-type")
                with target.open("wb") as fh:
                    for chunk in response.iter_bytes(chunk_size=65536):
                        fh.write(chunk)
                return content_type

    try:
        content_type = _stream(verify=True)
    except Exception as exc:
        ssl_related = "certificate" in str(exc).lower() or "ssl" in str(exc).lower()
        if ssl_related:
            logger.warning(
                "SSL verification failed for %s (%s); retrying without verification.", url, exc
            )
            if target.exists():
                target.unlink()
            content_type = _stream(verify=False)
        else:
            if target.exists():
                target.unlink()
            raise

    return target, content_type


def _extract_website(file_path: Path) -> str:
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(file_path.read_text(encoding="utf-8", errors="ignore"), "html.parser")
    for element in soup(["script", "style", "noscript"]):
        element.decompose()
    return "\n".join(line for line in soup.get_text(separator="\n", strip=True).splitlines() if line).strip()


def _extract_pdf(file_path: Path) -> str:
    """Extract text and metadata from a PDF file.

    Returns a string that begins with a metadata header (title, author,
    page count, creation date when available) followed by per-page text.
    Using ``get_text("blocks")`` preserves the reading order for
    multi-column layouts better than the default ``"text"`` mode.
    """
    import fitz

    sections: list[str] = []
    with fitz.open(file_path) as document:
        meta = document.metadata or {}
        meta_lines: list[str] = [f"Pages: {document.page_count}"]
        for key in ("title", "author", "creationDate", "subject", "keywords"):
            value = meta.get(key, "").strip()
            if value:
                meta_lines.append(f"{key.capitalize()}: {value}")
        sections.append("Metadata:\n" + "\n".join(meta_lines))

        for index, page in enumerate(document, start=1):
            blocks = page.get_text("blocks")  # type: ignore[arg-type]
            # Each block is (x0, y0, x1, y1, text, block_no, block_type)
            # block_type 0 = text; sort by vertical then horizontal position
            text_blocks = sorted(
                (b for b in blocks if b[6] == 0),
                key=lambda b: (round(b[1] / 20) * 20, b[0]),
            )
            page_text = "\n".join(b[4].strip() for b in text_blocks if b[4].strip())
            if page_text:
                sections.append(f"Page {index}:\n{page_text}")

    return "\n\n".join(sections).strip()


def _extract_image(file_path: Path) -> str:
    """Return basic metadata for an image file (dimensions, mode, format)."""
    from PIL import Image

    with Image.open(file_path) as image:
        width, height = image.size
        mode = image.mode
        fmt = image.format or file_path.suffix.lstrip(".").upper() or "unknown"
    return (
        f"Image file: format={fmt}, dimensions={width}x{height}, color_mode={mode}."
    )


def _llm_enrich(
    model: str,
    prompt_name: str,
    source_type: str,
    source_url: str,
    extracted_content: str,
) -> ParsedContext:
    prompt = _read_prompt(prompt_name)
    payload = {
        "url": source_url,
        "type": source_type,
        "raw_content": extracted_content[:24000],
    }
    fallback_name = Path(urlparse(source_url).path).name or source_url
    fallback_tags = [source_type]

    try:
        result = extract_json_with_model(model=model, prompt=prompt, user_payload=payload)
        return ParsedContext(
            name=str(result.get("name") or fallback_name),
            url=source_url,
            tags=[str(tag) for tag in (result.get("tags") or fallback_tags)],
            content=str(result.get("content") or extracted_content[:4000]),
            type=source_type,
        )
    except Exception:
        return ParsedContext(
            name=fallback_name,
            url=source_url,
            tags=fallback_tags,
            content=extracted_content[:4000],
            type=source_type,
        )


def parse_urls(urls: list[str], working_dir: str, model: str) -> list[dict[str, Any]]:
    work = Path(working_dir).resolve()
    work.mkdir(parents=True, exist_ok=True)

    contexts: list[dict[str, Any]] = []
    for url in urls:
        downloaded_path, content_type = _download(url, work)
        asset_type = _detect_type(downloaded_path, content_type)

        if asset_type == "pdf":
            extracted = _extract_pdf(downloaded_path)
            context = _llm_enrich(model, "pdf_prompt.md", asset_type, url, extracted)
        elif asset_type == "image":
            extracted = _extract_image(downloaded_path)
            context = _llm_enrich(model, "image_prompt.md", asset_type, url, extracted)
        else:
            extracted = _extract_website(downloaded_path)
            context = _llm_enrich(model, "website_prompt.md", asset_type, url, extracted)

        contexts.append(context.to_dict())

    return contexts


def main() -> None:
    parser = argparse.ArgumentParser(description="Download URLs and extract structured contexts.")
    parser.add_argument("urls", nargs="+", help="One or more URLs to parse")
    parser.add_argument("--working-dir", default="./working", help="Local working directory for downloads")
    parser.add_argument("--model", default=os.getenv("MODEL_NAME", "openai/gpt-4.1-mini"), help="Model id")
    parser.add_argument("--output", default="", help="Optional path to write resulting JSON")
    args = parser.parse_args()

    result = parse_urls(urls=args.urls, working_dir=args.working_dir, model=args.model)
    output = json.dumps(result, indent=2, ensure_ascii=False)

    if args.output:
        Path(args.output).write_text(output, encoding="utf-8")
    print(output)


if __name__ == "__main__":
    main()
