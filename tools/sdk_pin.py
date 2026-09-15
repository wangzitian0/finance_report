"""Print validated SDK bootstrap coordinates for workflow acquisition."""

import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT_DIR))


def main() -> None:
    from common.runtime.sdk_pin import read_sdk_pin

    print(*read_sdk_pin(ROOT_DIR))


if __name__ == "__main__":
    main()
