from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from celery.exceptions import TimeoutError as CeleryTimeoutError
from redis import Redis
from redis.exceptions import RedisError, ResponseError

BACKEND = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class RuntimeEnv:
    app_env: str
    redis_url: str
    broker_url: str
    result_backend: str
    namespace: str
    queue: str
    routing_key: str
    hash_tag: str
    prefix: str


def choose(*values: str | None) -> str | None:
    for value in values:
        if value:
            return value
    return None


def require(value: str | None, name: str) -> str:
    if not value:
        raise RuntimeError(f"{name} is required; inject it through the environment or pass the matching option")
    return value


def runtime_from_args(args: argparse.Namespace) -> RuntimeEnv:
    app_env = require(choose(getattr(args, "app_env", None), os.getenv("APP_ENV")), "APP_ENV")
    redis_url = require(choose(getattr(args, "redis_url", None), os.getenv("REDIS_URL")), "REDIS_URL")
    namespace = require(
        choose(getattr(args, "namespace", None), os.getenv("CELERY_NAMESPACE"), f"hr-certflow-{app_env}"),
        "CELERY_NAMESPACE",
    )
    queue = require(choose(getattr(args, "queue", None), os.getenv("CELERY_QUEUE"), namespace), "CELERY_QUEUE")
    routing_key = require(
        choose(getattr(args, "routing_key", None), os.getenv("CELERY_ROUTING_KEY"), queue),
        "CELERY_ROUTING_KEY",
    )
    hash_tag = require(
        choose(getattr(args, "hash_tag", None), os.getenv("CELERY_REDIS_HASH_TAG"), namespace),
        "CELERY_REDIS_HASH_TAG",
    )
    prefix = require(
        choose(getattr(args, "prefix", None), os.getenv("CELERY_REDIS_PREFIX"), f"{hash_tag}:"),
        "CELERY_REDIS_PREFIX",
    )
    return RuntimeEnv(
        app_env=app_env,
        redis_url=redis_url,
        broker_url=choose(getattr(args, "broker_url", None), os.getenv("CELERY_BROKER_URL"), redis_url) or redis_url,
        result_backend=choose(getattr(args, "result_backend", None), os.getenv("CELERY_RESULT_BACKEND"), redis_url)
        or redis_url,
        namespace=namespace,
        queue=queue,
        routing_key=routing_key,
        hash_tag=hash_tag,
        prefix=prefix,
    )


def build_env(base_env: dict[str, str], runtime: RuntimeEnv) -> dict[str, str]:
    env = dict(base_env)
    env.update(
        {
            "PYTHONPATH": f"{BACKEND}{os.pathsep}{env.get('PYTHONPATH', '')}",
            "APP_ENV": runtime.app_env,
            "AUTO_CREATE_TABLES": "false",
            "REDIS_URL": runtime.redis_url,
            "CELERY_BROKER_URL": runtime.broker_url,
            "CELERY_RESULT_BACKEND": runtime.result_backend,
            "CELERY_NAMESPACE": runtime.namespace,
            "CELERY_QUEUE": runtime.queue,
            "CELERY_ROUTING_KEY": runtime.routing_key,
            "CELERY_REDIS_HASH_TAG": runtime.hash_tag,
            "CELERY_REDIS_PREFIX": runtime.prefix,
        }
    )
    return env


def marker(prefix: str) -> str:
    return f"{prefix}-{int(time.time())}"


def send_probe(runtime: RuntimeEnv, *, expected_env: str, task_marker: str, timeout: int) -> dict[str, Any]:
    os.environ.update(build_env(dict(os.environ), runtime))
    sys.path.insert(0, str(BACKEND))

    from app.celery_app import celery_app  # noqa: PLC0415
    from app.core.config import get_settings  # noqa: PLC0415

    settings = get_settings()
    result = celery_app.send_task(
        "app.tasks.probe",
        args=[expected_env, task_marker],
        queue=settings.resolved_celery_queue,
        routing_key=settings.resolved_celery_routing_key,
    )
    try:
        payload = result.get(timeout=timeout)
    except CeleryTimeoutError as exc:
        raise TimeoutError(json.dumps({"status": "timeout", "marker": task_marker, "task_id": result.id})) from exc
    return payload


