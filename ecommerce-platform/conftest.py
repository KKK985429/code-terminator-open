from __future__ import annotations

import pytest

from testsupport import clear_bug_flags, prepare_test_database, seed_basic_data


@pytest.fixture()
def db_session(tmp_path):
    clear_bug_flags()
    prepare_test_database(tmp_path)
    from services.shared.database import SessionLocal

    assert SessionLocal is not None
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture()
def seeded_db(db_session):
    ids = seed_basic_data(db_session)
    return db_session, ids
