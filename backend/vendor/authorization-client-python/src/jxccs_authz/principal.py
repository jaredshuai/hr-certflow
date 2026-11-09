"""Trusted backend-side Principal facts (frozen v1 identity contract).

This type is produced by the business backend after its own verified identity
integration (OIDC/session or an equivalent trusted source). It is never
deserialized from request bodies, headers or cookies, and it never
authenticates anything by itself.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

AccountStatus = Literal["ACTIVE", "DISABLED", "LOCKED"]

_VALID_STATUSES = frozenset({"ACTIVE", "DISABLED", "LOCKED"})


@dataclass(frozen=True)
class Principal:
    """Canonical identity facts loaded from a verified source.

    Identity is the exact ``(issuer, sub)`` pair. Employee id, display name,
    email and company roles are business/display attributes only and never
    participate in authorization decisions made here.

    Department facts use two fields, never ``None``:

    - ``department_ids == ()`` and ``departments_confirmed is False``:
      directory membership is unknown / not read;
    - ``department_ids == ()`` and ``departments_confirmed is True``:
      the directory confirmed the person has no department;
    - non-empty ``department_ids`` requires ``departments_confirmed is True``.

    ``account_status`` has no default: a Principal without a confirmed status
    cannot be constructed. The SDK never converts a DISABLED status into a
    local 401; any decision about that identity remains the PDP's.
    """

    issuer: str
    sub: str
    account_status: AccountStatus
    department_ids: tuple[str, ...] = ()
    departments_confirmed: bool = False
    employee_id: str | None = None
    display_name: str | None = None
    company_roles: tuple[str, ...] = field(default=())

    def __post_init__(self) -> None:
        if not isinstance(self.issuer, str) or not self.issuer:
            raise ValueError("principal issuer must be a non-empty string")
        if not isinstance(self.sub, str) or not self.sub:
            raise ValueError(
                "principal sub must be a non-empty string (never derived from employee id)"
            )
        if self.account_status not in _VALID_STATUSES:
            raise ValueError("principal account_status must be explicitly ACTIVE/DISABLED/LOCKED")
        if isinstance(self.department_ids, str):
            raise ValueError("department_ids must be a sequence of department id strings")
        departments = tuple(self.department_ids)
        if any(not isinstance(dept, str) or not dept for dept in departments):
            raise ValueError("department_ids must contain non-empty strings only")
        if not isinstance(self.departments_confirmed, bool):
            raise ValueError("departments_confirmed must be an explicit boolean")
        if departments and not self.departments_confirmed:
            raise ValueError(
                "non-empty department_ids require departments_confirmed=True; "
                "unknown membership is the empty tuple with departments_confirmed=False"
            )
        if isinstance(self.company_roles, str):
            raise ValueError("company_roles must be a sequence of role strings")
        roles = tuple(self.company_roles)
        if any(not isinstance(role, str) or not role for role in roles):
            raise ValueError("company_roles must contain non-empty strings only")
        object.__setattr__(self, "department_ids", departments)
        object.__setattr__(self, "company_roles", roles)

    @property
    def is_trusted(self) -> bool:
        """Shape-only presence check for the canonical pair.

        This does not verify provenance. The caller must have loaded the
        Principal from its verified identity source.
        """
        return bool(self.issuer) and bool(self.sub)

    def subject_wire(self) -> dict[str, str]:
        """M6 subject carries only the canonical ``issuer``/``sub`` pair.

        Department ids, account status, employee id, display name and company
        roles are loaded server-side by the PDP directory and are never sent.
        Issuer is compared exactly; no URL normalization or alias guessing.
        """
        return {"issuer": self.issuer, "sub": self.sub}

    def same_identity_as(self, other: Principal) -> bool:
        """Exact canonical pair match; ``sub`` is case-sensitive."""
        return self.issuer == other.issuer and self.sub == other.sub
