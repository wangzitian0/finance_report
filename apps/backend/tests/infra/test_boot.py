from __future__ import annotations

import contextlib
import os
import runpy
import sys
import types
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from infra2_sdk.llm import LlmSettings

from src.boot import Bootloader, BootMode, ServiceStatus
from src.config import Settings

_ORIG_DB, _ORIG_S3 = Bootloader._check_database, Bootloader._check_s3
ZAI_CODING_BASE_URL = "https://api.z.ai/api/coding/paas/v4"
pytestmark = pytest.mark.no_db

_BASE_SETTINGS = {
    "database_url": "postgresql+asyncpg://test:test@localhost/test",
    "secret_key": "unit-test-" + "x" * 26,
    "ai_api_key": None,
    "s3_endpoint": "http://localhost:9000",
    "s3_access_key": "minio",
    "s3_secret_key": "minio123",
    "s3_region": "us-east-1",
    "s3_bucket": "statements",
    "next_public_app_url": "http://localhost:3000",
    "debug": False,
    "environment": "test",
    "base_currency": "USD",
    "ai_provider": "zai",
    "ai_base_url": ZAI_CODING_BASE_URL,
    "large_model": "test-large-model",
    "small_model": "test-model",
    "multimodal_model": "test-vision-model",
    "cors_origin_regex": ".*",
    "cors_origins_str": "http://localhost:3000",
    "otel_exporter_otlp_endpoint": "http://otel:4318",
    "otel_resource_attributes": "deployment.environment=test",
    "otel_service_name": "test",
    "openpanel_api_url": "https://openpanel.zitian.party/api",
    "openpanel_client_id": "op-test-client",
    "prefect_api_url": "http://prefect:4200/api",
    "s3_public_endpoint": "https://s3.zitian.party",
    "s3_public_access_key": None,
    "s3_public_secret_key": None,
    "s3_public_bucket": None,
    "s3_presign_expiry_seconds": 300,
    "api_rate_limit_requests": 300,
    "git_commit_sha": "deadbeef",
}
_SDK_ROLES = {
    "large_model": LlmSettings().large_model,
    "small_model": LlmSettings().small_model,
    "multimodal_model": LlmSettings().multimodal_model,
}
_GUARD_DEV = {
    "secret_key": "dev_secret_key_change_in_prod",
    "database_url": "postgresql+asyncpg://postgres:postgres@127.0.0.1:5432/finance_report",
    "s3_secret_key": "minio_local_secret",
}
_GUARD_STRONG = {
    "secret_key": "unit-test-" + "x" * 26,
    "database_url": "postgresql+asyncpg://finance:placeholder-password@db.internal:5432/finance_report",
    "s3_secret_key": "placeholder-" + "y" * 12,
}
_GUARD_TRIGGERS = {
    "staging-env": ("staging", "http://localhost:3000"),
    "production-env": ("production", "http://localhost:3000"),
    "unknown-env-fails-closed": ("prod-eu", "http://localhost:3000"),
    "public-https-url": ("development", "https://report.example.com"),
}


@pytest.fixture(autouse=True)
def restore_boot_checks():
    Bootloader._check_s3 = staticmethod(_ORIG_S3) if isinstance(_ORIG_S3, types.FunctionType) else _ORIG_S3
    Bootloader._check_database = staticmethod(_ORIG_DB) if isinstance(_ORIG_DB, types.FunctionType) else _ORIG_DB
    yield
    Bootloader._check_s3, Bootloader._check_database = _ORIG_S3, _ORIG_DB


@pytest.fixture
def mock_settings():
    with patch("src.boot.settings") as mock:
        mock.configure_mock(**_BASE_SETTINGS)
        yield mock


@pytest.fixture
def boot_mocks():
    with (
        patch("src.boot.logger") as log,
        patch("src.boot.Bootloader._check_database", new_callable=AsyncMock) as db,
        patch("src.boot.Bootloader._check_s3", new_callable=AsyncMock) as s3,
        patch("src.boot.Bootloader._check_ai_provider", new_callable=AsyncMock) as ai,
    ):
        yield types.SimpleNamespace(logger=log, db=db, s3=s3, ai=ai)


