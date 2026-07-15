import os
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "tools" / "check_ghcr_image_tag.sh"


def _write_fake_docker(bin_dir: Path, inspect_status: int) -> None:
    docker = bin_dir / "docker"
    docker.write_text(
        f"""#!/usr/bin/env bash
set -euo pipefail
printf '%s\\n' "$*" >> "$DOCKER_CALLS"
if [[ "$1 $2 $3" == "buildx imagetools inspect" ]]; then
  exit {inspect_status}
fi
exit 0
""",
        encoding="utf-8",
    )
    docker.chmod(0o755)


def _run_script(
    tmp_path: Path, inspect_status: int
) -> tuple[subprocess.CompletedProcess[str], str, str]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    calls = tmp_path / "docker-calls.txt"
    output = tmp_path / "github-output.txt"
    _write_fake_docker(bin_dir, inspect_status)

    env = {
        **os.environ,
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "DOCKER_CALLS": str(calls),
        "GITHUB_OUTPUT": str(output),
    }
    result = subprocess.run(
        [
            "bash",
            str(SCRIPT),
            "ghcr.io/acme/app-backend:abc123",
        ],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    return result, calls.read_text(encoding="utf-8"), output.read_text(encoding="utf-8")


def test_AC8_13_36_existing_image_skips_fresh_build(tmp_path: Path) -> None:
    """AC8.13.36: Existing SHA-tagged staging image is reused without a rebuild."""
    result, calls, output = _run_script(tmp_path, inspect_status=0)

    assert result.returncode == 0
    assert "buildx imagetools inspect ghcr.io/acme/app-backend:abc123" in calls
    assert "buildx imagetools create" not in calls
    assert "build_required=false" in output


def test_AC8_13_36_missing_image_requests_fresh_build(tmp_path: Path) -> None:
    """AC8.13.36: Missing SHA-tagged image falls back to the workflow build step."""
    result, calls, output = _run_script(tmp_path, inspect_status=1)

    assert result.returncode == 0
    assert "buildx imagetools inspect ghcr.io/acme/app-backend:abc123" in calls
    assert "buildx imagetools create" not in calls
    assert "build_required=true" in output
