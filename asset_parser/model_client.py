from __future__ import annotations

import json
import os
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from openai import OpenAI


def _foundry_token() -> str:
    from azure.identity import DefaultAzureCredential, get_bearer_token_provider

    provider = get_bearer_token_provider(
        DefaultAzureCredential(),
        "https://cognitiveservices.azure.com/.default",
    )
    return provider()


def create_openai_client() -> OpenAI:
    from dotenv import load_dotenv
    from openai import OpenAI

    load_dotenv()
    github_token = os.getenv("GITHUB_TOKEN", "").strip()
    foundry_endpoint = os.getenv("FOUNDRY_PROJECT_ENDPOINT", "").strip()
    foundry_api_key = os.getenv("FOUNDRY_API_KEY", "").strip()

    if foundry_endpoint:
        api_key = foundry_api_key or _foundry_token()
        base_url = foundry_endpoint.rstrip("/") + "/models"
        return OpenAI(base_url=base_url, api_key=api_key)

    if github_token:
        return OpenAI(
            base_url="https://models.github.ai/inference",
            api_key=github_token,
        )

    raise RuntimeError(
        "No model auth configured. Set either FOUNDRY_PROJECT_ENDPOINT (+optional FOUNDRY_API_KEY) or GITHUB_TOKEN."
    )


def extract_json_with_model(model: str, prompt: str, user_payload: Any) -> dict[str, Any]:
    client = create_openai_client()
    response = client.chat.completions.create(
        model=model,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": prompt},
            {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False)},
        ],
    )
    if not response.choices or not response.choices[0].message.content:
        raise ValueError("Model returned no JSON content")
    result = json.loads(response.choices[0].message.content)
    if not isinstance(result, dict):
        raise ValueError("Model response must be a JSON object")
    return result
