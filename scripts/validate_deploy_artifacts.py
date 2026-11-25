from __future__ import annotations

import argparse
import ipaddress
import json
from pathlib import Path
from typing import Any

import yaml


STEP3_CONFIG_KEYS = {
    "APP_ID",
    "PUBLIC_BASE_URL",
    "OIDC_ISSUER_URL",
    "OIDC_ISSUER_KEY",
    "OIDC_CLIENT_ID",
    "AUTHZ_BASE_URL",
    "SESSION_IDLE_SECONDS",
    "SESSION_ABSOLUTE_SECONDS",
    "SESSION_CHECK_INTERVAL_SECONDS",
    "POD_NAMESPACE",
}
STEP3_SECRET_KEYS = {"AUTHZ_SERVICE_TOKEN", "OIDC_CLIENT_SECRET", "SESSION_STORE_URL"}
AUTHORIZATION_MANIFEST = "authz/authorization-manifest.json"
CLUSTER_PROBE_PATH = "/_internal/healthz"
DEV_OIDC_ISSUER_URL = "http://10.34.200.180/hydra-dev"
RELEASE_OIDC_ISSUER_URL = "http://10.34.200.180/hydra"

EXPECTED = {
    "dev": {
        "app_env": "dev",
        "auth_required": "false",
        "namespace": "hr-certflow-dev",
        "path_prefix": "/hr-certflow-dev",
        "oidc_issuer_url": DEV_OIDC_ISSUER_URL,
    },
    "release": {
        "app_env": "release",
        "auth_required": "true",
        "namespace": "hr-certflow-release",
        "path_prefix": "/hr-certflow",
        "oidc_issuer_url": RELEASE_OIDC_ISSUER_URL,
        "oidc_client_id": "hr-certflow-release",
        "public_base_url": "http://10.34.200.180/hr-certflow",
        "authz_base_url": "http://authorization-center-release.authorization-center-release.svc.cluster.local:8080",
    },
}


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def load_yaml(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as file:
        payload = yaml.safe_load(file)
    require(isinstance(payload, dict), f"{path} must contain a YAML mapping")
    return payload


def validate_values(env_name: str, path: Path) -> None:
    expected = EXPECTED[env_name]
    values = load_yaml(path)
    config = values.get("config") or {}
    images = values.get("images") or {}
    ingress = values.get("ingress") or {}

    require(
        config.get("APP_ENV") == expected["app_env"],
        f"{path}: APP_ENV must be {expected['app_env']}",
    )
    require(
        config.get("CELERY_NAMESPACE") == expected["namespace"],
        f"{path}: CELERY_NAMESPACE must be {expected['namespace']}",
    )
    require(
        config.get("CELERY_QUEUE") == expected["namespace"],
        f"{path}: CELERY_QUEUE must be environment scoped",
    )
    require(
        config.get("CELERY_ROUTING_KEY") == expected["namespace"],
        f"{path}: CELERY_ROUTING_KEY must be environment scoped",
    )
    require(
        config.get("CELERY_REDIS_HASH_TAG") == expected["namespace"],
        f"{path}: CELERY_REDIS_HASH_TAG must be environment scoped",
    )
    require(
        config.get("CELERY_REDIS_PREFIX") == f"{expected['namespace']}:",
        f"{path}: CELERY_REDIS_PREFIX must be standalone Redis prefix {expected['namespace']}:",
    )
    require(
        "{" not in str(config.get("CELERY_REDIS_PREFIX")),
        f"{path}: Redis Cluster hash-tag prefix is not allowed",
    )
    require(
        ingress.get("pathPrefix") == expected["path_prefix"],
        f"{path}: unexpected ingress path prefix",
    )
    require(
        "SESSION_STORE_URL" not in config,
        f"{path}: SESSION_STORE_URL is credential-bearing and must use a Secret",
    )
    # 与 API 启动校验一致：release 必须开启认证并给出合法可信网段，否则新镜像会拒绝启动。
    require(
        str(config.get("AUTH_REQUIRED")).lower() == expected["auth_required"],
        f"{path}: AUTH_REQUIRED must be {expected['auth_required']}",
    )
    if expected["auth_required"] == "true":
        cidrs = [
            item.strip()
            for item in str(config.get("TRUSTED_PROXY_CIDRS") or "").split(",")
            if item.strip()
        ]
        require(
            cidrs, f"{path}: TRUSTED_PROXY_CIDRS is required when AUTH_REQUIRED is true"
        )
        for cidr in cidrs:
            try:
                network = ipaddress.ip_network(cidr, strict=False)
            except ValueError as exc:
                raise RuntimeError(
                    f"{path}: TRUSTED_PROXY_CIDRS has invalid entry {cidr!r}"
                ) from exc
            require(
                network.prefixlen > 0,
                f"{path}: TRUSTED_PROXY_CIDRS must not contain zero-prefix network {cidr!r}",
            )

    # dev 与 release 都启用了 jxccs-access（Item #32 H1）：step-3 配置键两环境必填。
    missing_keys = sorted(STEP3_CONFIG_KEYS.difference(config))
    require(
        not missing_keys, f"{path}: missing jxccs-access step-3 keys {missing_keys}"
    )
    require(
        config.get("OIDC_ISSUER_KEY") == "hydra-jiaxing-company",
        f"{path}: OIDC_ISSUER_KEY must be hydra-jiaxing-company",
    )
    require(
        config.get("OIDC_ISSUER_URL") == expected["oidc_issuer_url"],
        f"{path}: OIDC_ISSUER_URL must be {expected['oidc_issuer_url']}",
    )
    for key, expected_key in (
        ("OIDC_CLIENT_ID", "oidc_client_id"),
        ("PUBLIC_BASE_URL", "public_base_url"),
        ("AUTHZ_BASE_URL", "authz_base_url"),
    ):
        if expected_key in expected:
            require(
                config.get(key) == expected[expected_key],
                f"{path}: {key} must be {expected[expected_key]}",
            )
    for image_name in ("api", "web"):
        image = images.get(image_name) or {}
        require(
            image.get("repository"),
            f"{path}: images.{image_name}.repository is required",
        )
        require(image.get("tag"), f"{path}: images.{image_name}.tag is required")


def validate_onboarding_request(path: Path, *, repo_root: Path | None = None) -> None:
    payload = load_yaml(path)
    runtime = payload.get("runtime") or {}
    backend = runtime.get("backend") or {}
    require(
        backend.get("healthPath") == CLUSTER_PROBE_PATH,
        f"{path}: runtime.backend.healthPath must be {CLUSTER_PROBE_PATH}",
    )

    smoke = payload.get("smoke") or {}
    for env_name in ("dev", "release"):
        probe = smoke.get(env_name, {}).get("apiProbe") or {}
        require(
            probe == {"path": CLUSTER_PROBE_PATH, "mode": "cluster-internal"},
            f"{path}: smoke.{env_name}.apiProbe must use the cluster-internal {CLUSTER_PROBE_PATH}",
        )

    dependencies = payload.get("dependencies") or {}
    identity = dependencies.get("identity") or {}
    require(
        identity.get("manifest") == AUTHORIZATION_MANIFEST,
        f"{path}: dependencies.identity.manifest must be {AUTHORIZATION_MANIFEST}",
    )
    dev_identity = identity.get("dev") or []
    dev_identity_text = "\n".join(str(item) for item in dev_identity)
    require(
        "authorization-center-dev" in dev_identity_text,
        f"{path}: dev identity dependencies must include authorization-center-dev",
    )
    require(
        "hydra-dev" in dev_identity_text,
        f"{path}: dev identity dependencies must include the Hydra relay issuer",
    )
    require(
        any(
            "Redis-backed" in str(item) and "SESSION_STORE_URL" in str(item)
            for item in dev_identity
        ),
        f"{path}: dev identity dependencies must document the Redis-backed session store",
    )

    config_keys = set(payload.get("configMapKeys") or [])
    require(
        STEP3_CONFIG_KEYS.issubset(config_keys),
        f"{path}: configMapKeys do not declare all jxccs-access step-3 keys",
    )
    secret_keys = set(payload.get("runtimeSecretKeys") or [])
    require(
        STEP3_SECRET_KEYS.issubset(secret_keys),
        f"{path}: runtimeSecretKeys do not declare all jxccs-access step-3 secrets",
    )
    require(
        "SESSION_STORE_URL" not in config_keys,
        f"{path}: SESSION_STORE_URL is credential-bearing and must not be in configMapKeys",
    )

    root = repo_root or Path(__file__).resolve().parents[1]
    manifest_path = root / AUTHORIZATION_MANIFEST
    require(
        manifest_path.exists(), f"{manifest_path}: authorization manifest is missing"
    )
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"{manifest_path}: invalid JSON: {exc}") from exc
    permissions = {
        item.get("id")
        for item in manifest.get("permissions", [])
        if isinstance(item, dict) and isinstance(item.get("id"), str)
    }
    require(
        {"certificate.view", "certificate.manage"}.issubset(permissions),
        f"{manifest_path}: certificate.view and certificate.manage must be declared",
    )


