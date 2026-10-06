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

logger = logging.getLogger("asset_parser")

# Allowed URL schemes for downloads. Blocks file://, ftp://, etc. to avoid SSRF-like misuse.
_ALLOWED_SCHEMES = {"http", "https"}

# Default cap on downloaded asset size to avoid exhausting memory/disk on huge or malicious files.
_DEFAULT_MAX_DOWNLOAD_BYTES = 200 * 1024 * 1024  # 200 MB


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


def _download(
    url: str,
    working_dir: Path,
    max_bytes: int = _DEFAULT_MAX_DOWNLOAD_BYTES,
    timeout: float = 60.0,
) -> tuple[Path, str | None]:
    import httpx

    parsed = urlparse(url)
    if parsed.scheme not in _ALLOWED_SCHEMES:
        raise ValueError(f"Unsupported URL scheme '{parsed.scheme}' for '{url}'. Only http/https are allowed.")

    target = working_dir / _file_name_from_url(url)
    downloaded = 0
    with httpx.Client(timeout=timeout, follow_redirects=True) as client:
        with client.stream("GET", url) as response:
            response.raise_for_status()
            content_length = response.headers.get("content-length")
            if content_length and int(content_length) > max_bytes:
                raise ValueError(
                    f"Refusing to download '{url}': reported size {content_length} bytes exceeds limit {max_bytes}."
                )
            with target.open("wb") as handle:
                for chunk in response.iter_bytes():
                    downloaded += len(chunk)
                    if downloaded > max_bytes:
                        handle.close()
                        target.unlink(missing_ok=True)
                        raise ValueError(
                            f"Refusing to download '{url}': exceeded size limit of {max_bytes} bytes."
                        )
                    handle.write(chunk)
            content_type = response.headers.get("content-type")

    if downloaded == 0:
        logger.warning("Downloaded zero bytes from %s", url)

    return target, content_type


def _extract_website(file_path: Path) -> str:
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(file_path.read_text(encoding="utf-8", errors="ignore"), "html.parser")
    for element in soup(["script", "style", "noscript"]):
        element.decompose()
    return "\n".join(line for line in soup.get_text(separator="\n", strip=True).splitlines() if line).strip()


def _extract_pdf(file_path: Path) -> str:
    import pymupdf  # `fitz` is the deprecated alias for the same package.

    pages: list[str] = []
    with pymupdf.open(file_path) as document:
        if document.is_encrypted and not document.authenticate(""):
            raise ValueError(f"PDF '{file_path.name}' is password-protected and cannot be read.")

        for index, page in enumerate(document, start=1):
            try:
                text = page.get_text("text").strip()
            except Exception:
                logger.warning("Failed to extract text from page %d of %s", index, file_path.name)
                continue
            if text:
                pages.append(f"Page {index}:\n{text}")

    if not pages:
        logger.warning("No extractable text found in %s (it may be scanned/image-only).", file_path.name)

    return "\n\n".join(pages).strip()


def _extract_image(file_path: Path) -> str:
    from PIL import Image

    with Image.open(file_path) as image:
        width, height = image.size
        mode = image.mode
    return f"Image file with dimensions {width}x{height} and color mode {mode}."


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
    except Exception as exc:
        logger.warning(
            "LLM enrichment failed for %s (%s); falling back to raw extracted content: %s",
            source_url,
            source_type,
            exc,
        )
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
        try:
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
        except Exception as exc:
            logger.error("Failed to parse %s: %s", url, exc)
            contexts.append(
                {
                    "name": url,
                    "url": url,
                    "tags": ["error"],
                    "content": f"Failed to parse asset: {exc}",
                    "type": "error",
                }
            )

    return contexts


def main() -> None:
    parser = argparse.ArgumentParser(description="Download URLs and extract structured contexts.")
    parser.add_argument("urls", nargs="+", help="One or more URLs to parse")
    parser.add_argument("--working-dir", default="./working", help="Local working directory for downloads")
    parser.add_argument("--model", default=os.getenv("MODEL_NAME", "openai/gpt-4.1-mini"), help="Model id")
    parser.add_argument("--output", default="", help="Optional path to write resulting JSON")
    parser.add_argument("--verbose", action="store_true", help="Enable verbose (debug) logging")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )

    result = parse_urls(urls=args.urls, working_dir=args.working_dir, model=args.model)
    output = json.dumps(result, indent=2, ensure_ascii=False)

    if args.output:
        Path(args.output).write_text(output, encoding="utf-8")
    print(output)


if __name__ == "__main__":
    main()
