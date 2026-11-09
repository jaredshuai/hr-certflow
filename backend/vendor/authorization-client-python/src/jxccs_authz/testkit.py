"""Local recorded-fixture provider, principal registry and in-memory reset.

This is a recorded-scenario replay, not a second evaluator: it never derives
allow/deny from grants itself. Grant/deny records only explain the fixed
scenario facts. Unknown tuples fail loudly as simulated configuration errors;
they are never guessed into a deny or an allow.

The provider only owns its own in-memory state. ``reset()`` accepts no path or
DSN and touches no database, Casdoor, authorization-center or k3s.
"""

from __future__ import annotations

import copy
import hashlib
import json
from importlib import resources
from typing import Any, cast

from .client import BATCH_CHECK_PATH, CHECK_PATH, RawResponse, SimulatedFailure
from .errors import FailureCategory
from .principal import AccountStatus, Principal

FIXTURE_SETS: dict[str, str] = {"jxccs-authz-v1": "jxccs-authz-v1.json"}

# Synthetic loopback issuer is a label only; it maps to no real identity
# provider and must never reach integration/release assemblies.
SYNTHETIC_ISSUER = "http://127.0.0.1:19091"


class ScenarioLoadError(ValueError):
    """The requested fixture scenario set does not exist / cannot be read."""


class FixtureTransport:
    """Replays recorded PDP HTTP envelopes against the exact request tuple.

    Tuple identity covers subject issuer/sub, application, environment,
    permission, resourceType, resourceId and the opaque attributes. Changing
    any of them produces a different tuple and cannot reuse a recorded allow.
    """

    def __init__(self, fixture: dict[str, Any]) -> None:
        self._baseline = copy.deepcopy(fixture)
        self._state: dict[str, Any] = copy.deepcopy(fixture)
        self._state["_callSeq"] = 0
        self._state["_observedTuples"] = []
        self._index = self._build_index(self._state)

    @classmethod
    def for_scenario(cls, scenario: str) -> FixtureTransport:
        if scenario not in FIXTURE_SETS:
            raise ScenarioLoadError(
                f"unknown fixture scenario {scenario!r}; no default scenario is allowed"
            )
        try:
            fixture_file = (
                resources.files("jxccs_authz").joinpath("fixtures").joinpath(FIXTURE_SETS[scenario])
            )
            text = fixture_file.read_text(encoding="utf-8")
        except (OSError, ModuleNotFoundError) as exc:
            raise ScenarioLoadError(f"fixture file unreadable for {scenario!r}") from exc
        try:
            fixture = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ScenarioLoadError(f"fixture file is not valid JSON for {scenario!r}") from exc
        if not isinstance(fixture, dict) or fixture.get("fixtureVersion") != scenario:
            raise ScenarioLoadError(f"fixture file version mismatch for {scenario!r}")
        return cls(fixture)

    @staticmethod
    def _build_index(state: dict[str, Any]) -> dict[str, dict[str, Any]]:
        index: dict[str, dict[str, Any]] = {}
        for scenario in state["scenarios"]:
            key = _tuple_key(scenario["match"])
            if key in index:
                raise ScenarioLoadError(f"duplicate scenario tuple {scenario['id']!r}")
            index[key] = scenario
        return index

    def post_json(self, path: str, payload: dict[str, Any]) -> RawResponse:
        if path not in (CHECK_PATH, BATCH_CHECK_PATH):
            raise SimulatedFailure(
                FailureCategory.SIMULATED_CONFIG,
                upstream_code="SIMULATED_PATH_UNKNOWN",
            )
        self._state["_callSeq"] += 1
        seq = self._state["_callSeq"]
        request_id = payload.get("requestId")
        if path == CHECK_PATH:
            scenario = self._lookup(payload)
            return self._respond_single(scenario, request_id, seq)
        return self._respond_batch(payload, request_id, seq)

    def _lookup(self, envelope: dict[str, Any]) -> dict[str, Any]:
        try:
            key = _tuple_key(envelope)
        except (KeyError, TypeError) as exc:
            raise _unknown_tuple_failure() from exc
        self._state["_observedTuples"].append(key)
        scenario = self._index.get(key)
        if scenario is None:
            raise _unknown_tuple_failure()
        return scenario

    @staticmethod
    def _decision_body(scenario: dict[str, Any], seq: int) -> dict[str, Any]:
        outcome = scenario["outcome"]
        body: dict[str, Any] = {
            "allowed": outcome["allowed"],
            "decisionId": f"{scenario['id']}-{seq}",
            "entitlementVersion": outcome["entitlementVersion"],
            "reasonCodes": list(outcome["reasonCodes"]),
            "evaluatedAt": outcome["evaluatedAt"],
        }
        policy_version = outcome["policyVersion"]
        if policy_version["mode"] == "string":
            body["policyVersion"] = policy_version["value"]
        elif policy_version["mode"] == "null":
            body["policyVersion"] = None
        return body

    def _respond_single(self, scenario: dict[str, Any], request_id: Any, seq: int) -> RawResponse:
        outcome = scenario["outcome"]
        if outcome["kind"] == "decision":
            body = self._decision_body(scenario, seq)
            body["requestId"] = (
                request_id if isinstance(request_id, str) and request_id else f"gen-{seq}"
            )
            return RawResponse(status=200, body=_json_bytes(body))
        return _failure_response(outcome, request_id)

    def _respond_batch(self, payload: dict[str, Any], request_id: Any, seq: int) -> RawResponse:
        top_id = request_id if isinstance(request_id, str) and request_id else f"gen-batch-{seq}"
        raw_items = payload.get("items")
        if not isinstance(raw_items, list):
            return _failure_response(
                {
                    "kind": "httpStatus",
                    "status": 400,
                    "code": "INVALID_REQUEST",
                },
                top_id,
            )
        items: list[dict[str, Any]] = []
        for envelope in raw_items:
            if not isinstance(envelope, dict):
                return _failure_response(
                    {
                        "kind": "httpStatus",
                        "status": 400,
                        "code": "INVALID_REQUEST",
                    },
                    top_id,
                )
            scenario = self._lookup(envelope)
            outcome = scenario["outcome"]
            if outcome["kind"] != "decision":
                # A dependency/auth/protocol failure inside a batch fails the
                # whole batch; no partial allow is ever emitted.
                return _failure_response(outcome, top_id)
            item_body = self._decision_body(scenario, seq)
            item_body["itemId"] = envelope["itemId"]
            items.append(item_body)
        return RawResponse(
            status=200,
            body=_json_bytes({"items": items, "requestId": top_id}),
        )

    def principals(self) -> dict[str, Principal]:
        out: dict[str, Principal] = {}
        for fixture_id, person in self._baseline["people"].items():
            departments = person["departmentIds"]
            confirmed = departments is not None
            out[fixture_id] = Principal(
                issuer=self._baseline["issuer"],
                sub=person["sub"],
                account_status=cast(AccountStatus, person["accountStatus"]),
                department_ids=() if departments is None else tuple(departments),
                departments_confirmed=confirmed,
                employee_id=person.get("employeeId"),
                display_name=person.get("displayName"),
                company_roles=tuple(person.get("companyRoles", [])),
            )
        return out

    def principal(self, fixture_id: str) -> Principal:
        try:
            return self.principals()[fixture_id]
        except KeyError as exc:
            raise ScenarioLoadError(f"unknown fixture principal id {fixture_id!r}") from exc

    def close(self) -> None:
        """No native handles exist for a recorded in-memory provider."""

    def reset(self) -> None:
        """Replace this instance's owned in-memory state with the fixed baseline.

        Other FixtureTransport instances are independent objects and are
        provably unaffected.
        """
        self._state = copy.deepcopy(self._baseline)
        self._state["_callSeq"] = 0
        self._state["_observedTuples"] = []
        self._index = self._build_index(self._state)

    def baseline_digest(self) -> dict[str, str]:
        sections = {
            "people": self._state["people"],
            "grants": self._state["grants"],
            "denies": self._state["denies"],
            "ownership": self._state["ownership"],
            "scenarios": self._state["scenarios"],
            "runtime": {
                "callSeq": self._state["_callSeq"],
                "observed": self._state["_observedTuples"],
            },
        }
        return {name: _digest(section) for name, section in sections.items()}


