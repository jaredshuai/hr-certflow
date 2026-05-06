from app.core.config import Settings
from app.services.storage import ObjectStorage


class FakeS3Client:
    def __init__(self) -> None:
        self.put_calls: list[dict] = []

    def put_object(self, **kwargs) -> None:
        self.put_calls.append(kwargs)


def test_ai_raw_response_snapshot_writes_json(monkeypatch) -> None:
    client = FakeS3Client()
    storage = ObjectStorage(
        Settings(
            s3_endpoint_url="http://s3.example.test",
            s3_bucket="hr-certflow-test",
            upload_prefix="certificates",
        )
    )
    monkeypatch.setattr(storage, "_client", lambda: client)

    key = storage.build_ai_raw_response_key(
        "00000000-0000-0000-0000-000000000000",
        "workflow/run 1",
    )
    returned_key = storage.put_json_snapshot(key=key, payload={"raw_text": "安全证书"})

    assert returned_key == key
    assert key.startswith("certificates/ai-responses/")
    assert key.endswith(".json")
    assert client.put_calls[0]["Bucket"] == "hr-certflow-test"
    assert client.put_calls[0]["Key"] == key
    assert client.put_calls[0]["ContentType"] == "application/json; charset=utf-8"
    assert client.put_calls[0]["Body"].decode("utf-8") == '{"raw_text": "安全证书"}'
