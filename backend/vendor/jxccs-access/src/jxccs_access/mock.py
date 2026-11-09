"""M-A mock: flat persona capability table (contract §4).

A fixture is ``{permission, resource_type}`` pairs per persona: allowed when the
pair is in the table, denied otherwise. There is no role, inheritance,
wildcard, condition, attribute, scope, deny or expiry semantics, and
``ResourceRef.attributes`` is ignored. Data scope stays in the business PEP via
``department_ids``.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from .principal import Principal

MOCK_ISSUER_KEY = "dir-test-mock"
MOCK_ISSUER_URL = "http://127.0.0.1:19091"
MOCK_SUB_PREFIX = "u-dir-"
MOCK_DEPARTMENT_PREFIX = "dept-dir-"
MOCK_REASON = "MOCK_TABLE"

_TOP_KEYS = {"version", "issuer_key", "issuer_url", "personas"}
_PERSONA_KEYS = {
    "id",
    "sub",
    "display_name",
    "employee_id",
    "department_ids",
    "account_status",
    "capabilities",
}
_CAPABILITY_KEYS = {"permission", "resource_type"}
_STATUSES = {"ACTIVE", "DISABLED", "LOCKED"}


class FixtureError(ValueError):
    pass


@dataclass(frozen=True)
class Persona:
    id: str
    principal: Principal
    capabilities: frozenset[tuple[str, str]]


@dataclass(frozen=True)
class PersonaFixture:
    personas: dict[str, Persona]

    def get(self, persona_id: str) -> Persona | None:
        return self.personas.get(persona_id)

    def allows(self, principal: Principal, permission: str, resource_type: str) -> bool:
        persona = next(
            (p for p in self.personas.values() if p.principal.sub == principal.sub), None
        )
        return persona is not None and (permission, resource_type) in persona.capabilities


def _str(value: Any, where: str) -> str:
    if not isinstance(value, str) or not value:
        raise FixtureError(f"{where} must be a non-empty string")
    return value


def _exact_keys(mapping: Any, allowed: set[str], where: str) -> dict[str, Any]:
    if not isinstance(mapping, dict):
        raise FixtureError(f"{where} must be a mapping")
    unknown = set(mapping) - allowed
    if unknown:
        raise FixtureError(f"{where} has unsupported keys: {sorted(unknown)}")
    return mapping


def parse_fixture(data: Any) -> PersonaFixture:
    top = _exact_keys(data, _TOP_KEYS, "fixture")
    if top.get("version") != 1:
        raise FixtureError("fixture version must be 1")
    if top.get("issuer_key") != MOCK_ISSUER_KEY:
        raise FixtureError(f"issuer_key must be {MOCK_ISSUER_KEY}")
    if top.get("issuer_url") != MOCK_ISSUER_URL:
        raise FixtureError(f"issuer_url must be {MOCK_ISSUER_URL}")
    raw_personas = top.get("personas")
    if not isinstance(raw_personas, list) or not raw_personas:
        raise FixtureError("personas must be a non-empty list")
    personas: dict[str, Persona] = {}
    subs: set[str] = set()
    for index, raw in enumerate(raw_personas):
        where = f"personas[{index}]"
        item = _exact_keys(raw, _PERSONA_KEYS, where)
        missing = _PERSONA_KEYS - set(item)
        if missing:
            raise FixtureError(f"{where} is missing keys: {sorted(missing)}")
        persona_id = _str(item["id"], f"{where}.id")
        sub = _str(item["sub"], f"{where}.sub")
        if not sub.startswith(MOCK_SUB_PREFIX):
            raise FixtureError(f"{where}.sub must start with {MOCK_SUB_PREFIX}")
        if persona_id in personas or sub in subs:
            raise FixtureError(f"{where} duplicates an id or sub")
        departments = item["department_ids"]
        if not isinstance(departments, list):
            raise FixtureError(f"{where}.department_ids must be a list")
        for dept in departments:
            if not _str(dept, f"{where}.department_ids").startswith(MOCK_DEPARTMENT_PREFIX):
                raise FixtureError(
                    f"{where}.department_ids must start with {MOCK_DEPARTMENT_PREFIX}"
                )
        status = item["account_status"]
        if status not in _STATUSES:
            raise FixtureError(f"{where}.account_status must be one of {sorted(_STATUSES)}")
        employee_id = item["employee_id"]
        if employee_id is not None and not isinstance(employee_id, str):
            raise FixtureError(f"{where}.employee_id must be a string or null")
        caps = item["capabilities"]
        if not isinstance(caps, list):
            raise FixtureError(f"{where}.capabilities must be a list")
        capabilities: set[tuple[str, str]] = set()
        for cap_index, cap in enumerate(caps):
            cap_where = f"{where}.capabilities[{cap_index}]"
            entry = _exact_keys(cap, _CAPABILITY_KEYS, cap_where)
            permission = _str(entry.get("permission"), f"{cap_where}.permission")
            resource_type = _str(entry.get("resource_type"), f"{cap_where}.resource_type")
            if any(ch in permission + resource_type for ch in "*?"):
                raise FixtureError(f"{cap_where} must not use wildcards")
            capabilities.add((permission, resource_type))
        principal = Principal(
            issuer_key=MOCK_ISSUER_KEY,
            sub=sub,
            display_name=_str(item["display_name"], f"{where}.display_name"),
            employee_id=employee_id,
            department_ids=tuple(departments),
            account_status=status,
            source="mock",
        )
        personas[persona_id] = Persona(persona_id, principal, frozenset(capabilities))
        subs.add(sub)
    return PersonaFixture(personas)


def load_fixture(path: str | Path) -> PersonaFixture:
    try:
        data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise FixtureError(f"cannot read fixture: {type(exc).__name__}") from exc
    return parse_fixture(data)
