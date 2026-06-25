#!/usr/bin/env python3
"""Cluster-internal API probe smoke.

为什么需要这个脚本:
  网关启用 Casdoor OIDC 后,集群外未认证访问 /api/v1/health 会被网关 401,
  原有的经网关 HTTP smoke 不再适用。本脚本从集群内打 Pod 的探针端点
  /_internal/healthz —— 与 kubelet probe 完全相同的路径(集群内、绕网关、
  绕 AUTH_REQUIRED),用于验证「应用进程存活且探针端点可用」。

  经网关的应用层认证链路(Casdoor 注入 X-HR-Actor)由独立的验收步骤覆盖,
  不在 smoke 自动化范围内。

调用方式(见 release.yml / shared-k3s-smoke.yml):
  python scripts/smoke_api_probe.py --namespace hr-certflow-release \\
      --service hr-certflow-api --port 8000
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time


def kubectl_exec(namespace: str, service: str, port: int, path: str) -> tuple[int, str]:
    """在 api Pod 内用 python urllib 打本地探针,返回 (status, body)。"""
    # 用 python 而非 curl:api 镜像是 Python 应用,一定有解释器,curl 不保证存在。
    script = (
        "import json,urllib.request as u; "
        f"r=u.urlopen('http://{service}:{port}{path}',timeout=5); "
        "print(json.dumps({'status':r.status,'body':r.read(256).decode('utf-8','replace')}))"
    )
    completed = subprocess.run(
        [
            "kubectl",
            "exec",
            "-n",
            namespace,
            f"deploy/{service}",
            "--",
            "python",
            "-c",
            script,
        ],
        text=True,
        capture_output=True,
        check=False,
        timeout=60,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            f"kubectl exec failed (rc={completed.returncode})\n"
            f"stdout: {completed.stdout}\nstderr: {completed.stderr}"
        )
    payload = json.loads(completed.stdout.strip())
    return int(payload["status"]), str(payload.get("body", ""))


def discover_api_deployment(namespace: str) -> str:
    """按 component 标签发现 api Deployment 名,避免硬编码 fullname 差异。"""
    completed = subprocess.run(
        [
            "kubectl",
            "-n",
            namespace,
            "get",
            "deployment",
            "-l",
            "app.kubernetes.io/component=api",
            "-o",
            "jsonpath={.items[0].metadata.name}",
        ],
        text=True,
        capture_output=True,
        check=False,
        timeout=30,
    )
    if completed.returncode != 0 or not completed.stdout.strip():
        raise RuntimeError(
            f"no api deployment found in {namespace} via component label\n"
            f"stderr: {completed.stderr}"
        )
    return completed.stdout.strip()


def main() -> int:
    parser = argparse.ArgumentParser(description="Cluster-internal API probe smoke")
    parser.add_argument("--namespace", required=True)
    # service 默认为空时按 label 自动发现,适配不同环境的 fullname 差异。
    parser.add_argument("--service", default=None)
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--path", default="/_internal/healthz")
    parser.add_argument("--retries", type=int, default=6)
    args = parser.parse_args()

    service = args.service or discover_api_deployment(args.namespace)

    last_error: str | None = None
    for attempt in range(1, args.retries + 1):
        try:
            status, body = kubectl_exec(args.namespace, service, args.port, args.path)
            # 探针端点期望 2xx(204 No Content 或 200),不接受 3xx/4xx/5xx。
            if not 200 <= status < 300:
                raise RuntimeError(f"unexpected status {status}, body={body!r}")
            print(
                json.dumps(
                    {
                        "ok": True,
                        "probe": {"deployment": service, "path": args.path, "status": status},
                        "attempt": attempt,
                    },
                    ensure_ascii=False,
                )
            )
            return 0
        except Exception as exc:  # noqa: BLE001 - smoke 要聚合所有失败原因
            last_error = str(exc)
            time.sleep(min(attempt * 2, 10))

    print(f"api probe smoke failed: {last_error}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
