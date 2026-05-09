from app.core.config import Settings
from app.services.storage import ObjectStorage


class FakeS3Client:
    def __init__(self) -> None:
        self.put_calls: list[dict] = []
        self.presign_calls: list[dict] = []

    def put_object(self, **kwargs) -> None:
        self.put_calls.append(kwargs)

    def generate_presigned_url(self, client_method: str, Params: dict, ExpiresIn: int) -> str:
        self.presign_calls.append(
            {
                "client_method": client_method,
                "Params": Params,
                "ExpiresIn": ExpiresIn,
            }
        )
        return f"https://signed.example.test/{client_method}/{Params['Bucket']}/{Params['Key']}"


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


def test_create_read_url_uses_presigned_get(monkeypatch) -> None:
    client = FakeS3Client()
    storage = ObjectStorage(
        Settings(
            s3_endpoint_url="https://oss-cn-hangzhou.aliyuncs.com",
            s3_bucket="hr-certflow-test",
            upload_prefix="certificates",
            s3_force_path_style=False,
        )
    )
    monkeypatch.setattr(storage, "_client", lambda: client)

    read_url = storage.create_read_url(
        bucket="hr-certflow-test",
        key="certificates/2026/05/07/demo.pdf",
        expires_in=600,
    )

    assert read_url.startswith("https://signed.example.test/get_object/")
    assert client.presign_calls == [
        {
            "client_method": "get_object",
            "Params": {
                "Bucket": "hr-certflow-test",
                "Key": "certificates/2026/05/07/demo.pdf",
            },
            "ExpiresIn": 600,
        }
    ]


def test_upload_intent_returns_presigned_put_and_read_urls(monkeypatch) -> None:
    client = FakeS3Client()
    storage = ObjectStorage(
        Settings(
            s3_endpoint_url="https://oss-cn-hangzhou.aliyuncs.com",
            s3_bucket="hr-certflow-test",
            upload_prefix="certificates",
            s3_force_path_style=False,
        )
    )
    monkeypatch.setattr(storage, "_client", lambda: client)

    intent = storage.create_upload_intent(
        original_filename="safety certificate.pdf",
        content_type="application/pdf",
        expires_in=600,
    )

    assert intent.bucket == "hr-certflow-test"
    assert intent.key.startswith("certificates/")
    assert intent.key.endswith("-safety-certificate.pdf")
    assert intent.upload_url.startswith("https://signed.example.test/put_object/")
    assert intent.read_url is not None
    assert intent.read_url.startswith("https://signed.example.test/get_object/")
    assert [call["client_method"] for call in client.presign_calls] == ["put_object", "get_object"]
