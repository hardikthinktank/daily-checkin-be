"""Patient/drug/actor provisioning -- not one of the spec's numbered test
cases, but a real gap if missing: there was previously no way to create a
patient through the API at all, only via the seed scripts.
"""
from __future__ import annotations

import uuid


async def test_create_drug_then_create_patient_against_it(client):
    drug_resp = await client.post("/drugs", json={"name": f"Etanercept-{uuid.uuid4().hex[:8]}", "is_biologic_or_similar": True})
    assert drug_resp.status_code == 201
    drug_id = drug_resp.json()["id"]

    patient_resp = await client.post(
        "/patients",
        json={
            "name": "New Patient",
            "mrn": f"MRN-{uuid.uuid4().hex[:10]}",
            "diagnosis": "Rheumatoid arthritis",
            "current_drug_id": drug_id,
        },
    )
    assert patient_resp.status_code == 201
    body = patient_resp.json()
    assert body["current_drug"]["id"] == drug_id
    assert body["enrollment_date"] is not None  # defaulted to today

    listed = await client.get("/patients")
    assert any(p["id"] == body["id"] for p in listed.json())


async def test_create_patient_with_unknown_drug_id_returns_404(client):
    resp = await client.post(
        "/patients",
        json={
            "name": "X",
            "mrn": f"MRN-{uuid.uuid4().hex[:10]}",
            "diagnosis": "RA",
            "current_drug_id": str(uuid.uuid4()),
        },
    )
    assert resp.status_code == 404
    assert resp.json()["error_code"] == "drug_not_found"


async def test_duplicate_mrn_returns_409(client, biologic_drug):
    mrn = f"MRN-{uuid.uuid4().hex[:10]}"
    payload = {"name": "A", "mrn": mrn, "diagnosis": "RA", "current_drug_id": str(biologic_drug.id)}
    first = await client.post("/patients", json=payload)
    assert first.status_code == 201

    second = await client.post("/patients", json={**payload, "name": "B"})
    assert second.status_code == 409
    assert second.json()["error_code"] == "duplicate_mrn"


async def test_duplicate_drug_name_returns_409(client):
    name = f"Drug-{uuid.uuid4().hex[:8]}"
    first = await client.post("/drugs", json={"name": name, "is_biologic_or_similar": False})
    assert first.status_code == 201
    second = await client.post("/drugs", json={"name": name, "is_biologic_or_similar": True})
    assert second.status_code == 409
    assert second.json()["error_code"] == "duplicate_drug_name"


async def test_create_actor(client):
    resp = await client.post(
        "/actors", json={"display_name": "New Care Manager", "actor_type": "human", "role": "care_manager"}
    )
    assert resp.status_code == 201
    assert resp.json()["actor_type"] == "human"

    listed = await client.get("/actors")
    assert any(a["id"] == resp.json()["id"] for a in listed.json())