def _configure(mock_settings, environment: str, app_url: str, **overrides: object) -> None:
    mock_settings.configure_mock(
        **{**_SDK_ROLES, **_GUARD_STRONG, "environment": environment, "next_public_app_url": app_url, **overrides}
    )


@contextlib.contextmanager
def _patch_extra_checks(*, cache_status: str = "ok"):
    with contextlib.ExitStack() as stack:
        mocks = {
            t[7:]: stack.enter_context(patch.object(Bootloader, t, new_callable=AsyncMock))
            for t in (
                "_check_cache",
                "_check_workflow_engine",
                "_check_telemetry",
                "_check_analytics",
                "_check_market_data",
            )
        }
        for name, mock in mocks.items():
            st = cache_status if name == "cache" else "ok"
            mock.return_value = ServiceStatus(name, st, "Connection refused" if st == "error" else "OK")
        yield mocks


async def test_bootloader_validate_modes(boot_mocks, mock_settings) -> None:
    await Bootloader.validate(BootMode.DRY_RUN)
    boot_mocks.db.return_value = ServiceStatus("database", "ok", "Connected", duration_ms=10)
    await Bootloader.validate(BootMode.CRITICAL)
    boot_mocks.db.assert_called_once()
    boot_mocks.db.return_value = ServiceStatus("database", "error", "Conn refused")
    with pytest.raises(SystemExit):
        await Bootloader.validate(BootMode.CRITICAL)


@pytest.mark.parametrize("with_settings", [True, False])
async def test_full_check_runs_and_proceeds(request, boot_mocks, with_settings: bool) -> None:
    if with_settings:
        request.getfixturevalue("mock_settings")
    boot_mocks.db.return_value, boot_mocks.s3.return_value = (
        ServiceStatus("database", "ok", "OK"),
        ServiceStatus("minio", "ok", "OK"),
    )
    await Bootloader.validate(BootMode.FULL)
    if with_settings:
        boot_mocks.db.assert_called_once()
        boot_mocks.s3.assert_called_once()


@pytest.mark.parametrize("error_msg", [None, "S3 Down"])
async def test_check_s3(mock_settings, error_msg: str | None) -> None:
    client = MagicMock()
    if error_msg:
        client.head_bucket.side_effect = Exception(error_msg)
    with patch("infra2_sdk.storage.create_s3_client", return_value=client):
        st = await Bootloader._check_s3()
    if error_msg:
        assert st.status == "error" and error_msg in str(st.message)
    else:
        assert (st.status, st.service) == ("ok", "minio")
        assert client.head_bucket.call_count == 2
        client.put_object.assert_not_called()


async def test_check_s3_staging_write_delete_and_prod_readonly(mock_settings) -> None:
    staging_client = MagicMock()
    mock_settings.environment = "staging"
    with patch("infra2_sdk.storage.create_s3_client", return_value=staging_client):
        st_staging = await Bootloader._check_s3()
    assert (st_staging.status, st_staging.service) == ("ok", "minio")
    staging_client.put_object.assert_called_once()
    staging_client.delete_object.assert_called_once()

    for readonly_env in ("production", "prod", "preview", "prod-eu"):
        ro_client = MagicMock()
        mock_settings.environment = readonly_env
        with patch("infra2_sdk.storage.create_s3_client", return_value=ro_client):
            st_ro = await Bootloader._check_s3()
        assert (st_ro.status, st_ro.service) == ("ok", "minio"), readonly_env
        ro_client.put_object.assert_not_called()

    with patch(
        "httpx.AsyncClient.get", AsyncMock(return_value=MagicMock(status_code=200, json=lambda: {"ready": True}))
    ) as get_fn:
        st_analytics = await Bootloader._check_analytics()
    assert (st_analytics.status, st_analytics.service) == ("ok", "analytics")
    assert get_fn.await_args.args[0] == "https://openpanel.zitian.party/api/healthcheck"
    mock_settings.openpanel_client_id = ""
    assert (await Bootloader._check_analytics()).status == "error"


