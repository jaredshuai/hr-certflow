"""deploy 制品校验脚本：release 的 TRUSTED_PROXY_CIDRS 不允许零前缀网段。"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "validate_deploy_artifacts.py"
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
