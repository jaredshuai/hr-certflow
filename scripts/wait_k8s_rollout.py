from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from typing import Any


DEFAULT_DEPLOYMENTS = ("hr-certflow-api", "hr-certflow-web", "hr-certflow-worker", "hr-certflow-beat")
DEFAULT_KUBECTL_TIMEOUT_SECONDS = 45


def kubectl(args: list[str], *, input_text: str | None = None, timeout_seconds: int = DEFAULT_KUBECTL_TIMEOUT_SECONDS) -> str:
    command = ["kubectl", f"--request-timeout={timeout_seconds}s", *args]
    try:
        completed = subprocess.run(
            command,
            input=input_text,
            text=True,
            capture_output=True,
            check=False,
            timeout=timeout_seconds + 5,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"{' '.join(command)} timed out after {timeout_seconds + 5}s") from exc
    if completed.returncode != 0:
        raise RuntimeError(f"{' '.join(command)} failed\nstdout:\n{completed.stdout}\nstderr:\n{completed.stderr}")
    return completed.stdout


def kubectl_diagnostic(args: list[str], *, max_lines: int = 160) -> str:
    command = ["kubectl", f"--request-timeout={DEFAULT_KUBECTL_TIMEOUT_SECONDS}s", *args]
    try:
        completed = subprocess.run(
            command,
            text=True,
            capture_output=True,
            check=False,
            timeout=DEFAULT_KUBECTL_TIMEOUT_SECONDS + 5,
        )
    except subprocess.TimeoutExpired:
        return f"{' '.join(command)} timed out after {DEFAULT_KUBECTL_TIMEOUT_SECONDS + 5}s"
    output = "\n".join(part for part in (completed.stdout, completed.stderr) if part)
    lines = output.splitlines()
    if len(lines) > max_lines:
        return "\n".join([f"... truncated to last {max_lines} lines ...", *lines[-max_lines:]])
    return output


def component_from_deployment(deployment: str) -> str:
    return deployment.rsplit("-", 1)[-1]


def print_rollout_diagnostics(namespace: str, deployment: str) -> None:
    component = component_from_deployment(deployment)
    checks = [
        (
            "namespace workload overview",
            ["-n", namespace, "get", "deployment,replicaset,pod,service,ingress", "-o", "wide"],
        ),
        ("deployment", ["-n", namespace, "get", "deployment", deployment, "-o", "wide"]),
        ("deployment describe", ["-n", namespace, "describe", "deployment", deployment]),
        (
            "replicasets and pods",
            [
                "-n",
                namespace,
                "get",
                "replicaset,pod",
                "-l",
                f"app.kubernetes.io/component={component}",
                "-o",
                "wide",
            ],
        ),
        ("recent events", ["-n", namespace, "get", "events", "--sort-by=.lastTimestamp"]),
    ]
    print(f"rollout diagnostics for {namespace}/{deployment}", file=sys.stderr)
    for title, args in checks:
        print(f"\n--- {title}: kubectl {' '.join(args)} ---", file=sys.stderr)
        print(kubectl_diagnostic(args), file=sys.stderr)


def deployment_images(namespace: str, deployment: str) -> list[str]:
    payload = kubectl(["-n", namespace, "get", "deployment", deployment, "-o", "json"])
    data = json.loads(payload)
    containers = data["spec"]["template"]["spec"].get("containers") or []
    return [container["image"] for container in containers]


def image_has_tag(image: str, tag: str) -> bool:
    return image.endswith(f":{tag}") or f":{tag}@" in image


def wait_for_deployment_tag(namespace: str, deployment: str, tag: str, deadline: float, poll_interval: int) -> list[str]:
    last_images: list[str] = []
    while time.monotonic() < deadline:
        last_images = deployment_images(namespace, deployment)
        if last_images and all(image_has_tag(image, tag) for image in last_images):
            return last_images
        time.sleep(poll_interval)
    raise RuntimeError(f"{deployment} did not reach image tag {tag}; last images: {last_images}")


def rollout_status(namespace: str, deployment: str, timeout_seconds: int) -> None:
    kubectl(
        [
            "-n",
            namespace,
            "rollout",
            "status",
            f"deployment/{deployment}",
            f"--timeout={timeout_seconds}s",
        ],
        timeout_seconds=timeout_seconds + 10,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Wait for hr-certflow Kubernetes deployments to reach an image tag")
    parser.add_argument("--namespace", required=True)
    parser.add_argument("--image-tag", required=True)
    parser.add_argument("--deployment", action="append", dest="deployments")
    parser.add_argument("--timeout", type=int, default=600)
    parser.add_argument("--poll-interval", type=int, default=10)
    args = parser.parse_args()

    deployments = args.deployments or list(DEFAULT_DEPLOYMENTS)
    deadline = time.monotonic() + args.timeout
    results: list[dict[str, Any]] = []

    for deployment in deployments:
        try:
            images = wait_for_deployment_tag(args.namespace, deployment, args.image_tag, deadline, args.poll_interval)
            remaining = max(1, int(deadline - time.monotonic()))
            rollout_status(args.namespace, deployment, remaining)
            results.append({"deployment": deployment, "images": images})
        except Exception:
            print_rollout_diagnostics(args.namespace, deployment)
            raise

    print(json.dumps({"ok": True, "namespace": args.namespace, "image_tag": args.image_tag, "results": results}))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"rollout wait failed: {exc}", file=sys.stderr)
        raise SystemExit(1)