def worker_command(runtime: RuntimeEnv) -> list[str]:
    return [
        sys.executable,
        "-m",
        "celery",
        "-A",
        "app.celery_app.celery_app",
        "worker",
        "--loglevel=warning",
        "--pool=solo",
        "--concurrency=1",
        "-Q",
        runtime.queue,
        "--hostname",
        f"{runtime.namespace}@%h",
        "--without-gossip",
        "--without-mingle",
        "--without-heartbeat",
    ]


def start_worker(runtime: RuntimeEnv) -> subprocess.Popen:
    env = build_env(dict(os.environ), runtime)
    cmd = worker_command(runtime)
    return subprocess.Popen(cmd, cwd=BACKEND, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)


def stop_worker(worker: subprocess.Popen) -> None:
    if worker.poll() is not None:
        return
    worker.terminate()
    try:
        worker.wait(timeout=10)
    except subprocess.TimeoutExpired:
        worker.kill()
        worker.wait(timeout=10)


def run_send_subprocess(runtime: RuntimeEnv, *, expected_env: str, task_marker: str, timeout: int) -> dict[str, Any]:
    cmd = [
        sys.executable,
        str(Path(__file__).resolve()),
        "send",
        "--expected-env",
        expected_env,
        "--marker",
        task_marker,
        "--timeout",
        str(timeout),
    ]
    completed = subprocess.run(
        cmd,
        cwd=BACKEND,
        env=build_env(dict(os.environ), runtime),
        text=True,
        capture_output=True,
        timeout=timeout + 5,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            "probe failed "
            f"(env={runtime.app_env}, namespace={runtime.namespace}, marker={task_marker}, rc={completed.returncode})\n"
            f"stdout:\n{completed.stdout}\n"
            f"stderr:\n{completed.stderr}"
        )
    return json.loads(completed.stdout)


def run_send_expect_timeout(
    runtime: RuntimeEnv,
    *,
    expected_env: str,
    task_marker: str,
    timeout: int,
) -> dict[str, Any]:
    cmd = [
        sys.executable,
        str(Path(__file__).resolve()),
        "send",
        "--expected-env",
        expected_env,
        "--marker",
        task_marker,
        "--timeout",
        str(timeout),
    ]
    try:
        completed = subprocess.run(
            cmd,
            cwd=BACKEND,
            env=build_env(dict(os.environ), runtime),
            text=True,
            capture_output=True,
            timeout=timeout + 5,
        )
    except subprocess.TimeoutExpired as exc:
        return {"status": "timeout", "marker": task_marker, "reason": f"subprocess timeout after {exc.timeout}s"}

    if completed.returncode == 2:
        return json.loads(completed.stdout)
    if completed.returncode == 0:
        payload = json.loads(completed.stdout)
        raise RuntimeError(f"task was consumed but a timeout was expected: {payload}")
    raise RuntimeError(
        "task failed instead of timing out; this can indicate cross-environment consumption\n"
        f"stdout:\n{completed.stdout}\n"
        f"stderr:\n{completed.stderr}"
    )


def redis_client(redis_url: str):
    return Redis.from_url(redis_url, decode_responses=True, socket_timeout=5)


def scan_keys(client, pattern: str, limit: int) -> list[str]:
    keys: list[str] = []
    for key in client.scan_iter(match=pattern, count=200):
        keys.append(str(key))
        if len(keys) >= limit:
            break
    return keys


def check_naked_key(client, key: str) -> dict[str, Any]:
    exists = bool(client.exists(key))
    return {"key": key, "status": "present" if exists else "absent"}


