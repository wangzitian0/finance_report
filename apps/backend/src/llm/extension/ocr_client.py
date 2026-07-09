"""Dedicated OCR/layout-parsing transport (#1670).

Chat/JSON completions go through ``litellm_stream``; the layout-parsing OCR
endpoint is a separate, non-chat HTTP API that litellm does not wrap, so it
gets its own thin transport function — the single chokepoint for this call,
mirroring ``build_call`` for the litellm path.
"""

from __future__ import annotations

import httpx

from src.llm.base.errors import LLMError
from src.observability import get_logger, safe_error_message

logger = get_logger(__name__)


async def ocr_layout_call(
    *,
    base_url: str,
    layout_parsing_path: str,
    api_key: str,
    model: str,
    file_input: str,
    timeout: httpx.Timeout,
) -> str:
    """POST a document to the OCR layout-parsing endpoint; return its Markdown.

    Raises :class:`LLMError` on a non-200 response or an empty/malformed
    result.
    """
    layout_url = f"{base_url.rstrip('/')}/{layout_parsing_path.lstrip('/')}"
    payload = {
        "model": model,
        "file": file_input,
        "return_crop_images": False,
        "need_layout_visualization": False,
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    logger.info(
        "Sending document to OCR layout parser",
        model=model,
        data_source="base64" if file_input.startswith("data:") else "url",
    )

    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.post(layout_url, headers=headers, json=payload)

    if response.status_code != 200:
        safe_summary = safe_error_message(response.text)
        logger.error(
            "OCR layout parsing failed",
            model=model,
            status_code=response.status_code,
            safe_error_message=safe_summary,
        )
        raise LLMError(f"OCR layout parsing failed: HTTP {response.status_code}: {safe_summary}")

    result = response.json()
    markdown = result.get("md_results")
    if isinstance(markdown, list):
        markdown = "\n\n".join(str(item) for item in markdown if item)
    if not isinstance(markdown, str) or not markdown.strip():
        raise LLMError("OCR layout parsing returned empty Markdown")

    logger.info("OCR layout parsing completed", model=model, markdown_length=len(markdown))
    return markdown
