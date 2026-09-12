"""One-time backfill: encrypt already-stored plaintext Patient.name/phone and
Visit.transcript/structured_json in an existing dev DB (NFR-SC1) -- the same
kind of raw-SQL backfill as fix_asha_names.py, just for encryption instead of
names.

Run this ONCE, after ENCRYPTION_KEY is set in .env (see
scripts/generate_encryption_key.py) and before the app is relied on to show
correct data -- until this runs, the app will display existing rows exactly
as before (decrypt_field() passes through anything without the "enc:v1:"
marker), so nothing breaks, but nothing is protected yet either.

Safe to re-run: any value that already carries the "enc:v1:" marker is left
alone, so running it twice just does nothing the second time.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.encryption import _MARKER, encrypt_field  # noqa: E402
from app.db.session import engine  # noqa: E402


def _encrypt_column(conn, table: str, pk: str, column: str) -> int:
    rows = conn.exec_driver_sql(f"SELECT {pk}, {column} FROM {table}").fetchall()
    updated = 0
    for row_id, value in rows:
        if value is None or value.startswith(_MARKER):
            continue
        conn.exec_driver_sql(
            f"UPDATE {table} SET {column} = ? WHERE {pk} = ?",
            (encrypt_field(value), row_id),
        )
        updated += 1
    return updated


def main() -> None:
    with engine.connect() as conn:
        n_names = _encrypt_column(conn, "patients", "patient_id", "name")
        n_phones = _encrypt_column(conn, "patients", "patient_id", "phone")
        n_transcripts = _encrypt_column(conn, "visits", "visit_id", "transcript")
        n_structured = _encrypt_column(conn, "visits", "visit_id", "structured_json")
        conn.commit()
    print(
        f"Encrypted {n_names} patient names, {n_phones} patient phone numbers, "
        f"{n_transcripts} visit transcripts, {n_structured} structured visit records."
    )


if __name__ == "__main__":
    main()
