#!/usr/bin/env python3
"""Deprecated PR preview cleanup entry point.

PR preview lifecycle cleanup is now owned by tools/pr_preview_lifecycle.py.
Generic VPS host hygiene is now owned by the Dokploy server schedule managed by
tools/vps_host_hygiene.py.
"""

from __future__ import annotations

import argparse
import sys


DEPRECATION_MESSAGE = "\n".join(
    [
        "tools/cleanup_pr_preview_resources.py is deprecated.",
        "Use tools/pr_preview_lifecycle.py --action reconcile for closed PR preview leftovers.",
        "Use tools/vps_host_hygiene.py --ensure-dokploy-schedule for host hygiene.",
        "This command no longer performs SSH cleanup or host-wide Docker/journal pruning.",
    ]
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_known_args(argv)
    print(DEPRECATION_MESSAGE, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
