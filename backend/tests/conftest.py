from __future__ import annotations

import os

# 应用缺省 APP_ENV 按 release 处理（AUTH_REQUIRED=false 会拒绝启动）；
# 测试默认以 local 运行，需要其它环境的用例自行 monkeypatch。
os.environ.setdefault("APP_ENV", "local")
