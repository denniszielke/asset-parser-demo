import argparse
import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .model_client import extract_json_with_model


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
    import httpx

    target = working_dir / _file_name_from_url(url)
    with httpx.Client(timeout=60.0, follow_redirects=True) as client:
        response = client.get(url)
        response.raise_for_status()
        target.write_bytes(response.content)
        return target, response.headers.get("content-type")


def _extract_website(file_path: Path) -> str:
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(file_path.read_text(encoding="utf-8", errors="ignore"), "html.parser")
    for element in soup(["script", "style", "noscript"]):
        element.decompose()
    return "\n".join(line for line in soup.get_text(separator="\n", strip=True).splitlines() if line).strip()


def _extract_pdf(file_path: Path) -> str:
    import fitz

    pages: list[str] = []
    with fitz.open(file_path) as document:
        for index, page in enumerate(document, start=1):
            text = page.get_text("text").strip()
            if text:
                pages.append(f"Page {index}:\n{text}")
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
