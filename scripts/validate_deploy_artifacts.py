from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

import yaml


EXPECTED = {
    "dev": {
        "app_env": "dev",
        "namespace": "hr-certflow-dev",
        "path_prefix": "/hr-certflow",
    },
    "release": {
        "app_env": "release",
        "namespace": "hr-certflow-release",
        "path_prefix": "/hr-certflow-release",
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

    require(config.get("APP_ENV") == expected["app_env"], f"{path}: APP_ENV must be {expected['app_env']}")
    require(
        config.get("CELERY_NAMESPACE") == expected["namespace"],
        f"{path}: CELERY_NAMESPACE must be {expected['namespace']}",
    )
    require(config.get("CELERY_QUEUE") == expected["namespace"], f"{path}: CELERY_QUEUE must be environment scoped")
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
    require("{" not in str(config.get("CELERY_REDIS_PREFIX")), f"{path}: Redis Cluster hash-tag prefix is not allowed")
    require(ingress.get("pathPrefix") == expected["path_prefix"], f"{path}: unexpected ingress path prefix")

    for image_name in ("api", "web"):
        image = images.get(image_name) or {}
        require(image.get("repository"), f"{path}: images.{image_name}.repository is required")
        require(image.get("tag"), f"{path}: images.{image_name}.tag is required")


def validate_helm_templates(chart_dir: Path) -> None:
    helper_path = chart_dir / "templates" / "_helpers.tpl"
    require(helper_path.exists(), f"{helper_path}: missing Helm helper template")
    helper_text = helper_path.read_text(encoding="utf-8")
    require("define \"hr-certflow.intOrPercent\"" in helper_text, f"{helper_path}: missing intOrPercent helper")

    for template_name in ("api.yaml", "web.yaml", "worker.yaml", "beat.yaml"):
        template_path = chart_dir / "templates" / template_name
        text = template_path.read_text(encoding="utf-8")
        require(
            "maxSurge: {{ include \"hr-certflow.intOrPercent\"" in text,
            f"{template_path}: maxSurge must render through intOrPercent",
        )
        require(
            "maxUnavailable: {{ include \"hr-certflow.intOrPercent\"" in text,
            f"{template_path}: maxUnavailable must render through intOrPercent",
        )
        require(
            "maxSurge: {{ .Values." not in text and "maxUnavailable: {{ .Values." not in text,
            f"{template_path}: strategy values must not be rendered directly",
        )


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate hr-certflow deploy values")
    parser.add_argument("--dev-values", type=Path, default=Path("deploy/gitops/dev/values.yaml"))
    parser.add_argument("--release-values", type=Path, default=Path("deploy/gitops/release/values.yaml"))
    parser.add_argument("--chart-dir", type=Path, default=Path("deploy/helm/hr-certflow"))
    args = parser.parse_args()

    validate_values("dev", args.dev_values)
    validate_values("release", args.release_values)
    validate_helm_templates(args.chart_dir)
    print("deploy artifacts ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
