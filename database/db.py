"""SQLite access layer: connection, schema, seeding, ingredient CRUD, import/export, sessions."""
from __future__ import annotations

import csv
import io
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from pydantic import ValidationError

import config
from models.ingredient import EvidenceSource, HealthEffect, Ingredient, SafetyLimit


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def get_connection(db_path: Optional[Path | str] = None) -> sqlite3.Connection:
    """Open a connection with foreign keys on and dict-like rows."""
    path = Path(db_path) if db_path else config.DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(conn: sqlite3.Connection, seed: bool = True) -> None:
    """Create tables and (if the ingredient table is empty) load the seed file."""
    conn.executescript(config.SCHEMA_PATH.read_text(encoding="utf-8"))
    conn.commit()
    if seed:
        count = conn.execute("SELECT COUNT(*) FROM ingredients").fetchone()[0]
        if count == 0 and config.SEED_PATH.exists():
            load_seed(conn, config.SEED_PATH)


def load_seed(conn: sqlite3.Connection, path: Path | str) -> int:
    """Load a JSON list of ingredient records. Seed records are always validated."""
    records = json.loads(Path(path).read_text(encoding="utf-8"))
    for rec in records:
        upsert_ingredient(conn, Ingredient.model_validate(rec))
    return len(records)


# ---------------------------------------------------------------- ingredients
def upsert_ingredient(conn: sqlite3.Connection, ing: Ingredient, ingredient_id: Optional[int] = None) -> int:
    """Insert or update an ingredient and replace its child rows. Returns the ingredient id."""
    now = _now()
    iid = ingredient_id or ing.id
    if iid is None:
        row = conn.execute("SELECT id FROM ingredients WHERE canonical_name = ?", (ing.canonical_name,)).fetchone()
        iid = row["id"] if row else None
    values = (
        ing.canonical_name, ing.ins_number, ing.e_number, ing.category, ing.purpose, ing.hazard_summary,
        ing.evidence_level, ing.evidence_limitations, ing.permitted_use_notes, ing.allergen_notes,
        ing.precautions, ing.verification_status, ing.reviewed_on,
    )
    with conn:
        if iid is None:
            cur = conn.execute(
                """INSERT INTO ingredients (canonical_name, ins_number, e_number, category, purpose,
                   hazard_summary, evidence_level, evidence_limitations, permitted_use_notes,
                   allergen_notes, precautions, verification_status, reviewed_on, created_at, updated_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                values + (now, now),
            )
            iid = cur.lastrowid
        else:
            conn.execute(
                """UPDATE ingredients SET canonical_name=?, ins_number=?, e_number=?, category=?, purpose=?,
                   hazard_summary=?, evidence_level=?, evidence_limitations=?, permitted_use_notes=?,
                   allergen_notes=?, precautions=?, verification_status=?, reviewed_on=?, updated_at=?
                   WHERE id=?""",
                values + (now, iid),
            )
            # Children first (effects/limits reference sources).
            for table in ("health_effects", "safety_limits", "synonyms", "evidence_sources"):
                conn.execute(f"DELETE FROM {table} WHERE ingredient_id = ?", (iid,))

        for syn in ing.synonyms:
            if syn.lower() != ing.canonical_name.lower():
                conn.execute("INSERT OR IGNORE INTO synonyms (ingredient_id, synonym) VALUES (?,?)", (iid, syn))

        source_id_by_url: dict[str, int] = {}
        seen: set[tuple[str, str]] = set()
        for s in ing.sources:
            key = (s.url, s.claim_supported)
            if key in seen:
                continue
            seen.add(key)
            cur = conn.execute(
                """INSERT INTO evidence_sources (ingredient_id, title, publisher, url, publication_date,
                   retrieval_date, claim_supported) VALUES (?,?,?,?,?,?,?)""",
                (iid, s.title, s.publisher, s.url, s.publication_date, s.retrieval_date, s.claim_supported),
            )
            source_id_by_url.setdefault(s.url, cur.lastrowid)

        for e in ing.health_effects:
            conn.execute(
                """INSERT INTO health_effects (ingredient_id, effect, timeframe, body_system, exposure_route,
                   evidence_type, evidence_level, conditions, source_id) VALUES (?,?,?,?,?,?,?,?,?)""",
                (iid, e.effect, e.timeframe, e.body_system, e.exposure_route, e.evidence_type,
                 e.evidence_level, e.conditions, source_id_by_url.get(e.source_url or "")),
            )
        for lim in ing.safety_limits:
            conn.execute(
                """INSERT INTO safety_limits (ingredient_id, limit_type, value_mg_per_kg_bw, expressed_as,
                   authority, jurisdiction, source_id, verification_status, reviewed_on, notes)
                   VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (iid, lim.limit_type, lim.value_mg_per_kg_bw, lim.expressed_as, lim.authority,
                 lim.jurisdiction, source_id_by_url.get(lim.source_url or ""), lim.verification_status,
                 lim.reviewed_on, lim.notes),
            )
    return int(iid)


