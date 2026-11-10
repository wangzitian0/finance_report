from __future__ import annotations; import pytest; from common.runtime import release_images; _DIGEST_OUTPUT = 'Name: ghcr.io/example/backend:abc1234\nDigest: sha256:' + 'a' * 64
def test_AC_runtime_release_images_1_first_attempt_success_no_retry() -> None:
    'AC-runtime.release-images.1'; calls: list[str] = []
    def fake_inspect(image: str) -> tuple[int, str]: calls.append(image); return (0, _DIGEST_OUTPUT)
    def fake_sleep(_seconds: float) -> None: raise AssertionError('sleep should not be called when the first attempt succeeds')
    digests = release_images.verify_release_images(registry='ghcr.io', image_prefix='example', version_ref='abc1234', inspect_image=fake_inspect, sleep=fake_sleep); assert digests == {'backend_digest': 'sha256:' + 'a' * 64, 'frontend_digest': 'sha256:' + 'a' * 64}; assert len(calls) == 2
def test_AC_runtime_release_images_2_transient_miss_then_success_retries() -> None:
    'AC-runtime.release-images.2'; attempts: dict[str, int] = {}; sleeps: list[float] = []
    def fake_inspect(image: str) -> tuple[int, str]:
        attempts[image] = attempts.get(image, 0) + 1
        if attempts[image] < 3: return (1, '')
        return (0, _DIGEST_OUTPUT)
    digests = release_images.verify_release_images(registry='ghcr.io', image_prefix='example', version_ref='abc1234', inspect_image=fake_inspect, sleep=sleeps.append); assert digests['backend_digest'] == 'sha256:' + 'a' * 64; assert digests['frontend_digest'] == 'sha256:' + 'a' * 64; assert all((n == 3 for n in attempts.values())); assert len(sleeps) == 4
def test_AC_runtime_release_images_3_exhausted_retries_fails_closed() -> None:
    'AC-runtime.release-images.3'; fake_inspect = lambda _image: (1, '')
    with pytest.raises(RuntimeError, match='not found after 4 attempts'): release_images.verify_release_images(registry='ghcr.io', image_prefix='example', version_ref='abc1234', inspect_image=fake_inspect, sleep=lambda _s: None)
def test_AC_runtime_release_images_4_max_attempts_and_delay_are_configurable() -> None:
    'AC-runtime.release-images.4'; call_count = 0; sleeps: list[float] = []
    def fake_inspect(_image: str) -> tuple[int, str]: nonlocal call_count; call_count += 1; return (1, '')
    with pytest.raises(RuntimeError, match='not found after 2 attempts'): release_images.verify_release_images(registry='ghcr.io', image_prefix='example', version_ref='abc1234', inspect_image=fake_inspect, max_attempts=2, retry_delay_seconds=0.5, sleep=sleeps.append)
    assert call_count == 2; assert sleeps == [0.5]
def test_AC_runtime_release_images_5_max_attempts_below_1_is_rejected() -> None:
    'AC-runtime.release-images.5'
    with pytest.raises(ValueError, match='max_attempts must be >= 1'): release_images.verify_release_images(registry='ghcr.io', image_prefix='example', version_ref='abc1234', inspect_image=lambda _i: (0, _DIGEST_OUTPUT), max_attempts=0, sleep=lambda _s: None)
def test_AC_runtime_release_images_6_negative_delay_is_rejected() -> None:
    'AC-runtime.release-images.6'
    with pytest.raises(ValueError, match='retry_delay_seconds must be >= 0'): release_images.verify_release_images(registry='ghcr.io', image_prefix='example', version_ref='abc1234', inspect_image=lambda _i: (1, ''), retry_delay_seconds=-1.0, sleep=lambda _s: None)
    _m1_rc = release_images.main(['--registry', 'ghcr.io', '--image-prefix', 'example', '--version-ref', 'abc1234', '--dry-run']); assert _m1_rc == 0
