"""Fixture validation CLI: every persona capability must exist in the app manifest.

Usage: ``jxccs-access-check-fixture --fixture personas.yaml --manifest manifest.yaml``

Purely offline: reads two local files, never calls the Authorization Center.
Accepts the manifest either as ``spec.permissions`` (AuthorizationManifest
YAML draft) or top-level ``permissions`` (registry JSON), each permission
carrying ``id`` and ``resourceTypes``.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

import yaml

from .mock import FixtureError, load_fixture


def manifest_permissions(data: Any) -> dict[str, set[str]]:
    if not isinstance(data, dict):
        raise ValueError("manifest must be a mapping")
    spec: dict[str, Any] = data["spec"] if isinstance(data.get("spec"), dict) else data
    permissions = spec.get("permissions")
    if not isinstance(permissions, list):
        raise ValueError("manifest has no permissions list")
    result: dict[str, set[str]] = {}
    for entry in permissions:
        if not isinstance(entry, dict) or not isinstance(entry.get("id"), str):
            raise ValueError("manifest permission entries need an id")
        types = entry.get("resourceTypes")
        if not isinstance(types, list) or not all(isinstance(t, str) for t in types):
            raise ValueError(f"permission {entry['id']} needs resourceTypes")
        result[entry["id"]] = set(types)
    return result


def check(fixture_path: str, manifest_path: str) -> list[str]:
    """Return a list of problems (empty means the fixture is valid)."""
    try:
        fixture = load_fixture(fixture_path)
    except FixtureError as exc:
        return [f"fixture: {exc}"]
    try:
        manifest = manifest_permissions(
            yaml.safe_load(Path(manifest_path).read_text(encoding="utf-8"))
        )
    except (OSError, yaml.YAMLError, ValueError) as exc:
        return [f"manifest: {exc}"]
    problems: list[str] = []
    for persona in fixture.personas.values():
        for permission, resource_type in sorted(persona.capabilities):
            if permission not in manifest:
                problems.append(f"{persona.id}: permission {permission} is not in the manifest")
            elif resource_type not in manifest[permission]:
                problems.append(
                    f"{persona.id}: {permission} does not apply to resource type {resource_type}"
                )
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="jxccs-access-check-fixture")
    parser.add_argument("--fixture", required=True)
    parser.add_argument("--manifest", required=True)
    args = parser.parse_args(argv)
    problems = check(args.fixture, args.manifest)
    for problem in problems:
        print(problem, file=sys.stderr)
    if problems:
        return 1
    print("fixture OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