def _row_to_ingredient(conn: sqlite3.Connection, row: sqlite3.Row) -> Ingredient:
    iid = row["id"]
    synonyms = [r["synonym"] for r in conn.execute(
        "SELECT synonym FROM synonyms WHERE ingredient_id=? ORDER BY synonym", (iid,))]
    src_rows = conn.execute("SELECT * FROM evidence_sources WHERE ingredient_id=? ORDER BY id", (iid,)).fetchall()
    url_by_id = {r["id"]: r["url"] for r in src_rows}
    sources = [EvidenceSource(title=r["title"], publisher=r["publisher"], url=r["url"],
                              publication_date=r["publication_date"], retrieval_date=r["retrieval_date"],
                              claim_supported=r["claim_supported"]) for r in src_rows]
    effects = [HealthEffect(effect=r["effect"], timeframe=r["timeframe"], body_system=r["body_system"],
                            exposure_route=r["exposure_route"], evidence_type=r["evidence_type"],
                            evidence_level=r["evidence_level"], conditions=r["conditions"],
                            source_url=url_by_id.get(r["source_id"]))
               for r in conn.execute("SELECT * FROM health_effects WHERE ingredient_id=? ORDER BY id", (iid,))]
    limits = [SafetyLimit(limit_type=r["limit_type"], value_mg_per_kg_bw=r["value_mg_per_kg_bw"],
                          expressed_as=r["expressed_as"], authority=r["authority"],
                          jurisdiction=r["jurisdiction"], source_url=url_by_id.get(r["source_id"]),
                          verification_status=r["verification_status"], reviewed_on=r["reviewed_on"],
                          notes=r["notes"])
              for r in conn.execute("SELECT * FROM safety_limits WHERE ingredient_id=? ORDER BY id", (iid,))]
    return Ingredient(
        id=iid, canonical_name=row["canonical_name"], synonyms=synonyms, ins_number=row["ins_number"],
        e_number=row["e_number"], category=row["category"], purpose=row["purpose"],
        hazard_summary=row["hazard_summary"], evidence_level=row["evidence_level"],
        evidence_limitations=row["evidence_limitations"], permitted_use_notes=row["permitted_use_notes"],
        allergen_notes=row["allergen_notes"], precautions=row["precautions"],
        verification_status=row["verification_status"], reviewed_on=row["reviewed_on"],
        sources=sources, health_effects=effects, safety_limits=limits,
    )


def get_ingredient(conn: sqlite3.Connection, ingredient_id: int) -> Optional[Ingredient]:
    row = conn.execute("SELECT * FROM ingredients WHERE id=?", (ingredient_id,)).fetchone()
    return _row_to_ingredient(conn, row) if row else None


def get_all_ingredients(conn: sqlite3.Connection) -> list[Ingredient]:
    rows = conn.execute("SELECT * FROM ingredients ORDER BY canonical_name COLLATE NOCASE").fetchall()
    return [_row_to_ingredient(conn, r) for r in rows]


def delete_ingredient(conn: sqlite3.Connection, ingredient_id: int) -> None:
    with conn:
        conn.execute("DELETE FROM ingredients WHERE id=?", (ingredient_id,))


# -------------------------------------------------------------- import/export
def export_json(conn: sqlite3.Connection) -> str:
    data = [i.model_dump(exclude={"id"}) for i in get_all_ingredients(conn)]
    return json.dumps(data, indent=2, ensure_ascii=False)


CSV_COLUMNS = ["canonical_name", "synonyms", "e_number", "ins_number", "category", "purpose",
               "hazard_summary", "evidence_level", "verification_status", "reviewed_on", "source_urls"]


def export_csv(conn: sqlite3.Connection) -> str:
    """Flat summary export. Effects/limits are only in the JSON export."""
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=CSV_COLUMNS)
    w.writeheader()
    for i in get_all_ingredients(conn):
        w.writerow({
            "canonical_name": i.canonical_name, "synonyms": ";".join(i.synonyms),
            "e_number": i.e_number or "", "ins_number": i.ins_number or "", "category": i.category,
            "purpose": i.purpose, "hazard_summary": i.hazard_summary or "",
            "evidence_level": i.evidence_level, "verification_status": i.verification_status,
            "reviewed_on": i.reviewed_on or "", "source_urls": ";".join(s.url for s in i.sources),
        })
    return buf.getvalue()


