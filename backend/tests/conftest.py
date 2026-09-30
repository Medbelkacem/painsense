import base64
import os
import tempfile

# Set before the app modules load: the engine, the keystore and the artifact directories are
# all resolved at import time, and a developer's own .env must not decide where tests write.
_scratch = tempfile.mkdtemp(prefix="painscore-tests-")
os.environ["DATABASE_URL"] = f"sqlite+pysqlite:///{_scratch}/test.db"
os.environ["KEY_STORE_PATH"] = os.path.join(_scratch, "keystore")
os.environ["MODEL_STORE_PATH"] = os.path.join(_scratch, "models")
os.environ["DATASET_PATH"] = os.path.join(_scratch, "datasets")
os.environ["DOCUMENT_STORE_PATH"] = os.path.join(_scratch, "documents")
for _secret in ("MASTER_KEY", "JWT_SECRET", "JWT_REFRESH_SECRET"):
    os.environ[_secret] = base64.b64encode(os.urandom(32)).decode()

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.ai import training  # noqa: E402
from app.database.database import Base, engine  # noqa: E402
from app.database.models import Role, User  # noqa: E402
from app.database.seed import seed_reference_data  # noqa: E402
from app.datasets import generate  # noqa: E402
from app.dependencies import get_db, limiter  # noqa: E402
from app.main import app  # noqa: E402
from app.security import authentication as auth  # noqa: E402

DOCTOR_EMAIL = "s.benali@chu-batna.dz"
ADMIN_EMAIL = "a.mansouri@chu-batna.dz"
PASSWORD = "Consultation-Batna-2026"
TRAINING_ROWS = 600


@pytest.fixture(scope="session", autouse=True)
def platform():
    """One schema, one reference catalogue, one trained model for the whole run.

    Everything here is committed. Per-test writes live in a transaction that is rolled
    back, so tests never see each other's records but do share this fixed background.
    """
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        seed_reference_data(db)
        db.add_all(
            [
                User(
                    email=DOCTOR_EMAIL,
                    password_hash=auth.hash_password(PASSWORD),
                    display_name="Dr S. Benali",
                    role=Role.DOCTOR,
                    speciality="Anaesthesia and pain medicine",
                ),
                User(
                    email=ADMIN_EMAIL,
                    password_hash=auth.hash_password(PASSWORD),
                    display_name="Dr A. Mansouri",
                    role=Role.ADMIN,
                ),
            ]
        )
        db.commit()

        path, metadata = generate.write(TRAINING_ROWS, seed=7)
        generate.register(metadata, path)
        training.train(db, dataset_path=path, cv_folds=2)
    yield


@pytest.fixture
def db():
    """A session whose writes are discarded when the test ends.

    The application commits as it goes, so the session joins the outer transaction through
    a savepoint: a commit inside the code under test releases the savepoint, and the
    rollback here still undoes it.
    """
    connection = engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection, join_transaction_mode="create_savepoint")
    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()


@pytest.fixture
def client(db):
    limiter.reset()
    app.dependency_overrides[get_db] = lambda: db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture
def doctor_headers(client):
    response = client.post(
        "/api/auth/login", json={"email": DOCTOR_EMAIL, "password": PASSWORD}
    )
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


@pytest.fixture
def admin_headers(client):
    response = client.post("/api/auth/login", json={"email": ADMIN_EMAIL, "password": PASSWORD})
    return {"Authorization": f"Bearer {response.json()['access_token']}"}
