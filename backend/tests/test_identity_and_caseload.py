"""Four gaps between how an ASHA gets her patients here and how she does
in real life.

In life she is not given patients, she is given a place: she is selected
from the village she serves, and everyone living there is hers. Her list
comes from a household survey recorded in registers the ANM issues, and a
pregnant woman is registered with an RCH number printed on the MCP card she
carries herself.

Here, ownership was authorship -- whoever typed the name owned the person
forever. That models the survey step correctly and left out the
institutional half:

  1. Nothing could be handed over. ASHAs leave, go on maternity leave, get
     replaced; their patients became unreachable, because the list endpoint
     filters by worker_id. A supervisor could read the names and do nothing
     about any of them.
  2. Village was free text, so "Wagholi" and "wagholi" were two villages.
  3. Nothing was unique, so the same woman could be registered twice and
     nothing would ever know. This is how duplicates get into HMIS.
  4. Nothing flowed downward. The ANM holds the RCH register in life; here
     she could only watch.
"""
from fastapi.testclient import TestClient

from app.core.security import hash_pin
from app.db.models.patient import Patient
from app.db.models.worker import Worker
from app.db.session import SessionLocal, backfill_identity
from app.main import app
from app.services import identity
from scripts.seed_synthetic_data import seed_demo_fixtures

HER_SUB_CENTRE = "SC-PUNE-01"


def _client() -> TestClient:
    client = TestClient(app)
    db = SessionLocal()
    try:
        seed_demo_fixtures(db)
        for phone, name, sub in (
            ("9444400001", "Kavita Receiving", HER_SUB_CENTRE),
            ("9444400002", "Sunita Leaving", HER_SUB_CENTRE),
            ("9444400003", "Outside ASHA", "SC-ELSEWHERE-09"),
        ):
            if db.query(Worker).filter(Worker.phone == phone).first() is None:
                db.add(
                    Worker(
                        name=name, phone=phone, pin_hash=hash_pin("1234"),
                        role="asha", sub_centre_id=sub,
                    )
                )
        db.commit()
    finally:
        db.close()
    backfill_identity()
    return client


def _headers(client: TestClient, phone: str) -> dict:
    resp = client.post("/api/v1/auth/login", json={"phone": phone, "pin": "1234"})
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


def _worker_id(phone: str) -> str:
    db = SessionLocal()
    try:
        return db.query(Worker).filter(Worker.phone == phone).first().worker_id
    finally:
        db.close()


# ── Formal identifiers ──────────────────────────────────────────────────

def test_every_worker_gets_a_readable_code():
    """ASHA-PUNE-01-007 reads aloud over a bad phone line. A UUID does
    not, and an ANM working out which of her workers filed a referral has
    only the phone line."""
    _client()
    db = SessionLocal()
    try:
        workers = db.query(Worker).all()
        assert workers
        missing = [w.name for w in workers if not w.worker_code]
        assert not missing, f"no code for {missing}"
        codes = [w.worker_code for w in workers]
        assert len(codes) == len(set(codes)), "two workers share a code"

        sunita = db.query(Worker).filter(Worker.phone == "9999999999").first()
        assert sunita.worker_code.startswith("ASHA-PUNE-01-")
        admin = db.query(Worker).filter(Worker.phone == "9999999903").first()
        # No sub-centre, so no invented area in the code.
        assert admin.worker_code.startswith("ADMIN-")
    finally:
        db.close()


def test_a_code_survives_a_second_backfill():
    """It appears on paperwork. A code that changed would make last
    month's referral slips refer to nobody."""
    _client()
    db = SessionLocal()
    try:
        before = {w.worker_id: w.worker_code for w in db.query(Worker).all()}
    finally:
        db.close()

    backfill_identity()

    db = SessionLocal()
    try:
        after = {w.worker_id: w.worker_code for w in db.query(Worker).all()}
    finally:
        db.close()
    assert before == after


def test_an_rch_number_is_accepted_and_must_be_twelve_digits():
    with _client() as client:
        headers = _headers(client, "9999999999")
        good = client.post(
            "/api/v1/patients",
            headers=headers,
            json={"name": "Rch Good", "rch_number": "1234 5678 9012", "phone": "9333300001"},
        )
        assert good.status_code == 201, good.text
        assert good.json()["rch_number"] == "123456789012", "spacing should be normalised away"

        bad = client.post(
            "/api/v1/patients",
            headers=headers,
            json={"name": "Rch Bad", "rch_number": "12345", "phone": "9333300002"},
        )
        assert bad.status_code == 422, bad.text


