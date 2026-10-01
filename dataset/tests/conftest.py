import pytest

from dataset.pipeline.registry import MODEL_READY_FILE, UNIFIED_FILE


@pytest.fixture(scope="session")
def unified():
    if not UNIFIED_FILE.exists():
        pytest.skip(f"{UNIFIED_FILE} does not exist; run python -m dataset.pipeline run")
    import pandas as pd

    return pd.read_parquet(UNIFIED_FILE)


@pytest.fixture(scope="session")
def model_ready():
    if not MODEL_READY_FILE.exists():
        pytest.skip(f"{MODEL_READY_FILE} does not exist; run python -m dataset.pipeline run")
    import pandas as pd

    return pd.read_parquet(MODEL_READY_FILE)
