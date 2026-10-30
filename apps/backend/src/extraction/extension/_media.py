"""Media/payload building for vision + file inputs."""

import base64
import ipaddress
from collections.abc import Iterator, Sequence
from typing import Any
from urllib.parse import urlparse

import src.config
from src.extraction.extension._base import (
    ExtractionError,
    logger,
)

# Bound from the bare published root (config publishes no named symbols).
settings = src.config.settings


class _PdfVisionBatchSequence(Sequence[list[dict[str, Any]]]):
    """Lazy per-batch PDF vision payload sequence that bounds in-process memory (#2595).

    Validates the PDF and page count upfront, then renders at most one batch of
    ``batch_size`` pages at a time on demand so a 30-page scanned PDF never holds
    all 30 rendered PNGs or base64 data URIs in memory simultaneously.
    """

    def __init__(
        self,
        *,
        owner: "_MediaMixin",
        file_content: bytes,
        page_count: int,
        batch_size: int,
    ) -> None:
        self._owner = owner
        self._file_content = file_content
        self.total_pages = page_count
        self.batch_size = batch_size
        self.batch_count = (page_count + batch_size - 1) // batch_size
        self.total_image_bytes = 0
        self._cached_batch_index: int | None = None
        self._cached_batch: list[dict[str, Any]] | None = None

    def __len__(self) -> int:
        return self.batch_count

    def _render_page_range(self, start_page: int, end_page: int) -> list[dict[str, Any]]:
        """Render ``[start_page, end_page)`` 0-based PDF pages while enforcing the cumulative byte ceiling."""
        fitz = self._owner._import_fitz()
        document = self._owner._open_pdf_document(fitz, self._file_content)
        try:
            batch: list[dict[str, Any]] = []
            max_total_bytes = getattr(
                self._owner,
                "PDF_VISION_MAX_TOTAL_IMAGE_BYTES",
                _MediaMixin.PDF_VISION_MAX_TOTAL_IMAGE_BYTES,
            )
            for page_index in range(start_page, end_page):
                payload, page_bytes = self._owner._render_pdf_page_image_payload(
                    document,
                    fitz,
                    page_index,
                )
                self.total_image_bytes += page_bytes
                if max_total_bytes > 0 and self.total_image_bytes > max_total_bytes:
                    raise ExtractionError(
                        f"Rendered PDF vision payloads ({self.total_image_bytes:,} bytes) exceed the "
                        f"{max_total_bytes:,} bytes in-process memory bound."
                    )
                batch.append(payload)
            return batch
        finally:
            document.close()
            fitz.TOOLS.store_shrink(100)

    def pop_head_tail_meta_pages(self) -> tuple[list[dict[str, Any]], list[int]]:
        """Render the deduplicated first ``batch_size`` and last ``batch_size`` pages for Stage 1 metadata (#2813).

        Also caches batch 0 so Stage 2 does not re-render pages 1..batch_size.
        """
        head_batch = self.pop_batch(0)
        self._cached_batch_index = 0
        self._cached_batch = head_batch

        head_end = min(self.total_pages, self.batch_size)
        tail_start = max(head_end, self.total_pages - self.batch_size)
        page_numbers = list(range(1, head_end + 1))
        meta_pages = list(head_batch)

        if tail_start < self.total_pages:
            meta_pages.extend(self._render_page_range(tail_start, self.total_pages))
            page_numbers.extend(range(tail_start + 1, self.total_pages + 1))

        return meta_pages, page_numbers

    def pop_batch(self, batch_index: int) -> list[dict[str, Any]]:
        """Render and return one batch without retaining it on the sequence."""
        if batch_index < 0:
            batch_index += self.batch_count
        if batch_index < 0 or batch_index >= self.batch_count:
            raise IndexError(batch_index)

        if self._cached_batch_index == batch_index and self._cached_batch is not None:
            batch = self._cached_batch
            self._cached_batch_index = None
            self._cached_batch = None
            return batch

        self._cached_batch_index = None
        self._cached_batch = None
        if batch_index == 0:
            self.total_image_bytes = 0

        start_page = batch_index * self.batch_size
        end_page = min(self.total_pages, start_page + self.batch_size)
        batch = self._render_page_range(start_page, end_page)
        if end_page == self.total_pages:
            logger.info(
                "Rendered PDF pages for vision fallback",
                rendered_pages=self.total_pages,
                pages_per_call=self.batch_size,
                batch_count=self.batch_count,
                total_image_bytes=self.total_image_bytes,
            )
        return batch

    def __iter__(self) -> Iterator[list[dict[str, Any]]]:
        for batch_index in range(self.batch_count):
            yield self.pop_batch(batch_index)

    def __getitem__(self, index: int | slice) -> Any:
        if isinstance(index, slice):
            return [self.pop_batch(i) for i in range(*index.indices(self.batch_count))]
        if index < 0:
            index += self.batch_count
        if index < 0 or index >= self.batch_count:
            raise IndexError(index)
        if self._cached_batch_index == index and self._cached_batch is not None:
            return self._cached_batch
        batch = self.pop_batch(index)
        self._cached_batch_index = index
        self._cached_batch = batch
        return batch