async def test_static_config_basics_exceptions_and_aliases(monkeypatch, mock_settings) -> None:
    from src.config import Settings

    assert Bootloader._check_static_config() is True
    monkeypatch.setenv("ENVIRONMENT", "development")
    with patch("src.boot.settings", Settings(_env_file=None)):
        assert Bootloader._check_static_config() is True
    for env, secret in (("staging", "short-secret"), ("production", "   ")):
        _configure(mock_settings, env, "http://localhost:3000", secret_key=secret)
        assert Bootloader._check_static_config() is False
    with patch("src.boot.settings") as mock:
        type(mock).database_url = property(lambda _s: (_ for _ in ()).throw(ValueError("Missing")))
        assert Bootloader._check_static_config() is False
    with patch.object(Bootloader, "_check_static_config", return_value=False):
        with pytest.raises(SystemExit) as exc_info:
            await Bootloader.validate(BootMode.CRITICAL)
        assert exc_info.value.code == 1 and await Bootloader.validate(BootMode.FULL) is False

    _configure(mock_settings, "production", "http://localhost:3000", s3_access_key="")
    with pytest.raises(SystemExit) as exc_info2:
        await Bootloader.validate(BootMode.CRITICAL)
    assert exc_info2.value.code == 1
    monkeypatch.setenv("ENVIRONMENT", "staging")
    assert Bootloader._check_static_config() is False


@pytest.mark.parametrize("trigger", sorted(_GUARD_TRIGGERS))
@pytest.mark.parametrize("field", sorted(_GUARD_DEV))
def test_AC_runtime_guard_proofs_1_every_default_is_rejected_under_every_protected_trigger(
    mock_settings, field: str, trigger: str
) -> None:
    env, app_url = _GUARD_TRIGGERS[trigger]
    _configure(mock_settings, env, app_url, **{field: _GUARD_DEV[field]})
    assert Bootloader._check_static_config() is False


@pytest.mark.parametrize("environment", ("development", "test", "ci"))
def test_AC_runtime_guard_proofs_2_development_defaults_accepted_in_local_environments(
    mock_settings, environment: str
) -> None:
    _configure(mock_settings, environment, "http://localhost:3000", **_GUARD_DEV)
    assert Bootloader._check_static_config() is True


@pytest.mark.parametrize("trigger", sorted(_GUARD_TRIGGERS))
def test_guard_proofs_strong_values_accepted_under_every_protected_trigger(mock_settings, trigger: str) -> None:
    _configure(mock_settings, *_GUARD_TRIGGERS[trigger])
    assert Bootloader._check_static_config() is True


_PINNED = {
    "large_model": "pinned-large",
    "small_model": "pinned-small",
    "multimodal_model": "pinned-multimodal",
}


@pytest.mark.parametrize("environment", ("staging", "ci", "preview", "prod-eu", "pr-123", "testing"))
@pytest.mark.parametrize("role", sorted(_PINNED))
def test_AC_llm_2953_a_pinned_model_role_stops_every_deployed_environment_but_production(
    mock_settings, environment: str, role: str
) -> None:
    _configure(mock_settings, environment, "http://localhost:3000", **{role: _PINNED[role]})
    with patch("src.boot.logger") as log:
        assert Bootloader._check_static_config() is False
    pinned_env = {
        "large_model": "LLM_LARGE_MODEL",
        "small_model": "LLM_SMALL_MODEL",
        "multimodal_model": "LLM_MULTIMODAL_MODEL",
    }[role]
    assert pinned_env in str(log.error.call_args)


