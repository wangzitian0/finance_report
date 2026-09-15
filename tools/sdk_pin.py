"""Print validated SDK bootstrap coordinates for workflow acquisition."""

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT_DIR))


def main(argv: Sequence[str] | None = None) -> int:
    from common.runtime.sdk_pin import read_sdk_pin

    argparse.ArgumentParser(description=__doc__).parse_args(argv)
    print(*read_sdk_pin(ROOT_DIR))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