def _unknown_tuple_failure() -> SimulatedFailure:
    return SimulatedFailure(
        FailureCategory.SIMULATED_CONFIG,
        upstream_code="SIMULATED_TUPLE_UNKNOWN",
    )


def _tuple_key(match_or_envelope: dict[str, Any]) -> str:
    subject = match_or_envelope["subject"]
    resource = match_or_envelope["resource"]
    key = {
        "issuer": subject["issuer"],
        "sub": subject["sub"],
        "application": match_or_envelope.get("application"),
        "environment": match_or_envelope.get("environment"),
        "permission": match_or_envelope["permission"],
        "resourceType": resource["resourceType"],
        "resourceId": resource["resourceId"],
        "attributes": resource.get("attributes", {}),
    }
    return _canonical(key)


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False)


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _json_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False).encode("utf-8")


def _failure_response(outcome: dict[str, Any], request_id: Any) -> RawResponse:
    if outcome["kind"] == "timeout":
        raise _SimulatedTimeout()
    status = outcome["status"]
    body = {
        "code": outcome["code"],
        "message": outcome.get("message", "synthetic failure"),
        "requestId": (request_id if isinstance(request_id, str) and request_id else "gen-failure"),
    }
    return RawResponse(
        status=status,
        body=_json_bytes(body),
        retry_after_seconds=outcome.get("retryAfterSeconds"),
    )


class _SimulatedTimeout(SimulatedFailure):
    def __init__(self) -> None:
        super().__init__(FailureCategory.TRANSPORT, upstream_code="SIMULATED_TIMEOUT")
