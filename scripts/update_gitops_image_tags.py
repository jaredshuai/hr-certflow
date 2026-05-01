from __future__ import annotations

import argparse
from pathlib import Path

import yaml


def main() -> int:
    parser = argparse.ArgumentParser(description="Update GitOps image tags for hr-certflow")
    parser.add_argument("--values", required=True, type=Path)
    parser.add_argument("--api-repository", required=True)
    parser.add_argument("--web-repository", required=True)
    parser.add_argument("--tag", required=True)
    args = parser.parse_args()

    with args.values.open("r", encoding="utf-8") as file:
        data = yaml.safe_load(file) or {}

    images = data.setdefault("images", {})
    api = images.setdefault("api", {})
    web = images.setdefault("web", {})
    api["repository"] = args.api_repository
    api["tag"] = args.tag
    web["repository"] = args.web_repository
    web["tag"] = args.tag

    with args.values.open("w", encoding="utf-8") as file:
        yaml.safe_dump(data, file, sort_keys=False, allow_unicode=True)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