@pytest.mark.parametrize("environment", ("production", "development", "test", " Production ", "DEVELOPMENT"))
def test_AC_llm_2953_production_and_local_runs_may_pin_every_model_role(mock_settings, environment: str) -> None:
    _configure(mock_settings, environment, "http://localhost:3000", **_PINNED)
    assert Bootloader._check_static_config() is True


@pytest.mark.parametrize("environment", ("staging", "ci", "production", "development"))
def test_AC_llm_2953_the_sdk_default_roles_pass_in_every_environment(mock_settings, environment: str) -> None:
    _configure(mock_settings, environment, "http://localhost:3000")
    assert Bootloader._check_static_config() is True


@pytest.mark.parametrize("environment", ("production", "development"))
def test_AC_llm_2953_the_start_builds_the_llm_settings_of_the_sdk(mock_settings, environment: str) -> None:
    """A role that the SDK refuses stops the start in every environment, not at the first model call."""
    _configure(mock_settings, environment, "http://localhost:3000")
    mock_settings.to_llm_settings.side_effect = ValueError("large_model must be non-empty")
    assert Bootloader._check_static_config() is False


@pytest.mark.parametrize("blank", ("", "   "))
def test_AC_llm_2953_a_blank_role_variable_is_refused_by_the_real_settings(monkeypatch, blank: str) -> None:
    monkeypatch.setenv("LLM_LARGE_MODEL", blank)
    real = Settings(_env_file=None)
    assert real.large_model == blank
    with patch("src.boot.settings", real):
        assert Bootloader._check_llm_roles("production") is False


def test_AC_llm_2953_a_blank_base_url_variable_is_refused_by_the_real_settings(monkeypatch) -> None:
    monkeypatch.setenv("LLM_BASE_URL", "")
    real = Settings(_env_file=None)
    assert real.ai_base_url == ""
    with patch("src.boot.settings", real):
        assert Bootloader._check_llm_roles("production") is False


@pytest.mark.parametrize(
    ("environment", "app_url", "expected"),
    [
        ("staging", "http://localhost:3000", True),
        ("production", "http://localhost:3000", True),
        ("  Production ", "http://localhost:3000", True),
        ("prod-eu", "http://localhost:3000", True),
        ("development", "https://report.example.com", True),
        ("development", "http://localhost:3000", False),
        ("test", "", False),
        ("ci", "https://localhost:8443", False),
        ("development", "https://127.0.0.1:8443", False),
    ],
)
def test_AC_runtime_guard_proofs_3_protected_runtime_classification(
    mock_settings, environment: str, app_url: str, expected: bool
) -> None:
    mock_settings.next_public_app_url = app_url
    assert Bootloader._is_protected_runtime(environment) is expected


@pytest.mark.parametrize(
    ("debug", "env", "expected_fragments"),
    [
        (False, {"DEBUG": "false"}, None),
        (True, {"DEBUG": "true"}, ("Config loaded (DEBUG mode)", "database_url: set", "Fields using defaults:")),
        (
            True,
            {
                "DEBUG": "true",
                "ENVIRONMENT": "development",
                "BASE_CURRENCY": "USD",
                "LLM_LARGE_MODEL": "test-large-model",
                "LLM_SMALL_MODEL": "gemini",
                "LLM_PROVIDER": "zai",
                "LLM_BASE_URL": ZAI_CODING_BASE_URL,
                "LLM_MULTIMODAL_MODEL": "test-vision-model",
                "S3_ENDPOINT": "http://localhost:9000",
                "S3_BUCKET": "statements",
                "CORS_ORIGIN_REGEX": ".*",
                "OTEL_EXPORTER_OTLP_ENDPOINT": "http://otel:4317",
                "OTEL_SERVICE_NAME": "finance-report",
            },
            ("(none)",),
        ),
    ],
)
def test_print_config_modes(
    mock_settings, capsys, debug: bool, env: dict[str, str], expected_fragments: tuple[str, ...] | None
) -> None:
    mock_settings.configure_mock(
        debug=debug,
        environment="development",
        otel_exporter_otlp_endpoint="http://otel:4317" if debug else None,
        ai_api_key="k" if expected_fragments == ("(none)",) else None,
    )
    with patch.dict(os.environ, env, clear=False):
        Bootloader.print_config()
    out = capsys.readouterr().out
    assert out == "" if expected_fragments is None else all(f in out for f in expected_fragments)


