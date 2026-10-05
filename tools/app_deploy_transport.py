"""Dispatch one App deploy request and prove the matching infra2 run succeeded."""

from __future__ import annotations

import sys
from collections.abc import Sequence
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from infra2_sdk.dispatch import ReceiverRun as ReceiverRun  # noqa: E402, F401
from infra2_sdk.dispatch import dispatch_and_wait as _sdk_dispatch_and_wait  # noqa: E402, F401
from tools._lib.deploy import app_deploy_transport as _impl  # noqa: E402
from tools._lib.deploy.app_deploy_transport import (  # noqa: E402
    dispatch_and_wait as dispatch_and_wait,
    write_github_output as write_github_output,
)
from tools.app_deploy_request import request_from_mapping as request_from_mapping  # noqa: E402, F401


def main(argv: Sequence[str] | None = None) -> int:
    _this = sys.modules[__name__]
    for attr in ("dispatch_and_wait", "write_github_output", "sys"):
        if hasattr(_this, attr):
            setattr(_impl, attr, getattr(_this, attr))
    return _impl.main(argv)


if __name__ == "__main__":
    raise SystemExit(main())
