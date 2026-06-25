from __future__ import annotations

import argparse
import json
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def fetch(url: str, timeout: int) -> tuple[int, str]:
    request = Request(url, headers={"User-Agent": "hr-certflow-smoke/0.1"})
    with urlopen(request, timeout=timeout) as response:
        body = response.read(4096).decode("utf-8", errors="replace")
        return response.status, body


def check_url(name: str, url: str, timeout: int, retries: int, expect_json_status: bool) -> dict:
    last_error = None
    for attempt in range(1, retries + 1):
        try:
            status, body = fetch(url, timeout)
            if status >= 400:
                raise RuntimeError(f"HTTP {status}")
            if expect_json_status:
                payload = json.loads(body)
                if payload.get("status") != "ok":
                    raise RuntimeError(f"unexpected health payload: {payload}")
            return {"name": name, "url": url, "status": status, "attempt": attempt}
        except (HTTPError, URLError, TimeoutError, RuntimeError, json.JSONDecodeError) as exc:
            last_error = str(exc)
            time.sleep(min(attempt * 2, 10))

    raise RuntimeError(f"{name} smoke failed for {url}: {last_error}")


def main() -> int:
    parser = argparse.ArgumentParser(description="HTTP smoke test for hr-certflow")
    parser.add_argument("--web-url", required=True)
    # 网关 OIDC 启用后,集群外打 /api/v1/health 会 401;api 健康检查改由
    # smoke_api_probe.py 从集群内打 /_internal/healthz。这里 api-url 仅用于
    # 未启用网关认证的环境,故设为可选。
    parser.add_argument("--api-url", required=False, default=None)
    parser.add_argument("--timeout", type=int, default=10)
    parser.add_argument("--retries", type=int, default=12)
    args = parser.parse_args()

    results = [
        check_url("web", args.web_url, args.timeout, args.retries, expect_json_status=False),
    ]
    if args.api_url:
        results.append(
            check_url("api", args.api_url, args.timeout, args.retries, expect_json_status=True)
        )
    print(json.dumps({"ok": True, "results": results}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"smoke failed: {exc}", file=sys.stderr)
        raise SystemExit(1)
