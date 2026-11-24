"""The trusted current principal produced by the access package."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from jxccs_authz import Principal as AuthzPrincipal

Source = Literal["oidc", "mock"]
AccountStatus = Literal["ACTIVE", "DISABLED", "LOCKED"]

#: Source label written by 0.1.x sessions before the label was made
#: provider-neutral. Still accepted when reading a stored session so that
#: sessions created by an earlier release keep working; never written again.
LEGACY_SOURCE_CASDOOR = "casdoor"


@dataclass(frozen=True)
class Principal:
    """Identity facts from a verified login plus the Authorization Center directory.

    ``issuer_key`` is the registered directory issuer key (never derived from a
    token); ``sub`` is the opaque OIDC subject. Directory attributes come from
    subject-context (or the mock fixture) and are display/data-scope facts only.
    """

    issuer_key: str
    sub: str
    display_name: str | None
    employee_id: str | None
    department_ids: tuple[str, ...]
    account_status: AccountStatus
    source: Source

    def to_authz(self) -> AuthzPrincipal:
        return AuthzPrincipal(
            issuer=self.issuer_key,
            sub=self.sub,
            account_status=self.account_status,
            department_ids=self.department_ids,
            departments_confirmed=True,
            employee_id=self.employee_id,
            display_name=self.display_name,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "issuer_key": self.issuer_key,
            "sub": self.sub,
            "display_name": self.display_name,
            "employee_id": self.employee_id,
            "department_ids": list(self.department_ids),
            "account_status": self.account_status,
            "source": self.source,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Principal:
        source = data["source"]
        status = data["account_status"]
        if source == LEGACY_SOURCE_CASDOOR:
            # A session stored before the label was made provider-neutral. It is
            # still a real (non-mock) OIDC login, so it maps onto the current
            # label; the stored bytes are left untouched.
            source = "oidc"
        if source not in ("oidc", "mock") or status not in ("ACTIVE", "DISABLED", "LOCKED"):
            raise ValueError("invalid stored principal")
        return cls(
            issuer_key=str(data["issuer_key"]),
            sub=str(data["sub"]),
            display_name=data.get("display_name"),
            employee_id=data.get("employee_id"),
            department_ids=tuple(str(d) for d in data.get("department_ids", ())),
            account_status=status,
            source=source,
        )
