"""Print validated SDK bootstrap coordinates for workflow acquisition."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

if __name__ == "__main__":
    sys.path.insert(0, str(ROOT))
    from common.runtime.sdk_pin import read_sdk_pin

    print(*read_sdk_pin(ROOT))
