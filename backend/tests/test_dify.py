from app.services.dify import normalize_dify_outputs


def test_normalize_dify_outputs_strips_think_and_markdown_json() -> None:
    output = normalize_dify_outputs(
        {
            "result": """
<think>model reasoning should not be persisted</think>
```json
{
  "holder_name": " 张三 ",
  "certificate_name": "安全生产资格证",
  "certificate_no": "CERT-001",
  "suspicious_points": ["证书边角模糊", 123],
  "unexpected": "drop me"
}
```
""",
        }
    )

    assert output == {
        "holder_name": "张三",
        "certificate_name": "安全生产资格证",
        "certificate_no": "CERT-001",
        "suspicious_points": ["证书边角模糊", "123"],
    }


def test_normalize_dify_outputs_unwraps_nested_json_string() -> None:
    output = normalize_dify_outputs(
        {
            "data": {
                "outputs": '{"holder_name":"李四","confidence":"0.88","suspicious_points":"[\\"需核对钢印\\"]"}'
            }
        }
    )

    assert output["holder_name"] == "李四"
    assert output["confidence"] == 0.88
    assert output["suspicious_points"] == ["需核对钢印"]
