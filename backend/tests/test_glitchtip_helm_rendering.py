"""GlitchTip release 版本号的 Helm 渲染契约。

glitchtip.release 留空时必须自动回退为 web 镜像 tag：发版流水线只更新
images.web.tag，错误监控的 release 版本随之对齐，不需要手工同步 Argo 参数。
显式传入 glitchtip.release 时仍以显式值为准。

需要本机安装 helm CLI；无 helm 的环境整体跳过。
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
CHART_DIR = REPO_ROOT / "deploy" / "helm" / "hr-certflow"

pytestmark = pytest.mark.skipif(
    shutil.which("helm") is None, reason="helm CLI not available"
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
