import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from database import db  # noqa: E402


@pytest.fixture()
def conn(tmp_path):
    c = db.get_connection(tmp_path / "test.db")
    db.init_db(c)  # loads the seed file, which also validates it
    yield c
    c.close()


@pytest.fixture()
def ingredients(conn):
    return db.get_all_ingredients(conn)
