"""The Alembic baseline must describe the same schema the models do.

A migration set that has drifted from the models is worse than none: it
succeeds, and then the application fails on a column the migration never
made. This compares the two directly rather than trusting that whoever
last changed a model remembered to generate a revision.
"""
import subprocess
import sys
from pathlib import Path

from sqlalchemy import create_engine, inspect

import app.db.models  # noqa: F401  -- registers every model
from app.db.session import Base

BACKEND = Path(__file__).resolve().parents[1]


def _alembic_schema(tmp_path) -> dict[str, set[str]]:
    db_path = tmp_path / "alembic_head.db"
    url = f"sqlite:///{db_path}"
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=BACKEND,
        env={"PATH": "/usr/bin:/bin", "DATABASE_URL": url, "HOME": str(tmp_path),
             "PYTHONPATH": str(BACKEND)},
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    engine = create_engine(url)
    inspector = inspect(engine)
    schema = {
        table: {c["name"] for c in inspector.get_columns(table)}
        for table in inspector.get_table_names()
        if table != "alembic_version"
    }
    engine.dispose()
    return schema


def test_alembic_head_matches_the_models(tmp_path):
    migrated = _alembic_schema(tmp_path)
    declared = {
        name: {c.name for c in table.columns}
        for name, table in Base.metadata.tables.items()
    }

    assert set(migrated) == set(declared), (
        "tables differ between Alembic head and the models: "
        f"only in migrations {set(migrated) - set(declared)}, "
        f"only in models {set(declared) - set(migrated)}"
    )
    for table in sorted(declared):
        assert migrated[table] == declared[table], (
            f"{table}: columns differ -- "
            f"only in migrations {migrated[table] - declared[table]}, "
            f"only in models {declared[table] - migrated[table]}. "
            "Generate a revision: alembic revision --autogenerate -m '...'"
        )