def validate_chart_defaults(path: Path) -> None:
    payload = load_yaml(path)
    config = payload.get("config") or {}
    require(
        "SESSION_STORE_URL" not in config,
        f"{path}: SESSION_STORE_URL is credential-bearing and must use a Secret",
    )


def validate_helm_templates(chart_dir: Path) -> None:
    helper_path = chart_dir / "templates" / "_helpers.tpl"
    require(helper_path.exists(), f"{helper_path}: missing Helm helper template")
    helper_text = helper_path.read_text(encoding="utf-8")
    require(
        'define "hr-certflow.intOrPercent"' in helper_text,
        f"{helper_path}: missing intOrPercent helper",
    )

    for template_name in ("api.yaml", "web.yaml", "worker.yaml", "beat.yaml"):
        template_path = chart_dir / "templates" / template_name
        text = template_path.read_text(encoding="utf-8")
        require(
            'maxSurge: {{ include "hr-certflow.intOrPercent"' in text,
            f"{template_path}: maxSurge must render through intOrPercent",
        )
        require(
            'maxUnavailable: {{ include "hr-certflow.intOrPercent"' in text,
            f"{template_path}: maxUnavailable must render through intOrPercent",
        )
        require(
            "maxSurge: {{ .Values." not in text
            and "maxUnavailable: {{ .Values." not in text,
            f"{template_path}: strategy values must not be rendered directly",
        )


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate hr-certflow deploy values")
    parser.add_argument(
        "--dev-values", type=Path, default=Path("deploy/gitops/dev/values.yaml")
    )
    parser.add_argument(
        "--release-values", type=Path, default=Path("deploy/gitops/release/values.yaml")
    )
    parser.add_argument(
        "--onboarding-request",
        type=Path,
        default=Path("deploy/shared-k3s/onboarding-request.yaml"),
    )
    parser.add_argument(
        "--chart-values",
        type=Path,
        default=Path("deploy/helm/hr-certflow/values.yaml"),
    )
    parser.add_argument(
        "--chart-dir", type=Path, default=Path("deploy/helm/hr-certflow")
    )
    args = parser.parse_args()

    validate_values("dev", args.dev_values)
    validate_values("release", args.release_values)
    validate_onboarding_request(args.onboarding_request)
    validate_chart_defaults(args.chart_values)
    validate_helm_templates(args.chart_dir)
    print("deploy artifacts ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