def assert_redis_keys(runtime: RuntimeEnv, *, key_scan_limit: int) -> dict[str, Any]:
    client = redis_client(runtime.redis_url)
    naked_keys = ["celery", "_kombu.binding.celery", "unacked", "unacked_index"]

    try:
        prefixed_keys = scan_keys(client, f"{runtime.prefix}*", key_scan_limit)
        naked_report = [check_naked_key(client, key) for key in naked_keys]
        naked_task_meta = scan_keys(client, "celery-task-meta-*", key_scan_limit)
    except ResponseError as exc:
        if "MOVED" in str(exc) or "CROSSSLOT" in str(exc):
            raise RuntimeError(f"Redis routing failure during key inspection: {exc}") from exc
        raise
    except RedisError as exc:
        raise RuntimeError(f"Redis key inspection failed: {exc}") from exc

    bad_prefixed = [key for key in prefixed_keys if not key.startswith(runtime.prefix)]
    present_naked = [entry["key"] for entry in naked_report if entry["status"] == "present"]
    present_naked.extend(naked_task_meta)

    if present_naked:
        raise RuntimeError(f"found naked Celery Redis keys: {present_naked[:20]}")
    if bad_prefixed:
        raise RuntimeError(f"found keys outside namespace prefix {runtime.prefix}: {bad_prefixed[:20]}")

    return {
        "namespace": runtime.namespace,
        "allowed_prefix": runtime.prefix,
        "checked_prefixed_key_count": len(prefixed_keys),
        "naked_key_report": naked_report,
        "naked_task_meta": "absent",
    }