class _MediaMixin:
    PDF_VISION_MAX_PAGES = 5
    PDF_VISION_MAX_TOTAL_PAGES = 30
    PDF_VISION_RENDER_SCALE = 1.6
    PDF_VISION_FALLBACK_RENDER_SCALE = 1.0
    PDF_VISION_MAX_PAGE_IMAGE_BYTES = 1_500_000
    PDF_VISION_MAX_TOTAL_IMAGE_BYTES = 32 * 1024 * 1024

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

    @staticmethod
    def _import_fitz() -> Any:
        try:
            import fitz
        except ImportError as e:  # pragma: no cover - dependency is installed in packaged runtime
            raise ExtractionError("PDF vision fallback requires PyMuPDF to render pages") from e
        return fitz

    @staticmethod
    def _open_pdf_document(fitz: Any, file_content: bytes) -> Any:
        try:
            return fitz.open(stream=file_content, filetype="pdf")
        except Exception as e:
            raise ExtractionError("PDF vision fallback could not open PDF content") from e

    def _render_pdf_page_image_payload(
        self,
        document: Any,
        fitz: Any,
        page_index: int,
    ) -> tuple[dict[str, Any], int]:
        """Render a single PDF page to a PNG data-URI payload and shrink MuPDF's store (#2595)."""
        scale = getattr(self, "PDF_VISION_RENDER_SCALE", _MediaMixin.PDF_VISION_RENDER_SCALE)
        fallback_scale = getattr(
            self,
            "PDF_VISION_FALLBACK_RENDER_SCALE",
            _MediaMixin.PDF_VISION_FALLBACK_RENDER_SCALE,
        )
        max_page_bytes = getattr(
            self,
            "PDF_VISION_MAX_PAGE_IMAGE_BYTES",
            _MediaMixin.PDF_VISION_MAX_PAGE_IMAGE_BYTES,
        )

        page = document.load_page(page_index)
        try:
            pixmap = page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)
            image_bytes = pixmap.tobytes("png")
            del pixmap
            fitz.TOOLS.store_shrink(100)

            if max_page_bytes > 0 and len(image_bytes) > max_page_bytes:
                gray_pixmap = page.get_pixmap(
                    matrix=fitz.Matrix(fallback_scale, fallback_scale),
                    colorspace=fitz.csGRAY,
                    alpha=False,
                )
                downscaled_bytes = gray_pixmap.tobytes("png")
                del gray_pixmap
                fitz.TOOLS.store_shrink(100)
                if len(downscaled_bytes) < len(image_bytes):
                    image_bytes = downscaled_bytes
                del downscaled_bytes

                if len(image_bytes) > max_page_bytes:
                    reduced_scale = max(
                        0.5,
                        fallback_scale * ((max_page_bytes / len(image_bytes)) ** 0.5) * 0.9,
                    )
                    compact_pixmap = page.get_pixmap(
                        matrix=fitz.Matrix(reduced_scale, reduced_scale),
                        colorspace=fitz.csGRAY,
                        alpha=False,
                    )
                    compact_bytes = compact_pixmap.tobytes("png")
                    del compact_pixmap
                    fitz.TOOLS.store_shrink(100)
                    if len(compact_bytes) < len(image_bytes):
                        image_bytes = compact_bytes
                    del compact_bytes
        finally:
            del page
            fitz.TOOLS.store_shrink(100)

        page_byte_len = len(image_bytes)
        encoded = base64.b64encode(image_bytes).decode("utf-8")
        del image_bytes
        return (
            {
                "type": "image_url",
                "image_url": {"url": f"data:image/png;base64,{encoded}"},
            },
            page_byte_len,
        )

    def _render_pdf_pages_as_image_payload_batches(self, file_content: bytes) -> Sequence[list[dict[str, Any]]]:
        """Render EVERY PDF page to image_url payloads, grouped into per-call batches (#1832, #2595).

        Pre-#1832 this rendered only the first ``PDF_VISION_MAX_PAGES`` pages and
        silently dropped the rest — which made the running-balance chain
        mathematically guaranteed to fail for any statement longer than the cap
        and quarantined perfectly good documents. Now the cap is the per-request
        batch size; documents above ``PDF_VISION_MAX_TOTAL_PAGES`` fail with an
        explicit, honest error instead of truncating.

        #2595: returns a lazy batch sequence that renders one batch on demand and
        shrinks MuPDF's image store after each page so a 30-page scanned PDF
        never holds all 30 rendered pages in memory simultaneously.
        """
        fitz = self._import_fitz()
        if not file_content:
            raise ExtractionError("PDF vision fallback requires file content to render pages")

        document = self._open_pdf_document(fitz, file_content)
        try:
            page_count = len(document)
            if page_count <= 0:
                raise ExtractionError("PDF vision fallback could not render an empty PDF")
            if page_count > self.PDF_VISION_MAX_TOTAL_PAGES:
                raise ExtractionError(
                    f"PDF has {page_count} pages, above the "
                    f"{self.PDF_VISION_MAX_TOTAL_PAGES}-page vision-extraction limit. "
                    "Split the document into smaller parts and upload them separately."
                )
        finally:
            document.close()
            fitz.TOOLS.store_shrink(100)

        return _PdfVisionBatchSequence(
            owner=self,
            file_content=file_content,
            page_count=page_count,
            batch_size=self.PDF_VISION_MAX_PAGES,
        )

    def _build_vision_media_payload_batches(
        self,
        file_content: bytes | None,
        file_url: str | None,
        file_type: str,
        mime_type: str,
    ) -> Sequence[list[dict[str, Any]]]:
        """Build per-call vision media payload batches, rendering Z.AI PDFs to images when possible.

        Returns one batch per model call: multi-page PDFs produce several batches
        (all pages covered); every other input shape stays a single batch.
        """
        if file_type == "pdf" and self._is_zai_provider() and file_content:
            try:
                return self._render_pdf_pages_as_image_payload_batches(file_content)
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
        return [[self._build_media_payload(file_type=file_type, mime_type=mime_type, data=file_input)]]

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


def _redact_presigned_url(url: str) -> str | None:
    # Imported lazily: src.runtime.extension.storage pulls boto3 at module level, which
    # the minimal tooling env (that imports this package root) does not install.
    from src.runtime import redact_presigned_url

    return redact_presigned_url(url)
