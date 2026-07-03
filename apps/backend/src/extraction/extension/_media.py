"""Media/payload building for vision + file inputs."""

import base64
import ipaddress
from io import BytesIO
from typing import Any
from urllib.parse import urlparse

import src.config
from src.extraction.extension._base import (
    ExtractionError,
    logger,
)

# Bound from the bare published root (config publishes no named symbols).
settings = src.config.settings


class _MediaMixin:
    def _is_zai_provider(self) -> bool:
        return settings.ai_provider.lower() in {"zai", "glm"}

    def _build_media_payload(self, file_type: str, mime_type: str, data: str) -> dict[str, Any]:
        """Build OpenAI-compatible media payload based on file type.

        PDFs use provider-supported external URL payloads when available,
        otherwise 'file' type for base64-compatible providers.
        """
        is_base64 = data.startswith("data:")
        is_external_url = data.startswith(("http://", "https://"))
        payload_type = "image_url"
        if file_type == "pdf":
            payload_type = "image_url" if self._is_zai_provider() and is_external_url else "file"
        logger.info(
            "Building media payload",
            file_type=file_type,
            mime_type=mime_type,
            payload_type=payload_type,
            data_source="base64" if is_base64 else "url",
            data_size=len(data) if is_base64 else None,
        )
        if file_type == "pdf" and self._is_zai_provider() and is_external_url:
            return {
                "type": "image_url",
                "image_url": {"url": data},
            }
        if file_type == "pdf":
            return {
                "type": "file",
                "file": {
                    "filename": f"statement.{file_type}",
                    "file_data": data,
                },
            }
        return {
            "type": "image_url",
            "image_url": {"url": data},
        }

    def _render_pdf_pages_as_image_payloads(self, file_content: bytes) -> list[dict[str, Any]]:
        """Render a bounded number of PDF pages to in-memory image_url payloads."""
        try:
            import fitz  # type: ignore[import-untyped]
        except ImportError as e:  # pragma: no cover - dependency is installed in packaged runtime
            raise ExtractionError("PDF vision fallback requires PyMuPDF to render pages") from e

        if not file_content:
            raise ExtractionError("PDF vision fallback requires file content to render pages")

        try:
            document = fitz.open(stream=file_content, filetype="pdf")
        except Exception as e:
            raise ExtractionError("PDF vision fallback could not open PDF content") from e

        try:
            page_count = min(len(document), self.PDF_VISION_MAX_PAGES)
            if page_count <= 0:
                raise ExtractionError("PDF vision fallback could not render an empty PDF")

            matrix = fitz.Matrix(self.PDF_VISION_RENDER_SCALE, self.PDF_VISION_RENDER_SCALE)
            payloads: list[dict[str, Any]] = []
            total_bytes = 0
            for page_index in range(page_count):
                page = document.load_page(page_index)
                pixmap = page.get_pixmap(matrix=matrix, alpha=False)
                buffer = BytesIO(pixmap.tobytes("png"))
                image_bytes = buffer.getvalue()
                total_bytes += len(image_bytes)
                encoded = base64.b64encode(image_bytes).decode("utf-8")
                payloads.append(
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/png;base64,{encoded}"},
                    }
                )

            logger.info(
                "Rendered PDF pages for vision fallback",
                rendered_pages=page_count,
                max_pages=self.PDF_VISION_MAX_PAGES,
                total_image_bytes=total_bytes,
            )
            return payloads
        finally:
            document.close()

    def _build_vision_media_payloads(
        self,
        file_content: bytes | None,
        file_url: str | None,
        file_type: str,
        mime_type: str,
    ) -> list[dict[str, Any]]:
        """Build vision-model media payloads, rendering Z.AI PDFs to images when possible."""
        if file_type == "pdf" and self._is_zai_provider() and file_content:
            try:
                return self._render_pdf_pages_as_image_payloads(file_content)
            except ExtractionError as render_error:
                if file_url and self._validate_external_url(file_url):
                    logger.warning(
                        "PDF page rendering failed, falling back to external PDF URL",
                        error=str(render_error),
                        url=_redact_presigned_url(file_url),
                    )
                else:
                    raise

        prefer_url = self._requires_pdf_file_url_for_vision(file_type)
        file_input = self._build_ai_file_input(
            file_content,
            file_url,
            file_type,
            mime_type,
            prefer_url=prefer_url,
        )
        if prefer_url and not file_input.startswith(("http://", "https://")):
            raise ExtractionError("Z.AI PDF vision fallback requires file content or an external PDF URL")
        return [self._build_media_payload(file_type=file_type, mime_type=mime_type, data=file_input)]

    def _validate_external_url(self, url: str) -> bool:
        """Validate if a URL is accessible by external AI services.

        Rejects:
        - Private IP ranges (RFC 1918, RFC 4193, etc.)
        - Localhost names
        - Internal Docker DNS names (e.g., http://minio:9000)

        Returns:
        - True if the URL appears to be a valid, externally routable URL.
        - False if the URL is invalid, uses localhost, resolves to a private/loopback/link-local
          address, or appears to be an internal service name.
        """
        try:
            parsed = urlparse(url)
            hostname = parsed.hostname
            if not hostname:
                return False

            # Reject localhost by name
            if hostname.lower() == "localhost":
                return False

            # Check if it's an IP address (v4 or v6)
            try:
                ip = ipaddress.ip_address(hostname)
                if ip.is_private or ip.is_loopback or ip.is_link_local:
                    return False
            except ValueError:
                # Not an IP address, proceed to hostname checks
                pass

            # Reject common internal Docker/Kubernetes service names
            # Heuristic: If it has no dots, it's likely an internal service discovery name
            if "." not in hostname:
                return False

            return True
        except Exception as exc:
            url_preview = url[:100] if isinstance(url, str) else repr(url)[:100]
            logger.debug(
                "URL validation failed",
                url=url_preview if url else None,
                error=str(exc),
                error_type=type(exc).__name__,
            )
            return False

    def _build_ai_file_input(
        self,
        file_content: bytes | None,
        file_url: str | None,
        file_type: str,
        mime_type: str,
        *,
        prefer_url: bool = False,
    ) -> str:
        """Build URL or data URI input for AI provider file APIs."""
        if prefer_url and file_url and self._validate_external_url(file_url):
            return file_url
        if file_content:
            b64_content = base64.b64encode(file_content).decode("utf-8")
            return f"data:{mime_type};base64,{b64_content}"
        if file_url and self._validate_external_url(file_url):
            return file_url
        if file_url:
            logger.warning(
                "Rejected internal/private file URL for AI extraction",
                url=_redact_presigned_url(file_url),
            )
        raise ExtractionError(
            f"No valid file content or accessible URL provided for {file_type} extraction. "
            "Ensure file content is uploaded or URL is public."
        )

    def _requires_pdf_file_url_for_vision(self, file_type: str) -> bool:
        return file_type == "pdf" and self._is_zai_provider()


def _redact_presigned_url(url: str) -> str:
    # Imported lazily: src.services.storage pulls boto3 at module level, which
    # the minimal tooling env (that imports this package root) does not install.
    from src.services.storage import redact_presigned_url

    return redact_presigned_url(url)