@pytest.mark.parametrize(
    ("mode", "outcome", "expected_code"),
    [("full", True, 0), ("critical", False, 1), ("dry-run", KeyboardInterrupt(), 130)],
)
def test_main_exit_codes(mode: str, outcome: object, expected_code: int) -> None:
    def _run(coro):
        coro.close()
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome

    with (
        patch.object(sys, "argv", ["boot.py", "--mode", mode]),
        patch("asyncio.run", side_effect=_run),
        patch("sys.exit", side_effect=SystemExit(expected_code)),
        pytest.raises(SystemExit) as exc_info,
    ):
        runpy.run_module("src.boot", run_name="__main__")
    assert exc_info.value.code == expected_code


async def test_check_database_and_ai_provider(mock_settings) -> None:
    mock_conn = AsyncMock(execute=AsyncMock())
    mock_engine = MagicMock(dispose=AsyncMock())
    mock_engine.connect.return_value.__aenter__.return_value = mock_conn
    with patch("src.runtime.extension.adapters.create_async_engine", return_value=mock_engine):
        ok = await Bootloader._check_database()
    assert (ok.status, ok.service) == ("ok", "database") and mock_conn.execute.call_count == 1
    with patch("src.runtime.extension.adapters.create_async_engine", side_effect=Exception("Connection refused")):
        err = await Bootloader._check_database()
    assert err.status == "error" and "Connection refused" in err.message

    mock_settings.ai_api_key = None
    assert (await Bootloader._check_ai_provider()).status == "error"
    mock_settings.ai_api_key = "test-key"
    with patch("httpx.AsyncClient.get", AsyncMock(return_value=MagicMock(status_code=200))):
        ai_ok = await Bootloader._check_ai_provider()
    assert (ai_ok.status, ai_ok.service) == ("ok", "ai_provider") and "provider=zai models=200" in ai_ok.message
    with patch("httpx.AsyncClient.get", AsyncMock(return_value=MagicMock(status_code=401))):
        ai_err = await Bootloader._check_ai_provider()
    assert (ai_err.status, ai_err.service) == ("error", "ai_provider") and "Authentication failed" in ai_err.message


@pytest.mark.parametrize(
    ("db_status", "expected_result", "log_method"), [("warning", True, "warning"), ("error", False, "error")]
)
async def test_full_mode_handles_db_status(
    mock_settings, boot_mocks, db_status: str, expected_result: bool, log_method: str
) -> None:
    boot_mocks.db.return_value, boot_mocks.s3.return_value, boot_mocks.ai.return_value = (
        ServiceStatus("database", db_status, "DB"),
        ServiceStatus("minio", "ok", "OK"),
        ServiceStatus("ai_provider", "ok", "OK"),
    )
    assert await Bootloader.validate(BootMode.FULL) is expected_result
    getattr(boot_mocks.logger, log_method).assert_called()


@pytest.mark.parametrize(
    "attr_name",
    ["secret_key", "database_url", "s3_secret_key", "s3_access_key", "s3_endpoint", "s3_bucket", "next_public_app_url"],
)
def test_static_config_fails_closed_when_required_injected_setting_missing_in_protected_runtime(
    mock_settings, attr_name: str
) -> None:
    _configure(
        mock_settings,
        "production",
        "https://report.zitian.party",
        s3_access_key="minio-prod",
        s3_endpoint="http://minio:9000",
        s3_bucket="statements",
    )
    setattr(mock_settings, attr_name, "   ")
    assert Bootloader._check_static_config() is False


