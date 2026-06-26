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

# Characters sent to the LLM per request (leave room for prompt + JSON overhead).
_MAX_LLM_CHARS = 24_000
# Characters stored in the fallback `content` field when the LLM call fails.
_MAX_FALLBACK_CHARS = 4_000


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


def _download(url: str, working_dir: Path, verify_ssl: bool = True) -> tuple[Path, str | None]:
    """Download *url* into *working_dir* and return the local path plus the
    response ``Content-Type`` header value.

    Set *verify_ssl* to ``False`` to skip TLS certificate verification (useful
    in corporate proxy environments with self-signed certificates; controlled by
    the ``ASSET_PARSER_VERIFY_SSL`` environment variable).
    """
    import httpx

    target = working_dir / _file_name_from_url(url)
    logger.debug("Downloading %s → %s", url, target)
    with httpx.Client(timeout=60.0, follow_redirects=True, verify=verify_ssl) as client:
        response = client.get(url)
        response.raise_for_status()
        target.write_bytes(response.content)
        logger.debug("Downloaded %d bytes (content-type: %s)", len(response.content), response.headers.get("content-type"))
        return target, response.headers.get("content-type")


def _extract_website(file_path: Path) -> str:
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(file_path.read_text(encoding="utf-8", errors="ignore"), "html.parser")
    for element in soup(["script", "style", "noscript"]):
        element.decompose()
    return "\n".join(line for line in soup.get_text(separator="\n", strip=True).splitlines() if line).strip()


def _extract_pdf(file_path: Path) -> str:
    """Extract text from a PDF file.

    The returned string starts with a metadata header (title, author, subject,
    page count) followed by the per-page text.  This header helps the LLM
    produce more accurate ``name`` and ``tags`` values even when the visible
    page text is sparse.
    """
    import fitz

    pages: list[str] = []
    with fitz.open(file_path) as document:
        meta = document.metadata or {}
        page_count = document.page_count

        # Build a metadata preamble so the LLM always has document-level context.
        meta_lines: list[str] = [f"Page count: {page_count}"]
        for key in ("title", "author", "subject", "keywords"):
            value = (meta.get(key) or "").strip()
            if value:
                meta_lines.append(f"{key.capitalize()}: {value}")
        preamble = "--- Document Metadata ---\n" + "\n".join(meta_lines)

        for index, page in enumerate(document, start=1):
            try:
                text = page.get_text("text").strip()
            except Exception as exc:  # noqa: BLE001
                logger.warning("Failed to extract text from page %d: %s", index, exc)
                continue
            if text:
                pages.append(f"Page {index}:\n{text}")

    body = "\n\n".join(pages).strip()
    return f"{preamble}\n\n--- Document Text ---\n{body}" if body else preamble


def _extract_image(file_path: Path) -> str:
    from PIL import Image

    with Image.open(file_path) as image:
        width, height = image.size
        mode = image.mode
        fmt = image.format or file_path.suffix.lstrip(".").upper()
    return f"Image file: format={fmt}, dimensions={width}x{height}, color_mode={mode}."


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
        "raw_content": extracted_content[:_MAX_LLM_CHARS],
    }
    fallback_name = Path(urlparse(source_url).path).name or source_url
    fallback_tags = [source_type]

    try:
        result = extract_json_with_model(model=model, prompt=prompt, user_payload=payload)
        return ParsedContext(
            name=str(result.get("name") or fallback_name),
            url=source_url,
            tags=[str(tag) for tag in (result.get("tags") or fallback_tags)],
            content=str(result.get("content") or extracted_content[:_MAX_FALLBACK_CHARS]),
            type=source_type,
        )
    except Exception as exc:
        logger.warning("LLM enrichment failed for %s (%s): %s", source_url, source_type, exc)
        return ParsedContext(
            name=fallback_name,
            url=source_url,
            tags=fallback_tags,
            content=extracted_content[:_MAX_FALLBACK_CHARS],
            type=source_type,
        )


def parse_urls(
    urls: list[str],
    working_dir: str,
    model: str,
    verify_ssl: bool = True,
) -> list[dict[str, Any]]:
    """Download and parse each URL, returning a list of structured context dicts.

    Processing errors for individual URLs are logged and result in an ``error``
    entry rather than aborting the entire batch.

    Args:
        urls: Remote URLs to download and parse.
        working_dir: Local directory for downloaded files (created if absent).
        model: Model identifier / deployment name used for LLM enrichment.
        verify_ssl: Whether to verify TLS certificates during download.
            Defaults to the ``ASSET_PARSER_VERIFY_SSL`` env variable
            (``"false"`` disables verification) or ``True``.
    """
    work = Path(working_dir).resolve()
    work.mkdir(parents=True, exist_ok=True)

    contexts: list[dict[str, Any]] = []
    for url in urls:
        try:
            downloaded_path, content_type = _download(url, work, verify_ssl=verify_ssl)
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
            logger.error("Failed to process URL %s: %s", url, exc)
            contexts.append({"url": url, "error": str(exc)})

    return contexts


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    parser = argparse.ArgumentParser(description="Download URLs and extract structured contexts.")
    parser.add_argument("urls", nargs="+", help="One or more URLs to parse")
    parser.add_argument("--working-dir", default="./working", help="Local working directory for downloads")
    parser.add_argument("--model", default=os.getenv("MODEL_NAME", "openai/gpt-4.1-mini"), help="Model id")
    parser.add_argument("--output", default="", help="Optional path to write resulting JSON")
    parser.add_argument(
        "--no-verify-ssl",
        action="store_true",
        default=os.getenv("ASSET_PARSER_VERIFY_SSL", "true").lower() == "false",
        help="Disable TLS certificate verification (e.g. for corporate proxies)",
    )
    args = parser.parse_args()

    result = parse_urls(
        urls=args.urls,
        working_dir=args.working_dir,
        model=args.model,
        verify_ssl=not args.no_verify_ssl,
    )
    output = json.dumps(result, indent=2, ensure_ascii=False)

    if args.output:
        Path(args.output).write_text(output, encoding="utf-8")
    print(output)


if __name__ == "__main__":
    main()
