"""Dispatch one App deploy request and prove the matching infra2 run succeeded."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from infra2_sdk.deploy import ReceiverRun as ReceiverRun  # noqa: E402, F401
from infra2_sdk.deploy import dispatch_and_wait as _sdk_dispatch_and_wait  # noqa: E402, F401
from common.runtime.deploy.app_deploy_request import (  # noqa: E402, F401
    request_from_mapping as request_from_mapping,
)
from common.runtime.deploy.app_deploy_transport import (  # noqa: E402, F401
    dispatch_and_wait as dispatch_and_wait,
    main,
    write_github_output as write_github_output,
)

if __name__ == "__main__":
    raise SystemExit(main())