def test_static_config_injected_scope_and_manifest_tiers(mock_settings, boot_mocks, monkeypatch) -> None:
    from infra2_sdk.config import EnvironmentTier

    import src.boot as boot_module
    from src.runtime import DEPENDENCY_MANIFEST

    assert not hasattr(Bootloader, "_check_vault_secrets")
    assert all(
        not hasattr(boot_module, s)
        for s in (
            "VAULT_SECRETS_FILE_PATH",
            "VAULT_SECRETS_STALENESS_THRESHOLD_SECONDS",
            "PROTECTED_REQUIRED_INJECTED_FIELDS",
        )
    )
    for tier in EnvironmentTier:
        probed, unprobed = Bootloader._required_checks(tier)
        assert set(probed) | set(unprobed) == DEPENDENCY_MANIFEST.required_for(tier) and not (
            set(probed) & set(unprobed)
        )
    assert set(Bootloader._required_checks(EnvironmentTier.GITHUB_CI)[0]) == {"database", "object_storage"} and set(
        Bootloader._required_checks(EnvironmentTier.PRODUCTION)[0]
    ) == DEPENDENCY_MANIFEST.required_for(EnvironmentTier.PRODUCTION)

    for k in ("PREFECT_API_URL", "S3_PUBLIC_ENDPOINT"):
        monkeypatch.delenv(k, raising=False)
    _configure(
        mock_settings, "pr-123", "https://report-pr-123.zitian.party", prefect_api_url=None, s3_public_endpoint=None
    )
    assert Bootloader._is_protected_runtime("pr-123") and Bootloader._check_static_config()
    boot_mocks.logger.error.assert_not_called()

    _configure(
        mock_settings,
        "staging",
        "https://report-staging.zitian.party",
        prefect_api_url=None,
        s3_public_endpoint="https://s3.zitian.party",
    )
    assert (
        Bootloader._check_static_config() is False
        and "PREFECT_API_URL" in boot_mocks.logger.error.call_args.kwargs["error"]
    )

    boot_mocks.logger.error.reset_mock()
    _configure(
        mock_settings,
        "production",
        "https://report.zitian.party",
        prefect_api_url="http://prefect:4200/api",
        s3_public_endpoint="https://s3.zitian.party",
        s3_public_bucket=None,
    )
    monkeypatch.setenv("S3_PUBLIC_BUCKET", "")
    assert Bootloader._check_static_config() is True
    mock_settings.prefect_api_url = None
    assert Bootloader._check_static_config() is False
    err = boot_mocks.logger.error.call_args.kwargs["error"]
    assert "PREFECT_API_URL" in err and "S3_PUBLIC_BUCKET" not in err


@pytest.mark.parametrize(
    ("tier_name", "cache_status", "db_status", "expected"),
    [
        ("GITHUB_CI", "ok", "ok", True),
        ("STAGING", "ok", "ok", True),
        ("STAGING", "ok", "error", False),
        ("PRODUCTION", "ok", "ok", True),
        ("PRODUCTION", "error", "ok", False),
    ],
)
async def test_manifest_driven_full_validate(
    mock_settings, boot_mocks, tier_name: str, cache_status: str, db_status: str, expected: bool
) -> None:
    from infra2_sdk.config import EnvironmentTier

    boot_mocks.db.return_value, boot_mocks.s3.return_value, boot_mocks.ai.return_value = (
        ServiceStatus("database", db_status, "DB"),
        ServiceStatus("minio", "ok", "OK"),
        ServiceStatus("ai_provider", "ok", "OK"),
    )
    with _patch_extra_checks(cache_status=cache_status) as extra:
        assert await Bootloader.validate(BootMode.FULL, tier=getattr(EnvironmentTier, tier_name)) is expected
    if tier_name == "GITHUB_CI":
        boot_mocks.ai.assert_not_called()
    elif tier_name == "STAGING" and expected:
        boot_mocks.ai.assert_called_once()
        assert extra["market_data"].call_count == 1
    elif tier_name == "PRODUCTION" and expected:
        assert all(m.call_count == 1 for m in extra.values())