def test_an_rch_number_cannot_be_used_twice_anywhere():
    """Issued by the health system and unique across the country, so a
    match in another district is still the same woman."""
    with _client() as client:
        mine = _headers(client, "9999999999")
        far = _headers(client, "9444400003")  # a different sub-centre

        first = client.post(
            "/api/v1/patients",
            headers=mine,
            json={"name": "Rch First", "rch_number": "222233334444", "phone": "9333300003"},
        )
        assert first.status_code == 201, first.text

        second = client.post(
            "/api/v1/patients",
            headers=far,
            json={"name": "Rch Second", "rch_number": "222233334444", "phone": "9333300004"},
        )
        assert second.status_code == 409, second.text
        assert "MCP card" in second.json()["detail"]


# ── Duplicate detection without decrypting anything ─────────────────────

def test_the_same_woman_cannot_be_registered_twice_in_one_sub_centre():
    """Two ASHAs in neighbouring hamlets, one pregnant woman. The phone
    column is AES-GCM with a random nonce, so equality was impossible
    until the blind index existed."""
    with _client() as client:
        first = client.post(
            "/api/v1/patients",
            headers=_headers(client, "9999999999"),
            json={"name": "Shared Woman", "phone": "9876511111"},
        )
        assert first.status_code == 201, first.text

        # Same number, different ASHA, same sub-centre, written differently.
        second = client.post(
            "/api/v1/patients",
            headers=_headers(client, "9444400001"),
            json={"name": "Shared Woman Again", "phone": "+91 98765 11111"},
        )
        assert second.status_code == 409, second.text


def test_a_shared_number_in_another_sub_centre_is_allowed():
    """A phone number is not an identity -- households share one, numbers
    get reissued, a daughter uses her mother's. Matching district-wide
    would block real registrations."""
    with _client() as client:
        assert client.post(
            "/api/v1/patients",
            headers=_headers(client, "9999999999"),
            json={"name": "Local Woman", "phone": "9876522222"},
        ).status_code == 201
        assert client.post(
            "/api/v1/patients",
            headers=_headers(client, "9444400003"),
            json={"name": "Faraway Woman", "phone": "9876522222"},
        ).status_code == 201


def test_the_blind_index_is_not_the_phone_number():
    assert identity.phone_index("9876543210") != "9876543210"
    # Deterministic, or it could not be compared at all...
    assert identity.phone_index("9876543210") == identity.phone_index("+91 98765 43210")
    # ...and different numbers must not collide.
    assert identity.phone_index("9876543210") != identity.phone_index("9876543211")


# ── Village as a place ──────────────────────────────────────────────────

def test_case_and_spacing_do_not_make_a_new_village():
    assert identity.village_code(" Wagholi ") == identity.village_code("wagholi") == "WAGHOLI"


def test_khurd_and_budruk_stay_two_villages():
    """Two real villages of a pair, a naming convention across
    Maharashtra. An algorithm helpful about brackets would merge two
    populations into one row on a district heatmap."""
    assert identity.village_code("Wagholi (Kh)") != identity.village_code("Wagholi (Bk)")


def test_a_registered_patient_gets_a_village_key_and_her_own_sub_centre():
    with _client() as client:
        created = client.post(
            "/api/v1/patients",
            headers=_headers(client, "9999999999"),
            json={"name": "Placed Woman", "village": " wagholi ", "phone": "9876533333"},
        )
        assert created.status_code == 201, created.text

        db = SessionLocal()
        try:
            patient = db.query(Patient).filter(Patient.patient_id == created.json()["id"]).first()
            assert patient.village_code == "WAGHOLI"
            assert patient.village == "wagholi", "display keeps what she typed"
            assert patient.sub_centre_id == HER_SUB_CENTRE
        finally:
            db.close()


# ── Handover ────────────────────────────────────────────────────────────