def command_send(args: argparse.Namespace) -> int:
    runtime = runtime_from_args(args)
    expected_env = choose(args.expected_env, runtime.app_env) or runtime.app_env
    task_marker = choose(args.marker, marker(runtime.app_env)) or marker(runtime.app_env)
    try:
        payload = send_probe(runtime, expected_env=expected_env, task_marker=task_marker, timeout=args.timeout)
    except TimeoutError as exc:
        print(exc.args[0])
        return 2
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def command_expect_timeout(args: argparse.Namespace) -> int:
    runtime = runtime_from_args(args)
    task_marker = choose(args.marker, marker(f"{runtime.app_env}-timeout")) or marker(f"{runtime.app_env}-timeout")
    payload = run_send_expect_timeout(
        runtime,
        expected_env=choose(args.expected_env, runtime.app_env) or runtime.app_env,
        task_marker=task_marker,
        timeout=args.timeout,
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def command_assert_keys(args: argparse.Namespace) -> int:
    runtime = runtime_from_args(args)
    payload = assert_redis_keys(runtime, key_scan_limit=args.key_scan_limit)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def command_selftest(args: argparse.Namespace) -> int:
    runtime = runtime_from_args(args)
    worker = start_worker(runtime)
    time.sleep(args.worker_startup_seconds)
    try:
        probe_payload = run_send_subprocess(
            runtime,
            expected_env=runtime.app_env,
            task_marker=marker(runtime.app_env),
            timeout=args.timeout,
        )
        key_payload = assert_redis_keys(runtime, key_scan_limit=args.key_scan_limit)
    finally:
        stop_worker(worker)

    print(
        json.dumps(
            {
                "ok": True,
                "mode": "selftest",
                "namespace": runtime.namespace,
                "probe": probe_payload,
                "redis_keys": key_payload,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def command_dual_local(args: argparse.Namespace) -> int:
    redis_url = require(choose(args.redis_url, os.getenv("REDIS_URL")), "REDIS_URL")
    dev_runtime = RuntimeEnv(
        app_env=args.dev_env,
        redis_url=redis_url,
        broker_url=choose(os.getenv("CELERY_BROKER_URL"), redis_url) or redis_url,
        result_backend=choose(os.getenv("CELERY_RESULT_BACKEND"), redis_url) or redis_url,
        namespace=args.dev_namespace,
        queue=args.dev_namespace,
        routing_key=args.dev_namespace,
        hash_tag=args.dev_namespace,
        prefix=f"{args.dev_namespace}:",
    )
    release_runtime = RuntimeEnv(
        app_env=args.release_env,
        redis_url=redis_url,
        broker_url=choose(os.getenv("CELERY_BROKER_URL"), redis_url) or redis_url,
        result_backend=choose(os.getenv("CELERY_RESULT_BACKEND"), redis_url) or redis_url,
        namespace=args.release_namespace,
        queue=args.release_namespace,
        routing_key=args.release_namespace,
        hash_tag=args.release_namespace,
        prefix=f"{args.release_namespace}:",
    )

    dev_worker = start_worker(dev_runtime)
    release_worker = start_worker(release_runtime)
    time.sleep(args.worker_startup_seconds)

    try:
        dev_payload = run_send_subprocess(
            dev_runtime,
            expected_env=dev_runtime.app_env,
            task_marker=marker("dev"),
            timeout=args.timeout,
        )
        release_payload = run_send_subprocess(
            release_runtime,
            expected_env=release_runtime.app_env,
            task_marker=marker("release"),
            timeout=args.timeout,
        )
        stop_worker(dev_worker)
        stopped_dev_probe = run_send_expect_timeout(
            dev_runtime,
            expected_env=dev_runtime.app_env,
            task_marker=marker("dev-worker-stopped"),
            timeout=args.stopped_worker_timeout,
        )
        dev_worker = start_worker(dev_runtime)
        time.sleep(args.worker_startup_seconds)
        recovered_payload = run_send_subprocess(
            dev_runtime,
            expected_env=dev_runtime.app_env,
            task_marker=marker("dev-recovered"),
            timeout=args.timeout,
        )
    finally:
        stop_worker(dev_worker)
        stop_worker(release_worker)

    print(
        json.dumps(
            {
                "ok": True,
                "mode": "dual-local",
                "dev_probe": dev_payload,
                "release_probe": release_payload,
                "stopped_dev_probe": stopped_dev_probe,
                "dev_recovered_probe": recovered_payload,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def add_runtime_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--redis-url")
    parser.add_argument("--broker-url")
    parser.add_argument("--result-backend")
    parser.add_argument("--app-env")
    parser.add_argument("--namespace")
    parser.add_argument("--queue")
    parser.add_argument("--routing-key")
    parser.add_argument("--hash-tag")
    parser.add_argument("--prefix")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Smoke test Celery Redis namespace isolation")
    subparsers = parser.add_subparsers(dest="command", required=True)

    selftest = subparsers.add_parser("selftest", help="Start a temporary worker and verify this namespace")
    add_runtime_options(selftest)
    selftest.add_argument("--worker-startup-seconds", type=int, default=8)
    selftest.add_argument("--timeout", type=int, default=30)
    selftest.add_argument("--key-scan-limit", type=int, default=500)

    send = subparsers.add_parser("send", help="Send a probe task and wait for a running worker")
    add_runtime_options(send)
    send.add_argument("--expected-env")
    send.add_argument("--marker")
    send.add_argument("--timeout", type=int, default=30)

    expect_timeout = subparsers.add_parser("expect-timeout", help="Send a probe task and require it to time out")
    add_runtime_options(expect_timeout)
    expect_timeout.add_argument("--expected-env")
    expect_timeout.add_argument("--marker")
    expect_timeout.add_argument("--timeout", type=int, default=8)

    assert_keys = subparsers.add_parser("assert-keys", help="Inspect Redis keys visible to this runtime user")
    add_runtime_options(assert_keys)
    assert_keys.add_argument("--key-scan-limit", type=int, default=500)

    dual_local = subparsers.add_parser("dual-local", help="Run dev/release locally with one non-ACL Redis URL")
    dual_local.add_argument("--redis-url")
    dual_local.add_argument("--dev-env", default="dev")
    dual_local.add_argument("--release-env", default="release")
    dual_local.add_argument("--dev-namespace", default="hr-certflow-dev")
    dual_local.add_argument("--release-namespace", default="hr-certflow-release")
    dual_local.add_argument("--worker-startup-seconds", type=int, default=8)
    dual_local.add_argument("--timeout", type=int, default=30)
    dual_local.add_argument("--stopped-worker-timeout", type=int, default=8)
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        if args.command == "selftest":
            return command_selftest(args)
        if args.command == "send":
            return command_send(args)
        if args.command == "expect-timeout":
            return command_expect_timeout(args)
        if args.command == "assert-keys":
            return command_assert_keys(args)
        if args.command == "dual-local":
            return command_dual_local(args)
    except RuntimeError as exc:
        print(f"smoke failed: {exc}", file=sys.stderr)
        return 2
    parser.error(f"unsupported command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
