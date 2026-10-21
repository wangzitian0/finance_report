"""AC-runtime.runner-pin.1: every workflow job runs on one pinned runner image (#2578).

On 2026-10-21 the floating label ubuntu-latest moved from Ubuntu 24.04 to 26.04.
actions/setup-python has no Python 3.12.12 build for 26.04, so every CI and deploy
job failed at setup. A pinned label makes a runner upgrade one reviewed change.
"""

import re
from pathlib import Path

WORKFLOWS = Path(__file__).resolve().parents[2] / ".github" / "workflows"
RAW_RUNS_ON = re.compile(r"^\s*runs-on:", re.MULTILINE)
PLAIN_RUNS_ON = re.compile(
    r"^\s*runs-on:[ \t]*(?P<label>[A-Za-z0-9.\-]+)[ \t]*$", re.MULTILINE
)
PINNED_LABEL = re.compile(r"^ubuntu-\d{2}\.\d{2}$")


def _labels_by_file() -> dict[str, list[str]]:
    labels: dict[str, list[str]] = {}
    for path in sorted(WORKFLOWS.glob("*.yml")):
        text = path.read_text(encoding="utf-8")
        raw = len(RAW_RUNS_ON.findall(text))
        plain = [m.group("label") for m in PLAIN_RUNS_ON.finditer(text)]
        # A matrix, expression or list form would hide a label from this guard.
        assert raw == len(plain), (
            f"{path.name}: {raw - len(plain)} runs-on entries use a form this guard cannot read"
        )
        labels[path.name] = plain
    return labels


def test_AC_runtime_runner_pin_1_the_guard_reads_workflow_jobs() -> None:
    labels = _labels_by_file()
    assert sum(len(v) for v in labels.values()) > 0
    assert labels["ci.yml"], (
        "ci.yml defines the required check and must declare a runner"
    )


def test_AC_runtime_runner_pin_1_no_workflow_uses_a_floating_runner_label() -> None:
    floating = {
        name: sorted({label for label in found if not PINNED_LABEL.match(label)})
        for name, found in _labels_by_file().items()
    }
    floating = {name: labels for name, labels in floating.items() if labels}
    assert not floating, f"pin these runs-on labels to ubuntu-NN.NN: {floating}"


def test_AC_runtime_runner_pin_1_all_workflows_use_one_runner_label() -> None:
    used = {label for found in _labels_by_file().values() for label in found}
    assert len(used) == 1, f"one runner label expected, found {sorted(used)}"
