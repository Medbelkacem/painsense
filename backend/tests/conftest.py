import base64
import os
import tempfile

_scratch = tempfile.mkdtemp(prefix="painscore-tests-")
os.environ["DATABASE_URL"] = f"sqlite+pysqlite:///{_scratch}/test.db"
os.environ["KEY_STORE_PATH"] = os.path.join(_scratch, "keystore")
os.environ["MODEL_STORE_PATH"] = os.path.join(_scratch, "models")
os.environ["DATASET_PATH"] = os.path.join(_scratch, "datasets")
os.environ["DOCUMENT_STORE_PATH"] = os.path.join(_scratch, "documents")
os.environ["EXTERNAL_DATASET_PATH"] = os.path.join(_scratch, "external")
os.environ["EPIDEMIC_DATA_PATH"] = os.path.join(_scratch, "epidemic")
os.environ["SIGNAL_STORE_PATH"] = os.path.join(_scratch, "signals")
# The sync worker must never reach the network from a test run. Every test that
# exercises it supplies its own connector or its own recorded response.
os.environ["SYNC_ENABLED"] = "false"
os.environ["KAGGLE_USERNAME"] = ""
os.environ["KAGGLE_KEY"] = ""
for _secret in ("MASTER_KEY", "JWT_SECRET", "JWT_REFRESH_SECRET"):
    os.environ[_secret] = base64.b64encode(os.urandom(32)).decode()

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from backend.ai import training
from database.session import Base, engine
from database.models import Role, User
from database.seed import seed_reference_data
from dataset.synthetic import generate
from backend.dependencies import get_db, limiter
from backend.main import app
from security import authentication as auth

DOCTOR_EMAIL = "s.benali@chu-batna.dz"
ADMIN_EMAIL = "a.mansouri@chu-batna.dz"
PASSWORD = "Consultation-Batna-2026"
TRAINING_PATIENTS = 120
TRAINING_ASSESSMENTS = 600


@pytest.fixture(scope="session", autouse=True)
def platform():
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
                    role=Role.CLINIC_ADMIN,
                ),
            ]
        )
        db.commit()

        path, metadata = generate.write(
            TRAINING_ASSESSMENTS, seed=7, patients=TRAINING_PATIENTS
        )
        generate.register(metadata, path)
        training.train(db, dataset_path=path, cv_folds=2)
    yield


@pytest.fixture
def db():
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
