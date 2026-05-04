from app.core.config import Settings
from app.smoke.celery_redis_isolation import runtime_from_args, worker_command


def test_celery_namespace_defaults_from_app_env() -> None:
    settings = Settings(app_env="dev", redis_url="redis://example:6379/0")

    assert settings.resolved_celery_broker_url == "redis://example:6379/0"
    assert settings.resolved_celery_result_backend == "redis://example:6379/0"
    assert settings.resolved_celery_namespace == "hr-certflow-dev"
    assert settings.resolved_celery_queue == "hr-certflow-dev"
    assert settings.resolved_celery_routing_key == "hr-certflow-dev"
    assert settings.resolved_celery_redis_hash_tag == "hr-certflow-dev"
    assert settings.resolved_celery_redis_prefix == "hr-certflow-dev:"
    assert settings.resolved_celery_fanout_prefix == "hr-certflow-dev:fanout"
    assert settings.resolved_celery_fanout_prefix.format(db=0) == "hr-certflow-dev:fanout"


def test_celery_explicit_namespace_overrides() -> None:
    settings = Settings(
        app_env="release",
        redis_url="redis://example:6379/0",
        celery_namespace="custom",
        celery_queue="custom-queue",
        celery_routing_key="custom-route",
        celery_redis_hash_tag="custom-slot",
        celery_redis_prefix="custom-slot:",
    )

    assert settings.resolved_celery_namespace == "custom"
    assert settings.resolved_celery_queue == "custom-queue"
    assert settings.resolved_celery_routing_key == "custom-route"
    assert settings.resolved_celery_redis_hash_tag == "custom-slot"
    assert settings.resolved_celery_redis_prefix == "custom-slot:"
    assert settings.resolved_celery_fanout_prefix.format(db=0) == "custom-slot:fanout"


def test_smoke_runtime_reads_redis_isolation_env(monkeypatch) -> None:
    redis_url = "redis://<redis-user>:<redis-password>@<redis-host>:6379/0"
    monkeypatch.setenv("APP_ENV", "dev")
    monkeypatch.setenv("REDIS_URL", redis_url)
    monkeypatch.setenv("CELERY_BROKER_URL", redis_url)
    monkeypatch.setenv("CELERY_RESULT_BACKEND", redis_url)
    monkeypatch.setenv("CELERY_NAMESPACE", "hr-certflow-dev")
    monkeypatch.setenv("CELERY_QUEUE", "hr-certflow-dev")
    monkeypatch.setenv("CELERY_ROUTING_KEY", "hr-certflow-dev")
    monkeypatch.setenv("CELERY_REDIS_HASH_TAG", "hr-certflow-dev")
    monkeypatch.setenv("CELERY_REDIS_PREFIX", "hr-certflow-dev:")

    runtime = runtime_from_args(type("Args", (), {})())

    assert runtime.app_env == "dev"
    assert runtime.queue == "hr-certflow-dev"
    assert runtime.routing_key == "hr-certflow-dev"
    assert runtime.hash_tag == "hr-certflow-dev"
    assert runtime.prefix == "hr-certflow-dev:"


def test_smoke_worker_command_disables_cluster_chatter(monkeypatch) -> None:
    redis_url = "redis://<redis-user>:<redis-password>@<redis-host>:6379/0"
    monkeypatch.setenv("APP_ENV", "dev")
    monkeypatch.setenv("REDIS_URL", redis_url)
    monkeypatch.setenv("CELERY_NAMESPACE", "hr-certflow-dev")
    monkeypatch.setenv("CELERY_QUEUE", "hr-certflow-dev")
    monkeypatch.setenv("CELERY_ROUTING_KEY", "hr-certflow-dev")
    monkeypatch.setenv("CELERY_REDIS_HASH_TAG", "hr-certflow-dev")
    monkeypatch.setenv("CELERY_REDIS_PREFIX", "hr-certflow-dev:")

    cmd = worker_command(runtime_from_args(type("Args", (), {})()))

    assert "-Q" in cmd
    assert "hr-certflow-dev" in cmd
    assert "--without-gossip" in cmd
    assert "--without-mingle" in cmd
    assert "--without-heartbeat" in cmd
