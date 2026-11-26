"""GlitchTip release 版本号的 Helm 渲染契约。

glitchtip.release 留空时必须自动回退为 web 镜像 tag：发版流水线只更新
images.web.tag，错误监控的 release 版本随之对齐，不需要手工同步 Argo 参数。
显式传入 glitchtip.release 时仍以显式值为准。

需要本机安装 helm CLI；无 helm 的环境整体跳过。
"""

import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
CHART_DIR = REPO_ROOT / "deploy" / "helm" / "hr-certflow"

# CI 必须装 helm（backend job 用 azure/setup-helm）：CI 缺 helm 时让用例失败，
# 避免静默绿灯；仅本地无 helm 的开发环境允许整体跳过。
pytestmark = pytest.mark.skipif(
    shutil.which("helm") is None and not os.getenv("CI"),
    reason="helm CLI not available outside CI",
)

HELM_TIMEOUT_SECONDS = 60


def render_chart(*overrides: str) -> str:
    command = ["helm", "template", "hr-certflow", str(CHART_DIR)]
    for override in overrides:
        command.extend(["--set", override])
    # Windows 下 locale 默认 GBK，helm 输出含中文注释必须显式按 UTF-8 解码。
    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=HELM_TIMEOUT_SECONDS,
    )
    assert result.returncode == 0, f"helm template failed: {result.stderr}"
    return result.stdout


def glitchtip_config_block(rendered: str) -> str:
    match = re.search(r"glitchtip-config\.js: \|\n((?: {4}.*\n)+)", rendered)
    assert match is not None, "glitchtip ConfigMap not rendered"
    return match.group(1)


def glitchtip_checksum(rendered: str) -> str:
    match = re.search(r'checksum/glitchtip-config: "([0-9a-f]{64})"', rendered)
    assert match is not None, "glitchtip checksum annotation not rendered"
    return match.group(1)


def test_empty_release_falls_back_to_web_image_tag() -> None:
    rendered = render_chart(
        "glitchtip.enabled=true",
        "glitchtip.release=",
        "images.web.tag=web-tag-fallback-probe",
    )

    assert 'release: "web-tag-fallback-probe"' in glitchtip_config_block(rendered)


def test_explicit_release_overrides_web_image_tag() -> None:
    rendered = render_chart(
        "glitchtip.enabled=true",
        "glitchtip.release=explicit-release-probe",
        "images.web.tag=web-tag-overridden-probe",
    )

    block = glitchtip_config_block(rendered)
    assert 'release: "explicit-release-probe"' in block
    assert "web-tag-overridden-probe" not in block


def test_checksum_rolls_when_image_tag_changes_with_empty_release() -> None:
    before = render_chart(
        "glitchtip.enabled=true",
        "glitchtip.release=",
        "images.web.tag=web-tag-before",
    )
    after = render_chart(
        "glitchtip.enabled=true",
        "glitchtip.release=",
        "images.web.tag=web-tag-after",
    )

    assert glitchtip_checksum(before) != glitchtip_checksum(after)


def test_checksum_stable_when_explicit_release_pinned() -> None:
    before = render_chart(
        "glitchtip.enabled=true",
        "glitchtip.release=pinned-release-probe",
        "images.web.tag=web-tag-one",
    )
    after = render_chart(
        "glitchtip.enabled=true",
        "glitchtip.release=pinned-release-probe",
        "images.web.tag=web-tag-two",
    )

    assert glitchtip_checksum(before) == glitchtip_checksum(after)


def test_explicit_zero_release_is_respected_not_fallback() -> None:
    # helm 的 default 会把数字 0 当空值，契约要求：非空字符串标量一旦显式传入
    # 就必须生效，不得静默回退镜像 tag。
    rendered = render_chart(
        "glitchtip.enabled=true",
        "glitchtip.release=0",
        "images.web.tag=web-tag-should-not-win",
    )

    block = glitchtip_config_block(rendered)
    assert 'release: "0"' in block
    assert "web-tag-should-not-win" not in block


def test_release_omitted_when_fallback_tag_is_latest() -> None:
    # chart 默认占位 tag latest（或空）不是有意义的版本号：
    # 注入 release "latest" 会让所有事件聚到一个伪版本，不如省略。
    rendered = render_chart(
        "glitchtip.enabled=true",
        "glitchtip.release=",
        "images.web.tag=latest",
    )

    block = glitchtip_config_block(rendered)
    assert "release:" not in block


def test_release_omitted_when_fallback_tag_is_empty() -> None:
    rendered = render_chart(
        "glitchtip.enabled=true",
        "glitchtip.release=",
        "images.web.tag=",
    )

    block = glitchtip_config_block(rendered)
    assert "release:" not in block


def test_explicit_release_is_respected_even_when_it_is_latest() -> None:
    # 显式传入优先：即便值本身是 latest，也是部署方的明确选择。
    rendered = render_chart(
        "glitchtip.enabled=true",
        "glitchtip.release=latest",
        "images.web.tag=web-tag-real-version",
    )

    block = glitchtip_config_block(rendered)
    assert 'release: "latest"' in block
    assert "web-tag-real-version" not in block
