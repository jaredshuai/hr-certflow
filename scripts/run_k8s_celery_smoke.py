from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from typing import Any


DEFAULT_COMMANDS = ("selftest", "send", "assert-keys")


def kubectl(args: list[str], *, input_text: str | None = None) -> str:
    completed = subprocess.run(
        ["kubectl", *args],
        input=input_text,
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(f"kubectl {' '.join(args)} failed\nstdout:\n{completed.stdout}\nstderr:\n{completed.stderr}")
    return completed.stdout


def api_image(namespace: str, deployment: str) -> str:
    payload = kubectl(["-n", namespace, "get", "deployment", deployment, "-o", "json"])
    data = json.loads(payload)
    containers = data["spec"]["template"]["spec"].get("containers") or []
    for container in containers:
        if container.get("name") == "api":
            return str(container["image"])
    if containers:
        return str(containers[0]["image"])
    raise RuntimeError(f"{deployment} has no containers")


def smoke_job_manifest(
    *,
    namespace: str,
    name: str,
    image: str,
    command: str,
    service_account: str,
    config_map: str,
    secret: str,
    image_pull_secret: str,
    active_deadline_seconds: int,
) -> dict[str, Any]:
    return {
        "apiVersion": "batch/v1",
        "kind": "Job",
        "metadata": {
            "name": name,
            "namespace": namespace,
            "labels": {
                "app.kubernetes.io/name": "hr-certflow",
                "app.kubernetes.io/component": "celery-redis-smoke",
            },
        },
        "spec": {
            "backoffLimit": 0,
            "ttlSecondsAfterFinished": 300,
            "activeDeadlineSeconds": active_deadline_seconds,
            "template": {
                "metadata": {
                    "labels": {
                        "app.kubernetes.io/name": "hr-certflow",
                        "app.kubernetes.io/component": "celery-redis-smoke",
                    }
                },
                "spec": {
                    "restartPolicy": "Never",
                    "serviceAccountName": service_account,
                    "imagePullSecrets": [{"name": image_pull_secret}],
                    "containers": [
                        {
                            "name": "smoke",
                            "image": image,
                            "imagePullPolicy": "IfNotPresent",
                            "command": ["python", "-m", "app.smoke.celery_redis_isolation", command],
                            "envFrom": [
                                {"configMapRef": {"name": config_map}},
                                {"secretRef": {"name": secret}},
                            ],
                        }
                    ],
                },
            },
        },
    }


def wait_for_job(namespace: str, name: str, timeout: int, poll_interval: int) -> None:
    deadline = time.monotonic() + timeout
    last_status: dict[str, Any] = {}
    while time.monotonic() < deadline:
        payload = kubectl(["-n", namespace, "get", "job", name, "-o", "json"])
        job = json.loads(payload)
        last_status = job.get("status") or {}
        if int(last_status.get("succeeded") or 0) > 0:
            return
        if int(last_status.get("failed") or 0) > 0:
            raise RuntimeError(f"job {name} failed: {last_status}")
        time.sleep(poll_interval)
    raise RuntimeError(f"job {name} timed out: {last_status}")


def job_logs(namespace: str, name: str) -> str:
    return kubectl(["-n", namespace, "logs", f"job/{name}", "--all-containers=true"])


def safe_job_logs(namespace: str, name: str) -> str:
    try:
        return job_logs(namespace, name).strip()
    except Exception as exc:
        return f"<unable to read logs: {exc}>"


def delete_job(namespace: str, name: str) -> None:
    subprocess.run(
        ["kubectl", "-n", namespace, "delete", "job", name, "--ignore-not-found=true"],
        text=True,
        capture_output=True,
        check=False,
    )


def run_smoke_command(args: argparse.Namespace, image: str, command: str) -> dict[str, Any]:
    name = f"hr-certflow-smoke-{command.replace('_', '-')}-{int(time.time())}"
    manifest = smoke_job_manifest(
        namespace=args.namespace,
        name=name,
        image=image,
        command=command,
        service_account=args.service_account,
        config_map=args.config_map,
        secret=args.secret,
        image_pull_secret=args.image_pull_secret,
        active_deadline_seconds=args.timeout,
    )
    try:
        kubectl(["apply", "-f", "-"], input_text=json.dumps(manifest))
        wait_for_job(args.namespace, name, args.timeout, args.poll_interval)
        logs = job_logs(args.namespace, name).strip()
        return {"command": command, "job": name, "logs": logs}
    except Exception as exc:
        logs = safe_job_logs(args.namespace, name)
        raise RuntimeError(f"{command} smoke job failed: {exc}\nlogs:\n{logs}") from exc
    finally:
        delete_job(args.namespace, name)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run hr-certflow Celery/Redis smoke in Kubernetes Jobs")
    parser.add_argument("--namespace", required=True)
    parser.add_argument("--image")
    parser.add_argument("--api-deployment", default="hr-certflow-api")
    parser.add_argument("--command", action="append", dest="commands")
    parser.add_argument("--service-account", default="hr-certflow-runtime")
    parser.add_argument("--config-map", default="hr-certflow-config")
    parser.add_argument("--secret", default="hr-certflow-runtime-secrets")
    parser.add_argument("--image-pull-secret", default="ghcr-pull-secret")
    parser.add_argument("--timeout", type=int, default=180)
    parser.add_argument("--poll-interval", type=int, default=3)
    args = parser.parse_args()

    image = args.image or api_image(args.namespace, args.api_deployment)
    commands = args.commands or list(DEFAULT_COMMANDS)
    results = [run_smoke_command(args, image, command) for command in commands]
    print(json.dumps({"ok": True, "namespace": args.namespace, "image": image, "results": results}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"celery redis smoke failed: {exc}", file=sys.stderr)
        raise SystemExit(1)
