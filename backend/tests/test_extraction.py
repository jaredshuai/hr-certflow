from app.services.extraction import normalize_extraction_output


def test_normalize_extraction_output_recovers_json_after_thinking_text() -> None:
    output = {
        "holder_name": 'is "孙启凡"',
        "certificate_name": '技术资格" but according to the rules',
        "certificate_no": "/",
        "raw_text": (
            '<think>{"holder_name":"错误样例"}</think>'
            '{"holder_name":"孙启凡","certificate_name":"信息系统项目管理师",'
            '"certificate_no":"17201330212","issue_date":"2017-11-11",'
            '"raw_text":"证书正文 OCR","suspicious_points":[],"model_name":"kimi"}'
        ),
        "suspicious_points": [],
    }

    normalized = normalize_extraction_output(output)

    assert normalized["holder_name"] == "孙启凡"
    assert normalized["certificate_name"] == "信息系统项目管理师"
    assert normalized["certificate_no"] == "17201330212"
    assert normalized["raw_text"] == "证书正文 OCR"
    assert normalized["model_name"] == "kimi"
    assert normalized["suspicious_points"] == ["模型返回包含非结构化文本，系统已从末尾 JSON 恢复字段，请人工核对。"]


def test_normalize_extraction_output_keeps_clean_outputs() -> None:
    output = {
        "holder_name": "张三",
        "certificate_name": "安全员证",
        "certificate_no": "A-001",
        "raw_text": "姓名：张三\n证书编号：A-001",
    }

    assert normalize_extraction_output(output) == output
