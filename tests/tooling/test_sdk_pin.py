"""AC-runtime.sdk-pin.1: bootstrap consumes the declared, hashed SDK artifact."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def test_AC_runtime_sdk_pin_1_lock_and_declaration_must_agree(tmp_path):
    from common.runtime.sdk_pin import read_sdk_pin

    backend = tmp_path / "apps/backend"
    backend.mkdir(parents=True)
    version = "1.9.2"
    filename = f"infra2_sdk-{version}-py3-none-any.whl"
    url = f"https://github.com/wangzitian0/infra2-sdk/releases/download/v{version}/{filename}"
    declaration = f"infra2-sdk @ {url}"
    project = "[project]\ndependencies = [" + json.dumps(declaration) + "]\n"
    lock = (
        '[[package]]\nname = "infra2-sdk"\nversion = "1.9.2"\n'
        f'source = {{ url = "{url}" }}\n'
        f'wheels = [{{ url = "{url}", hash = "sha256:{"a" * 64}" }}]\n'
    )
    (backend / "pyproject.toml").write_text(project)
    (backend / "uv.lock").write_text(lock)
    assert read_sdk_pin(tmp_path) == (url, "a" * 64, filename)

    for corrupted in (
        lock.replace('version = "1.9.2"', 'version = "1.9.1"'),
        lock.replace('version = "1.9.2"', 'version = "latest"'),
        lock.replace("a" * 64, "not-a-digest"),
        lock.replace(url, url.replace("1.9.2", "1.9.3")),
        lock.replace(lock.splitlines()[-1], 'wheels = "invalid"'),
        lock.replace("wheels = [", "wheels = [42, "),
        lock.replace(f'"sha256:{"a" * 64}"', "42"),
        lock + lock,
    ):
        (backend / "uv.lock").write_text(corrupted)
        with pytest.raises(ValueError, match="infra2-sdk"):
            read_sdk_pin(tmp_path)

    (backend / "uv.lock").write_text(lock)
    (backend / "pyproject.toml").write_text(project.replace("1.9.2", "1.9.3"))
    with pytest.raises(ValueError, match="infra2-sdk"):
        read_sdk_pin(tmp_path)


def test_AC_runtime_sdk_pin_1_bootstrap_needs_only_standard_library():
    from common.runtime.sdk_pin import read_sdk_pin

    result = subprocess.run(
        [sys.executable, "-S", str(ROOT / "tools/sdk_pin.py")],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    assert result.stdout.strip().split() == list(read_sdk_pin(ROOT))


@pytest.mark.parametrize(
    ("filename", "content", "field"),
    [
        ("pyproject.toml", "", "project"),
        ("pyproject.toml", '[project]\ndependencies = "invalid"\n', "dependencies"),
        ("pyproject.toml", "[project]\ndependencies = [42]\n", "dependencies"),
        ("uv.lock", "", "package"),
        ("uv.lock", 'package = "invalid"\n', "package"),
        ("uv.lock", "package = [42]\n", "package"),
        ("uv.lock", '[[package]]\nversion = "1.5.1"\n', "package"),
    ],
)
def test_sdk_pin_reports_malformed_field(tmp_path, filename, content, field):
    """AC-runtime.sdk-pin.1: malformed input names its source file and field."""
    from common.runtime.sdk_pin import read_sdk_pin

    backend = tmp_path / "apps/backend"
    backend.mkdir(parents=True)
    for name in ("pyproject.toml", "uv.lock"):
        (backend / name).write_text((ROOT / "apps/backend" / name).read_text())
    (backend / filename).write_text(content)
    with pytest.raises(ValueError, match=filename + ".*" + field):
        read_sdk_pin(tmp_path)
