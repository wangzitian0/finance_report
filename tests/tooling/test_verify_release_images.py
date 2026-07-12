"""Release-image digest verification retry behavior (AC-runtime.release-images.*).

Behavioral tests only — no source-text mirroring (see #1435): each test calls
``verify_release_images`` directly with an injected ``inspect_image``/``sleep``,
following the same DI pattern as tests/tooling/test_real_corpus_eval_evidence.py.
"""

from __future__ import annotations

import pytest

from common.runtime import release_images

_DIGEST_OUTPUT = "Name: ghcr.io/example/backend:abc1234\nDigest: sha256:" + "a" * 64


def test_AC_runtime_release_images_1_first_attempt_success_no_retry() -> None:
    """AC-runtime.release-images.1: a digest found on the first inspect needs
    no retry and no sleep call."""
    calls: list[str] = []

    def fake_inspect(image: str) -> tuple[int, str]:
        calls.append(image)
        return 0, _DIGEST_OUTPUT

    def fake_sleep(_seconds: float) -> None:
        raise AssertionError(
            "sleep should not be called when the first attempt succeeds"
        )

    digests = release_images.verify_release_images(
        registry="ghcr.io",
        image_prefix="example",
        version_ref="abc1234",
        inspect_image=fake_inspect,
        sleep=fake_sleep,
    )
    assert digests == {
        "backend_digest": "sha256:" + "a" * 64,
        "frontend_digest": "sha256:" + "a" * 64,
    }
    # One inspect per service, not multiplied by any retry.
    assert len(calls) == 2


def test_AC_runtime_release_images_2_transient_miss_then_success_retries() -> None:
    """AC-runtime.release-images.2: a not-yet-visible digest (e.g. registry
    propagation lag right after container-images pushes :<sha>) is retried,
    not treated as a hard failure, as long as it succeeds within max_attempts."""
    attempts: dict[str, int] = {}
    sleeps: list[float] = []

    def fake_inspect(image: str) -> tuple[int, str]:
        attempts[image] = attempts.get(image, 0) + 1
        if attempts[image] < 3:
            return 1, ""
        return 0, _DIGEST_OUTPUT

    digests = release_images.verify_release_images(
        registry="ghcr.io",
        image_prefix="example",
        version_ref="abc1234",
        inspect_image=fake_inspect,
        sleep=sleeps.append,
    )
    assert digests["backend_digest"] == "sha256:" + "a" * 64
    assert digests["frontend_digest"] == "sha256:" + "a" * 64
    # 2 failed + 1 success per service = 3 attempts each; 2 sleeps per service
    # (between attempts 1->2 and 2->3), never a sleep after the final success.
    assert all(n == 3 for n in attempts.values())
    assert len(sleeps) == 4


def test_AC_runtime_release_images_3_exhausted_retries_fails_closed() -> None:
    """AC-runtime.release-images.3: an image that never becomes visible still
    fails — retrying bounds the flake tolerance, it does not remove the
    guarantee that a truly missing image fails the gate."""

    def fake_inspect(_image: str) -> tuple[int, str]:
        return 1, ""

    with pytest.raises(RuntimeError, match="not found after 4 attempts"):
        release_images.verify_release_images(
            registry="ghcr.io",
            image_prefix="example",
            version_ref="abc1234",
            inspect_image=fake_inspect,
            sleep=lambda _s: None,
        )


def test_AC_runtime_release_images_4_max_attempts_and_delay_are_configurable() -> None:
    """AC-runtime.release-images.4: callers can tune max_attempts/retry_delay_seconds
    (e.g. a caller with tighter time budget) instead of being locked to the default."""
    call_count = 0

    def fake_inspect(_image: str) -> tuple[int, str]:
        nonlocal call_count
        call_count += 1
        return 1, ""

    with pytest.raises(RuntimeError, match="not found after 2 attempts"):
        release_images.verify_release_images(
            registry="ghcr.io",
            image_prefix="example",
            version_ref="abc1234",
            inspect_image=fake_inspect,
            max_attempts=2,
            sleep=lambda _s: None,
        )
    # 2 attempts for backend before it raises -- frontend is never reached.
    assert call_count == 2
