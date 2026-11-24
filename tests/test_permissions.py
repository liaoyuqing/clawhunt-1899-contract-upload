"""Permission boundaries: cross-organisation -> 404, no role -> 403."""

from __future__ import annotations

from tests.fixtures import PDF_BYTES


def _upload(client, headers):
    response = client.post(
        "/api/doc/contracts",
        files={"file": ("contract.pdf", PDF_BYTES, "application/pdf")},
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return response.json()["contract_id"]


def test_cross_org_404_is_byte_identical_to_unknown_id_404(
    client, headers, other_org_headers
):
    """A foreign contract and a random id must be indistinguishable."""
    contract_id = _upload(client, headers)
    cross = client.get(f"/api/doc/contracts/{contract_id}/file", headers=other_org_headers)
    unknown = client.get("/api/doc/contracts/11111111-2222-3333-4444-555555555555/file", headers=headers)
    assert cross.status_code == 404
    assert unknown.status_code == 404
    assert cross.content == unknown.content
    assert cross.headers.get("content-type") == unknown.headers.get("content-type")


def test_same_org_without_view_permission_gets_403(client, headers):
    """A caller of the same org without the view role gets 403."""
    contract_id = _upload(client, headers)
    no_role = {
        "X-Org-Id": "org-0001",
        "X-User-Id": "user-nobody",
        "X-Roles": "billing_only",
    }
    response = client.get(f"/api/doc/contracts/{contract_id}/file", headers=no_role)
    assert response.status_code == 403, response.text


def test_upload_without_upload_permission_gets_403(client, headers):
    """A viewer may download but not upload."""
    viewer = {
        "X-Org-Id": "org-0001",
        "X-User-Id": "user-viewer",
        "X-Roles": "contract_viewer",
    }
    response = client.post(
        "/api/doc/contracts",
        files={"file": ("contract.pdf", PDF_BYTES, "application/pdf")},
        headers=viewer,
    )
    assert response.status_code == 403, response.text
