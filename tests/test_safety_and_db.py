import json

import pytest

from database import db
from services.safety_service import check_toxic_exposure, load_emergency_resources


@pytest.mark.parametrize("text", [
    "my toddler swallowed the whole packet", "I think I took an overdose", "chest pain after eating",
    "difficulty breathing and swollen throat", "suspected poisoning"])
def test_toxic_exposure_triggers_urgent_guidance(text):
    a = check_toxic_exposure(text)
    assert a and a.triggered
    joined = " ".join(a.guidance).lower()
    assert "emergency services" in joined and "do not induce vomiting" in joined
    assert "no prediction" in joined


@pytest.mark.parametrize("text", ["", None, "I like orange juice", "reading the label"])
def test_no_alert_for_benign_text(text):
    assert check_toxic_exposure(text) is None


def test_emergency_resources_never_invented(tmp_path, monkeypatch):
    import config
    monkeypatch.setattr(config, "EMERGENCY_RESOURCES_FILE", tmp_path / "missing.json")
    assert load_emergency_resources() == {}


def test_seed_loads_and_is_all_unverified(conn):
    ings = db.get_all_ingredients(conn)
    assert len(ings) >= 8
    assert all(i.verification_status == "unverified" for i in ings)
    assert all(l.verification_status == "unverified" for i in ings for l in i.safety_limits)


def test_import_forces_unverified(conn):
    data = json.loads(db.export_json(conn))
    data[0]["canonical_name"] = "Test additive"
    data[0]["verification_status"] = "reviewed"
    data[0]["reviewed_on"] = "2026-01-01"
    n, errs = db.import_json(conn, json.dumps([data[0]]))
    assert n == 1 and not errs
    imported = next(i for i in db.get_all_ingredients(conn) if i.canonical_name == "Test additive")
    assert imported.verification_status == "unverified"


def test_import_reports_bad_records(conn):
    n, errs = db.import_json(conn, json.dumps([{"canonical_name": ""}, {"canonical_name": "ok"}]))
    assert n == 1 and len(errs) == 1


def test_csv_roundtrip_keeps_effects(conn):
    before = {i.canonical_name: len(i.health_effects) for i in db.get_all_ingredients(conn)}
    n, errs = db.import_csv(conn, db.export_csv(conn))
    after = {i.canonical_name: len(i.health_effects) for i in db.get_all_ingredients(conn)}
    assert not errs and n == len(before) and before == after


def test_sessions_save_list_delete(conn):
    sid = db.save_session(conn, "P", {"ingredients": [], "unmatched": []},
                          [{"input_name": "x", "match_type": "none"}])
    assert db.list_sessions(conn)[0]["id"] == sid
    db.delete_all_sessions(conn)
    assert db.list_sessions(conn) == []
    assert conn.execute("SELECT COUNT(*) FROM analysis_findings").fetchone()[0] == 0  # cascade


def test_foreign_keys_enforced(conn):
    import sqlite3
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO synonyms (ingredient_id, synonym) VALUES (9999, 'x')")
