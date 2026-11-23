"""deploy 制品校验：身份边界、可信网段与 onboarding 契约保持一致。"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "scripts" / "validate_deploy_artifacts.py"
_spec = importlib.util.spec_from_file_location("validate_deploy_artifacts", SCRIPT_PATH)
assert _spec is not None and _spec.loader is not None
validate_deploy_artifacts = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(validate_deploy_artifacts)


def _write_release_values(tmp_path: Path, *, cidrs: str) -> Path:
    path = tmp_path / "values.yaml"
    path.write_text(
        "\n".join(
            [
                "config:",
                "  APP_ENV: release",
                "  AUTH_REQUIRED: 'true'",
                f"  TRUSTED_PROXY_CIDRS: '{cidrs}'",
                "  CELERY_NAMESPACE: hr-certflow-release",
                "  CELERY_QUEUE: hr-certflow-release",
                "  CELERY_ROUTING_KEY: hr-certflow-release",
                "  CELERY_REDIS_HASH_TAG: hr-certflow-release",
                "  CELERY_REDIS_PREFIX: 'hr-certflow-release:'",
                "ingress:",
                "  pathPrefix: /hr-certflow",
                "images:",
                "  api:",
                "    repository: api",
                "    tag: v1",
                "  web:",
                "    repository: web",
                "    tag: v1",
            ]
        ),
        encoding="utf-8",
    )
    return path


@pytest.mark.parametrize("cidrs", ["0.0.0.0/0", "::/0", "10.42.0.0/16,0.0.0.0/0"])
def test_release_values_reject_zero_prefix_trusted_cidr(tmp_path: Path, cidrs: str) -> None:
    path = _write_release_values(tmp_path, cidrs=cidrs)

    with pytest.raises(RuntimeError, match="TRUSTED_PROXY_CIDRS"):
        validate_deploy_artifacts.validate_values("release", path)


def test_release_values_accept_scoped_trusted_cidrs(tmp_path: Path) -> None:
    path = _write_release_values(tmp_path, cidrs="10.42.0.0/16, 172.16.0.0/12")

    validate_deploy_artifacts.validate_values("release", path)


def test_values_reject_credential_bearing_session_store_url(tmp_path: Path) -> None:
    path = _write_release_values(tmp_path, cidrs="10.42.0.0/16")
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    payload["config"]["SESSION_STORE_URL"] = "redis://example.invalid/0"
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")

    with pytest.raises(RuntimeError, match="SESSION_STORE_URL"):
        validate_deploy_artifacts.validate_values("release", path)


def test_chart_defaults_reject_credential_bearing_session_store_url(
    tmp_path: Path,
) -> None:
    source = REPO_ROOT / "deploy" / "helm" / "hr-certflow" / "values.yaml"
    payload = yaml.safe_load(source.read_text(encoding="utf-8"))
    payload["config"]["SESSION_STORE_URL"] = "redis://example.invalid/0"
    path = tmp_path / "chart-values.yaml"
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")

    with pytest.raises(RuntimeError, match="SESSION_STORE_URL"):
        validate_deploy_artifacts.validate_chart_defaults(path)


def _write_onboarding_request(tmp_path: Path) -> Path:
    source = REPO_ROOT / "deploy" / "shared-k3s" / "onboarding-request.yaml"
    payload = yaml.safe_load(source.read_text(encoding="utf-8"))
    path = tmp_path / "onboarding-request.yaml"
    path.write_text(yaml.safe_dump(payload, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return path


def test_checked_in_onboarding_contract_matches_step3_identity_and_probe() -> None:
    path = REPO_ROOT / "deploy" / "shared-k3s" / "onboarding-request.yaml"

    validate_deploy_artifacts.validate_onboarding_request(path, repo_root=REPO_ROOT)


@pytest.mark.parametrize("env_name", ["dev", "release"])
def test_onboarding_contract_rejects_authenticated_health_as_smoke_path(tmp_path: Path, env_name: str) -> None:
    path = _write_onboarding_request(tmp_path)
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    payload["smoke"][env_name]["apiProbe"]["path"] = "/api/v1/health"
    path.write_text(yaml.safe_dump(payload, allow_unicode=True, sort_keys=False), encoding="utf-8")

    with pytest.raises(RuntimeError, match="cluster-internal"):
        validate_deploy_artifacts.validate_onboarding_request(path, repo_root=REPO_ROOT)


def test_onboarding_contract_requires_redis_backed_dev_session(tmp_path: Path) -> None:
    path = _write_onboarding_request(tmp_path)
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    payload["dependencies"]["identity"]["dev"] = [
        item for item in payload["dependencies"]["identity"]["dev"] if "Redis-backed" not in item
    ] + ["Redis-backed sessions", "SESSION_STORE_URL from runtime secret"]
    path.write_text(yaml.safe_dump(payload, allow_unicode=True, sort_keys=False), encoding="utf-8")

    with pytest.raises(RuntimeError, match="Redis-backed"):
        validate_deploy_artifacts.validate_onboarding_request(path, repo_root=REPO_ROOT)


def test_onboarding_docs_describe_redis_backed_dev_session() -> None:
    path = REPO_ROOT / "docs" / "shared-k3s-onboarding.md"
    text = " ".join(path.read_text(encoding="utf-8").split())

    assert "Session store: Redis-backed through `SESSION_STORE_URL`" in text
    assert "dev does not use the in-memory fallback" in text
    assert "Session store: in-memory" not in text