def test_an_anm_can_hand_a_departed_ashas_caseload_to_another():
    """The gap that mattered. Until now those patients were unreachable:
    the list endpoint filters by worker_id, so nobody else could see them
    and no visit could be recorded against them."""
    leaving, receiving = _worker_id("9444400002"), _worker_id("9444400001")
    with _client() as client:
        leaving_headers = _headers(client, "9444400002")
        for i in range(3):
            assert client.post(
                "/api/v1/patients",
                headers=leaving_headers,
                json={"name": f"Handover Patient {i}", "phone": f"987654400{i}"},
            ).status_code == 201

        anm = _headers(client, "9999999901")
        resp = client.post(
            f"/api/v1/patients/caseload/{leaving}/reassign",
            headers=anm,
            json={"to_worker_id": receiving, "reason": "Sunita has left the post; Kavita covers those streets now."},
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["moved"] >= 3

        # Gone from one list, present on the other -- and recordable again.
        old_list = client.get(f"/api/v1/patients/{leaving}", headers=anm).json()["patients"]
        new_list = client.get(f"/api/v1/patients/{receiving}", headers=anm).json()["patients"]
        assert not any(p["name"].startswith("Handover Patient") for p in old_list)
        assert sum(1 for p in new_list if p["name"].startswith("Handover Patient")) >= 3


def test_a_reassigned_patient_keeps_her_own_sub_centre():
    """She has not moved village because somebody else changed jobs."""
    receiving = _worker_id("9444400001")
    with _client() as client:
        created = client.post(
            "/api/v1/patients",
            headers=_headers(client, "9999999999"),
            json={"name": "Stays Put", "village": "Wagholi", "phone": "9876544444"},
        ).json()

        resp = client.post(
            f"/api/v1/patients/{created['id']}/reassign",
            headers=_headers(client, "9999999901"),
            json={"to_worker_id": receiving, "reason": "Redistributing the load after a resignation."},
        )
        assert resp.status_code == 200, resp.text

        db = SessionLocal()
        try:
            patient = db.query(Patient).filter(Patient.patient_id == created["id"]).first()
            assert patient.worker_id == receiving
            assert patient.sub_centre_id == HER_SUB_CENTRE
        finally:
            db.close()


def test_a_caseload_cannot_be_moved_out_of_the_sub_centre():
    leaving, outside = _worker_id("9444400002"), _worker_id("9444400003")
    with _client() as client:
        resp = client.post(
            f"/api/v1/patients/caseload/{leaving}/reassign",
            headers=_headers(client, "9999999901"),
            json={"to_worker_id": outside, "reason": "Trying to reach into the next block."},
        )
        assert resp.status_code == 403, resp.text


def test_an_asha_cannot_reassign_anybody():
    leaving, receiving = _worker_id("9444400002"), _worker_id("9444400001")
    with _client() as client:
        resp = client.post(
            f"/api/v1/patients/caseload/{leaving}/reassign",
            headers=_headers(client, "9999999999"),
            json={"to_worker_id": receiving, "reason": "Helping myself to a colleague's list."},
        )
        assert resp.status_code == 403, resp.text


def test_a_handover_needs_a_reason():
    """Left, on leave, or replaced are different facts about a real
    person's employment, and six months later the audit log is the only
    place anybody can find out which."""
    leaving, receiving = _worker_id("9444400002"), _worker_id("9444400001")
    with _client() as client:
        resp = client.post(
            f"/api/v1/patients/caseload/{leaving}/reassign",
            headers=_headers(client, "9999999901"),
            json={"to_worker_id": receiving, "reason": "x"},
        )
        assert resp.status_code == 422, resp.text


def test_a_caseload_cannot_be_handed_to_an_unapproved_account():
    """Handing it to somebody who cannot log in is the same as losing it,
    and it would look like it worked."""
    leaving = _worker_id("9444400002")
    with _client() as client:
        pending = client.post(
            "/api/v1/auth/register",
            json={"name": "Not Yet Approved", "phone": "9444400009", "pin": "5150",
                  "role": "asha", "sub_centre_id": HER_SUB_CENTRE},
        ).json()
        resp = client.post(
            f"/api/v1/patients/caseload/{leaving}/reassign",
            headers=_headers(client, "9999999901"),
            json={"to_worker_id": pending["worker_id"], "reason": "She has not been approved yet."},
        )
        assert resp.status_code == 400, resp.text


# ── Work flowing downward ───────────────────────────────────────────────

def test_an_anm_can_register_a_patient_to_one_of_her_ashas():
    """In life the ANM holds the sub-centre's RCH register and hands the
    line-list down. Before this she could only watch."""
    asha = _worker_id("9444400001")
    with _client() as client:
        resp = client.post(
            "/api/v1/patients",
            headers=_headers(client, "9999999901"),
            json={"name": "Handed Down", "phone": "9876555555", "worker_id": asha},
        )
        assert resp.status_code == 201, resp.text

        listed = client.get(f"/api/v1/patients/{asha}", headers=_headers(client, "9999999901")).json()
        assert any(p["name"] == "Handed Down" for p in listed["patients"])


def test_an_anm_must_name_the_worker():
    """A patient filed to an ANM is a patient nobody visits: she does not
    do home visits, and the list endpoint is keyed on the ASHA."""
    with _client() as client:
        resp = client.post(
            "/api/v1/patients",
            headers=_headers(client, "9999999901"),
            json={"name": "Nobody's Patient", "phone": "9876566666"},
        )
        assert resp.status_code == 400, resp.text


def test_an_asha_cannot_file_a_patient_onto_a_colleague():
    """A worker who could do that could also quietly empty her own list."""
    other = _worker_id("9444400001")
    with _client() as client:
        resp = client.post(
            "/api/v1/patients",
            headers=_headers(client, "9999999999"),
            json={"name": "Not Mine To Give", "phone": "9876577777", "worker_id": other},
        )
        assert resp.status_code == 403, resp.text


def test_an_anm_cannot_file_a_patient_outside_her_sub_centre():
    outside = _worker_id("9444400003")
    with _client() as client:
        resp = client.post(
            "/api/v1/patients",
            headers=_headers(client, "9999999901"),
            json={"name": "Wrong Block", "phone": "9876588888", "worker_id": outside},
        )
        assert resp.status_code == 403, resp.text