def import_json(conn: sqlite3.Connection, text: str, keep_status: bool = False) -> tuple[int, list[str]]:
    """Import JSON records. By default every imported record becomes 'unverified'."""
    errors: list[str] = []
    try:
        records = json.loads(text)
    except json.JSONDecodeError as exc:
        return 0, [f"Invalid JSON: {exc}"]
    if not isinstance(records, list):
        return 0, ["Top-level JSON value must be a list of ingredient records."]
    ok = 0
    for n, rec in enumerate(records, start=1):
        try:
            if isinstance(rec, dict) and not keep_status:
                rec = {**rec, "verification_status": "unverified", "reviewed_on": None}
                for lim in rec.get("safety_limits", []) or []:
                    if isinstance(lim, dict):
                        lim["verification_status"] = "unverified"
                        lim["reviewed_on"] = None
            upsert_ingredient(conn, Ingredient.model_validate(rec))
            ok += 1
        except (ValidationError, sqlite3.DatabaseError, TypeError) as exc:
            errors.append(f"Record {n}: {str(exc).splitlines()[0] if str(exc) else exc.__class__.__name__}")
    return ok, errors


def import_csv(conn: sqlite3.Connection, text: str) -> tuple[int, list[str]]:
    """Import flat CSV rows. Existing records keep their effects/limits; all rows become 'unverified'."""
    errors: list[str] = []
    ok = 0
    existing = {i.canonical_name.lower(): i for i in get_all_ingredients(conn)}
    for n, row in enumerate(csv.DictReader(io.StringIO(text)), start=2):
        try:
            name = (row.get("canonical_name") or "").strip()
            base = existing.get(name.lower())
            data = base.model_dump() if base else {}
            data.update({
                "canonical_name": name,
                "synonyms": [s for s in (row.get("synonyms") or "").split(";") if s.strip()],
                "e_number": row.get("e_number") or None, "ins_number": row.get("ins_number") or None,
                "category": row.get("category") or "unspecified", "purpose": row.get("purpose") or "",
                "hazard_summary": row.get("hazard_summary") or None,
                "evidence_level": row.get("evidence_level") or "not_assessed",
                "verification_status": "unverified", "reviewed_on": None,
            })
            if not base:
                data["sources"] = [{"title": "Imported (unverified)", "publisher": "Unknown", "url": u.strip(),
                                    "claim_supported": "Not specified"}
                                   for u in (row.get("source_urls") or "").split(";") if u.strip()]
            upsert_ingredient(conn, Ingredient.model_validate(data))
            ok += 1
        except (ValidationError, sqlite3.DatabaseError) as exc:
            errors.append(f"Row {n}: {str(exc).splitlines()[0]}")
    return ok, errors


# ------------------------------------------------------------------- sessions
def save_session(conn: sqlite3.Connection, product_name: str, report: dict, findings: list[dict]) -> int:
    with conn:
        cur = conn.execute(
            "INSERT INTO analysis_sessions (created_at, product_name, report_json) VALUES (?,?,?)",
            (_now(), product_name or None, json.dumps(report, ensure_ascii=False)),
        )
        sid = cur.lastrowid
        for f in findings:
            conn.execute(
                """INSERT INTO analysis_findings (session_id, ingredient_id, input_name, match_type,
                   confidence, risk_category) VALUES (?,?,?,?,?,?)""",
                (sid, f.get("ingredient_id"), f["input_name"], f["match_type"], f.get("confidence"),
                 f.get("risk_category")),
            )
    return int(sid)


def list_sessions(conn: sqlite3.Connection, limit: int = 50) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT id, created_at, product_name FROM analysis_sessions ORDER BY id DESC LIMIT ?", (limit,)
    ).fetchall()


def get_session_report(conn: sqlite3.Connection, session_id: int) -> Optional[dict]:
    row = conn.execute("SELECT report_json FROM analysis_sessions WHERE id=?", (session_id,)).fetchone()
    return json.loads(row["report_json"]) if row else None


def delete_session(conn: sqlite3.Connection, session_id: int) -> None:
    with conn:
        conn.execute("DELETE FROM analysis_sessions WHERE id=?", (session_id,))


def delete_all_sessions(conn: sqlite3.Connection) -> None:
    with conn:
        conn.execute("DELETE FROM analysis_sessions")


def save_ai_summary(conn: sqlite3.Connection, session_id: int, summary: str, model: Optional[str]) -> None:
    with conn:
        conn.execute("INSERT INTO ai_summaries (session_id, model, summary, created_at) VALUES (?,?,?,?)",
                     (session_id, model, summary, _now()))


if __name__ == "__main__":  # python -m database.db  -> initialise the database
    c = get_connection()
    init_db(c)
    print(f"Database ready at {config.DB_PATH} with {c.execute('SELECT COUNT(*) FROM ingredients').fetchone()[0]} ingredients.")
