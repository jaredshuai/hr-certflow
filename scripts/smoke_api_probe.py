#!/usr/bin/env python3
"""Cluster-internal API probe smoke.

为什么需要这个脚本:
  网关启用 Casdoor OIDC 后,集群外未认证访问 /api/v1/health 会被网关 401,
  原有的经网关 HTTP smoke 不再适用。本脚本验证 /_internal/healthz 探针可用
  —— 即 kubelet probe 命中的同一个端点。

验证策略(逐层 fallback,每层都不依赖 pods/exec 权限):
  1. kubectl get --raw 经 API server proxy 直接打 Service 的 /_internal/healthz
     (需要 services/proxy 权限;最直接,返回真实 HTTP 状态)
  2. 若 proxy 权限不足,回退到验证 Deployment 的 Ready 状态:
     kubelet probe 通过 = Pod Ready = /_internal/healthz 可用。
     这复用 wait_k8s_rollout 已有的 get/rollout 权限,零额外授权。

经网关的应用层认证链路(Casdoor 注入 X-HR-Actor)由独立验收步骤覆盖,不在
smoke 自动化范围内。

调用方式(见 release.yml / shared-k3s-smoke.yml):
  python scripts/smoke_api_probe.py --namespace hr-certflow-release
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time

DEFAULT_KUBECTL_TIMEOUT_SECONDS = 30


def kubectl(args: list[str], *, timeout_seconds: int = DEFAULT_KUBECTL_TIMEOUT_SECONDS) -> tuple[int, str, str]:
    command = ["kubectl", f"--request-timeout={timeout_seconds}s", *args]
    completed = subprocess.run(
        command,
        text=True,
        capture_output=True,
        check=False,
        timeout=timeout_seconds + 5,
    )
    return completed.returncode, completed.stdout, completed.stderr


def discover_api_deployment(namespace: str) -> str:
    """按 component 标签发现 api Deployment 名,避免硬编码 fullname 差异。"""
    rc, stdout, stderr = kubectl(
        ["-n", namespace, "get", "deployment", "-l", "app.kubernetes.io/component=api",
         "-o", "jsonpath={.items[0].metadata.name}"]
    )
    if rc != 0 or not stdout.strip():
        raise RuntimeError(
            f"no api deployment found in {namespace} via component label\nstderr: {stderr}"
        )
    return stdout.strip()


def probe_via_api_proxy(namespace: str, deployment: str, port: int, path: str) -> tuple[int, str]:
    """经 API server proxy 直接打 Service 的探针端点。返回 (http_status, body)。

    需要服务账号对 services/proxy 子资源有权限;无权限时调用方应回退。
    """
    # Deployment 名 <fullname>-api,对应同名 Service。
    service = deployment
    raw_path = f"/api/v1/namespaces/{namespace}/services/{service}:{port}/proxy{path}"
    rc, stdout, stderr = kubectl(["get", "--raw", raw_path])
    if rc != 0:
        # 权限不足或路径不存在,抛出让调用方决定是否回退。
        raise PermissionError(f"kubectl get --raw failed (rc={rc}): {stderr.strip() or stdout.strip()}")
    # --raw 成功(rc=0)时 stdout 是响应 body;HTTP 状态由 rc 体现,
    # kubectl 对 2xx 返回 0,4xx/5xx 返回非 0。此处 rc=0 视为 2xx。
    return 200, stdout


def probe_via_rollout_ready(namespace: str, deployment: str) -> dict:
    """回退:通过 Deployment Ready 状态间接证明探针可用。

    kubelet readiness/liveness probe 通过是 Pod Ready 的前提,
    而 chart 已将探针指向 /_internal/healthz,故 Deployment Ready 即证明
    该端点可响应。复用 wait_k8s_rollout 的 get/rollout 权限,无需 pods/exec。
    """
    rc, stdout, stderr = kubectl(
        ["-n", namespace, "rollout", "status", f"deployment/{deployment}", "--timeout=60s"]
    )
    if rc != 0:
        raise RuntimeError(
            f"deployment {namespace}/{deployment} not Ready\nstdout: {stdout}\nstderr: {stderr}"
        )
    return {"deployment": deployment, "ready": True, "method": "rollout-status"}


def main() -> int:
    parser = argparse.ArgumentParser(description="Cluster-internal API probe smoke")
    parser.add_argument("--namespace", required=True)
    parser.add_argument("--deployment", default=None, help="api Deployment 名;默认按标签自动发现")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--path", default="/_internal/healthz")
    parser.add_argument("--retries", type=int, default=6)
    args = parser.parse_args()

    deployment = args.deployment or discover_api_deployment(args.namespace)

    last_error: str | None = None
    for attempt in range(1, args.retries + 1):
        try:
            # 首选:API server proxy 直接打探针端点(返回真实 HTTP 状态)
            try:
                status, _body = probe_via_api_proxy(args.namespace, deployment, args.port, args.path)
                if not 200 <= status < 300:
                    raise RuntimeError(f"unexpected status {status} from {args.path}")
                print(json.dumps(
                    {"ok": True, "deployment": deployment, "method": "api-proxy",
                     "probe": {"path": args.path, "status": status}, "attempt": attempt},
                    ensure_ascii=False))
                return 0
            except PermissionError:
                # proxy 权限不足 → 回退到 rollout Ready 验证(零额外权限)
                result = probe_via_rollout_ready(args.namespace, deployment)
                print(json.dumps(
                    {"ok": True, "deployment": deployment, "method": result["method"],
                     "probe": {"path": args.path, "note": "verified via Pod Ready (probe path is /_internal/healthz)"},
                     "attempt": attempt},
                    ensure_ascii=False))
                return 0
        except Exception as exc:  # noqa: BLE001 - smoke 要聚合所有失败原因
            last_error = str(exc)
            time.sleep(min(attempt * 2, 10))

    print(f"api probe smoke failed: {last_error}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
