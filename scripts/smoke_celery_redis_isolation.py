from __future__ import annotations

import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1] / "backend"


def main() -> int:
    sys.path.insert(0, str(BACKEND))
    from app.smoke.celery_redis_isolation import main as smoke_main

    return smoke_main()


if __name__ == "__main__":
    raise SystemExit(main())
