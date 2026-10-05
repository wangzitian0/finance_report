#!/usr/bin/env python3
"""Thin shim for env reference generation."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from tools._lib.env_reference import (  # noqa: E402
    ALIAS_CHAIN_EMPTY_NOTE as ALIAS_CHAIN_EMPTY_NOTE,
    BEGIN_MARKER as BEGIN_MARKER,
    END_MARKER as END_MARKER,
    ENV_EXAMPLE_PATH as ENV_EXAMPLE_PATH,
    ENV_REFERENCE_DOC_PATH as ENV_REFERENCE_DOC_PATH,
    REQUIRED_ENV_MANIFEST_PATH as REQUIRED_ENV_MANIFEST_PATH,
    _environment_contract as _environment_contract,
    _render_value as _render_value,
    _settings_model as _settings_model,
    _settings_module as _settings_module,
    collect_backend_fields as collect_backend_fields,
    env_example_documented_keys as env_example_documented_keys,
    main as main,
    manifest_gate_errors as manifest_gate_errors,
    render_backend_block as render_backend_block,
    render_env_example as render_env_example,
    render_reference_doc as render_reference_doc,
    render_required_env_manifest as render_required_env_manifest,
)

if __name__ == "__main__":
    raise SystemExit(main())
