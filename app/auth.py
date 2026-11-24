"""Mocked identity / role context (S2-IAM is out of scope).

The real IAM service is another work item, so this module implements the
same *shape*: the caller identity arrives through headers and is resolved
into an organisation + role set.  The download endpoint narrows the record
by ``(id, org_id)`` FIRST and only then checks the role, so a caller from
another organisation cannot even tell whether an id exists.
"""

from __future__ import annotations

from dataclasses import dataclass

ROLE_ADMIN = "admin"
ROLE_CONTRACT_MANAGER = "contract_manager"
ROLE_CONTRACT_VIEWER = "contract_viewer"

KNOWN_ROLES = frozenset(
    {ROLE_ADMIN, ROLE_CONTRACT_MANAGER, ROLE_CONTRACT_VIEWER}
)

VIEW_ROLES = frozenset({ROLE_ADMIN, ROLE_CONTRACT_MANAGER, ROLE_CONTRACT_VIEWER})
UPLOAD_ROLES = frozenset({ROLE_ADMIN, ROLE_CONTRACT_MANAGER})


@dataclass(frozen=True)
class AuthContext:
    org_id: str
    user_id: str
    roles: frozenset[str]

    def has_any_role(self, allowed: frozenset[str]) -> bool:
        return bool(self.roles & allowed)

    @property
    def can_view_contracts(self) -> bool:
        return self.has_any_role(VIEW_ROLES)

    @property
    def can_upload_contracts(self) -> bool:
        return self.has_any_role(UPLOAD_ROLES)


def parse_roles(raw: str | None) -> frozenset[str]:
    if not raw:
        return frozenset()
    parts = [item.strip().lower() for item in raw.replace(";", ",").split(",")]
    return frozenset(part for part in parts if part in KNOWN_ROLES)
