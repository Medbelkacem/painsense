"""Connector parsing, against responses recorded from the real publishers.

The payload shapes below were taken from live calls to each API. They are kept here as
fixtures so the parsers are tested without the tests depending on a network, on a
publisher being up, or on today's catalogue contents. A publisher that changes its
response shape breaks these tests, which is the point.
"""

import json

import pytest

from database.models import Granularity, LicenceVerdict, SourceAccess
from backend.sync import http, licensing
from backend.sync.sources import cdc, github, huggingface, kaggle, physionet, who

# --- recorded fragments ----------------------------------------------------------------

GHO_INDICATORS = {
    "@odata.context": "https://ghoapi.azureedge.net/api/$metadata#Indicator",
    "value": [
        {
            "IndicatorCode": "CHOLERA_0000000001",
            "IndicatorName": "Number of reported cases of cholera",
            "Language": "EN",
        },
        {
            "IndicatorCode": "ABORTION_ADMISSIONS",
            "IndicatorName": "Abortion admissions per 1000 women",
            "Language": "EN",
        },
        {
            "IndicatorCode": "CHOLERA_FR",
            "IndicatorName": "Cas de cholera",
            "Language": "FR",
        },
    ],
}

GHO_OBSERVATIONS = {
    "value": [
        {"Id": 1, "SpatialDim": "DZA", "TimeDim": 2019, "NumericValue": 12.0},
        {"Id": 2, "SpatialDim": "FRA", "TimeDim": 2019, "NumericValue": 3.0},
    ]
}

SOCRATA_CATALOGUE = {
    "results": [
        {
            "resource": {
                "name": "COVID-19 Case Surveillance Public Use Data",
                "id": "vbim-akqf",
                "description": "Patient-level data reported to CDC.",
                "updatedAt": "2024-08-01T12:00:00.000Z",
            },
            "permalink": "https://data.cdc.gov/d/vbim-akqf",
            "metadata": {"license": "Public Domain U.S. Government"},
        },
        {
            "resource": {
                "name": "NNDSS Weekly Data",
                "id": "x9gk-5huc",
                "description": "Counts by reporting area and MMWR week.",
                "updatedAt": "2024-07-02T09:30:00.000Z",
            },
            "permalink": "https://data.cdc.gov/d/x9gk-5huc",
            "metadata": {},
        },
    ]
}

KAGGLE_RESULTS = [
    {
        "ref": "ziya07/cervical-pain-assessment-dataset",
        "title": "Cervical Pain Assessment Dataset",
        "subtitle": "Pain intensity with EMG and heart rate per patient",
        "description": "",
        "url": "https://www.kaggle.com/datasets/ziya07/cervical-pain-assessment-dataset",
        "licenseName": "CC0: Public Domain",
        "currentVersionNumber": 1,
        "lastUpdated": "2024-11-02T07:15:00.000Z",
        "totalBytes": 48122,
        "isPrivate": False,
    },
    {
        "ref": "someone/cars-of-the-world",
        "title": "Cars of the world",
        "subtitle": "Vehicle specifications",
        "description": "",
        "url": "https://www.kaggle.com/datasets/someone/cars",
        "licenseName": "CC0: Public Domain",
        "isPrivate": False,
    },
    {
        "ref": "private/hidden",
        "title": "Pain intensity private",
        "subtitle": "pain intensity",
        "isPrivate": True,
    },
]

PHYSIONET_OPEN = """
<html><h1>Q-Pain: a question answering dataset</h1>
<meta name="description" content="A dataset for medical bias in pain management.">
<p>Anyone can access the files, as long as they conform to the terms of the specified license.</p>
<a href="/content/q-pain/view-license/1.0.0/">Creative Commons Attribution-ShareAlike 4.0 International Public License</a>
<p>Topics pain nlp Project Views 1000</p>
</html>
"""

PHYSIONET_CREDENTIALED = """
<html><h1>MedDec clinical notes</h1>
<meta name="description" content="Annotated clinical notes.">
<p>Only credentialed users who sign the DUA can access the files.</p>
<a href="/content/meddec/view-license/1.0.0/">PhysioNet Credentialed Health Data License 1.5.0</a>
<a href="/content/meddec/view-dua/1.0.0/">PhysioNet Credentialed Health Data Use Agreement</a>
<p>Topics clinical-notes Project Views 50</p>
</html>
"""


class FakeResponse:
    """Stands in for `http.Response`, carrying either HTML text or a decoded payload."""

    def __init__(self, payload):
        self._payload = payload

    def text(self) -> str:
        return self._payload if isinstance(self._payload, str) else json.dumps(self._payload)

    def json(self):
        return json.loads(self._payload) if isinstance(self._payload, str) else self._payload


@pytest.fixture
def stub(monkeypatch):
    """Replace the HTTP client's reads with recorded payloads, keyed by URL fragment."""

    def _install(routes: dict):
        def _match(url):
            # Suffix first, then substring. Without that a route for
            # "/repos/owner/name" shadows the "/repos/owner/name/readme" request, and the
            # adapter silently parses the wrong payload.
            for fragment, payload in routes.items():
                if url.endswith(fragment):
                    return payload
            for fragment, payload in routes.items():
                if fragment in url:
                    return payload
            raise http.TransferError(f"no recorded response for {url}")

        def get_json(self, url, **kwargs):
            payload = _match(url)
            return json.loads(payload) if isinstance(payload, str) else payload

        def get(self, url, **kwargs):
            return FakeResponse(_match(url))

        monkeypatch.setattr(http.Client, "get_json", get_json)
        monkeypatch.setattr(http.Client, "get", get)

    return _install


# --- WHO ----------------------------------------------------------------------------------


def test_who_filters_the_catalogue_to_configured_terms(stub):
    stub({"/Indicator": GHO_INDICATORS})
    found = who.WHO_GHO.discover({"terms": ["cholera"], "limit": 10})

    assert [row.external_id for row in found] == ["CHOLERA_0000000001"]


def test_who_records_aggregate_statistics_not_clinical_records(stub):
    stub({"/Indicator": GHO_INDICATORS})
    row = who.WHO_GHO.discover({"terms": ["cholera"], "limit": 10})[0]

    assert row.granularity is Granularity.AGGREGATE
    assert row.dataset_type == "aggregate_statistics"
    assert "not as records about individual people" in row.description


def test_who_licence_permits_research_use_only(stub):
    stub({"/Indicator": GHO_INDICATORS})
    row = who.WHO_GHO.discover({"terms": ["cholera"], "limit": 10})[0]
    assert licensing.verdict(row.licence) is LicenceVerdict.RESEARCH_ONLY


def test_who_writes_observations_as_one_object_per_line(stub, tmp_path):
    stub({"/Indicator": GHO_INDICATORS, "/CHOLERA_0000000001": GHO_OBSERVATIONS})
    row = who.WHO_GHO.discover({"terms": ["cholera"], "limit": 10})[0]
    acquired = who.WHO_GHO.fetch(row, tmp_path, max_bytes=1 << 20)

    lines = acquired.files[0].read_text().strip().splitlines()
    assert len(lines) == 2
    assert json.loads(lines[0])["SpatialDim"] == "DZA"
    assert acquired.file_format == "jsonl"
    assert acquired.sha256


def test_who_refuses_an_indicator_with_no_observations(stub, tmp_path):
    stub({"/Indicator": GHO_INDICATORS, "/CHOLERA_0000000001": {"value": []}})
    row = who.WHO_GHO.discover({"terms": ["cholera"], "limit": 10})[0]
    with pytest.raises(who.Unavailable):
        who.WHO_GHO.fetch(row, tmp_path, max_bytes=1 << 20)


# --- CDC ------------------------------------------------------------------------------------


def test_cdc_reads_the_socrata_catalogue(stub):
    stub({"/api/catalog/v1": SOCRATA_CATALOGUE})
    found = cdc.CDC_SOCRATA.discover({"queries": ["covid"], "per_query": 5})

    assert {row.external_id for row in found} == {"vbim-akqf", "x9gk-5huc"}


def test_cdc_distinguishes_case_level_from_summary_tables(stub):
    stub({"/api/catalog/v1": SOCRATA_CATALOGUE})
    found = {row.external_id: row for row in cdc.CDC_SOCRATA.discover({"queries": ["covid"]})}

    assert found["vbim-akqf"].granularity is Granularity.SUBJECT_LEVEL
    assert found["x9gk-5huc"].granularity is Granularity.AGGREGATE


def test_cdc_falls_back_to_the_domain_licence_and_says_so(stub):
    stub({"/api/catalog/v1": SOCRATA_CATALOGUE})
    found = {row.external_id: row for row in cdc.CDC_SOCRATA.discover({"queries": ["covid"]})}

    summary = found["x9gk-5huc"]
    assert summary.licence == cdc.DOMAIN_LICENCE
    assert "domain position" in summary.notes
    assert found["vbim-akqf"].notes == ""


def test_cdc_builds_a_csv_export_url(stub):
    stub({"/api/catalog/v1": SOCRATA_CATALOGUE})
    row = cdc.CDC_SOCRATA.discover({"queries": ["covid"]})[0]
    assert row.download_url.endswith("rows.csv?accessType=DOWNLOAD")


# --- Kaggle -----------------------------------------------------------------------------------


def test_kaggle_keeps_pain_datasets_and_drops_the_rest(stub):
    stub({"/datasets/list": KAGGLE_RESULTS})
    found = kaggle.KAGGLE.discover({"queries": ["pain"], "minimum_relevance": 2})

    assert [row.external_id for row in found] == ["ziya07/cervical-pain-assessment-dataset"]


def test_kaggle_never_lists_a_private_dataset(stub):
    stub({"/datasets/list": KAGGLE_RESULTS})
    found = kaggle.KAGGLE.discover({"queries": ["pain"], "minimum_relevance": 0})
    assert all(row.external_id != "private/hidden" for row in found)


def test_kaggle_infers_modalities_but_says_they_are_inferred(stub):
    stub({"/datasets/list": KAGGLE_RESULTS})
    row = kaggle.KAGGLE.discover({"queries": ["pain"]})[0]

    assert "emg" in row.modalities
    assert "heart_rate" in row.modalities
    assert row.granularity is Granularity.UNKNOWN
    assert "inferred" in row.notes


def test_kaggle_refuses_a_sign_in_page_instead_of_storing_it(stub, tmp_path, monkeypatch):
    stub({"/datasets/list": KAGGLE_RESULTS})
    row = kaggle.KAGGLE.discover({"queries": ["pain"]})[0]

    def fake_download(self, url, destination, *, max_bytes):
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(b"<!DOCTYPE html><html>Sign in to Kaggle</html>")
        return http.Downloaded(destination, 44, "d" * 64, "text/html", url)

    monkeypatch.setattr(http.Client, "download", fake_download)
    with pytest.raises(kaggle.Unavailable, match="did not return an archive"):
        kaggle.KAGGLE.fetch(row, tmp_path, max_bytes=1 << 20)
    assert not (tmp_path / "archive.zip").exists()


def test_kaggle_sends_no_authorization_header_without_credentials():
    client = kaggle.KAGGLE._client()
    assert client.auth_header is None


# --- PhysioNet ---------------------------------------------------------------------------------


def test_physionet_reads_an_open_access_policy(stub):
    stub({"?topic=pain": '<a href="/content/q-pain/">x</a>', "/content/q-pain/": PHYSIONET_OPEN})
    found = physionet.PHYSIONET.discover({"topics": ["pain"], "limit": 5})

    assert len(found) == 1
    row = found[0]
    assert row.access_status is SourceAccess.OPEN
    assert row.publisher_version == "1.0.0"
    assert row.download_url.endswith("q-pain-1.0.0.zip")
    assert licensing.verdict(row.licence) is LicenceVerdict.PERMISSIVE


def test_physionet_records_a_credentialed_project_without_a_download_url(stub):
    stub({"?topic=pain": '<a href="/content/meddec/">x</a>', "/content/meddec/": PHYSIONET_CREDENTIALED})
    row = physionet.PHYSIONET.discover({"topics": ["pain"], "limit": 5})[0]

    assert row.access_status is SourceAccess.CREDENTIALED
    assert row.download_url is None
    assert "Data use agreement" in row.notes
    assert "No files were requested" in row.notes


def test_physionet_refuses_to_fetch_a_restricted_project_even_if_asked_directly(tmp_path):
    """The access gate is enforced in the connector too, not only by the orchestrator."""
    from backend.sync.sources.base import RemoteDataset

    forged = RemoteDataset(
        external_id="meddec",
        name="MedDec",
        source_url="https://physionet.org/content/meddec/",
        download_url="https://physionet.org/static/published-projects/meddec/meddec-1.0.0.zip",
        access_status=SourceAccess.CREDENTIALED,
    )
    with pytest.raises(physionet.Unavailable, match="restricts this project"):
        physionet.PHYSIONET.fetch(forged, tmp_path, max_bytes=1 << 20)


# --- transport guards ------------------------------------------------------------------------


@pytest.mark.parametrize(
    "url",
    [
        "http://data.cdc.gov/api/views/x.csv",
        "https://127.0.0.1/secrets",
        "https://localhost/secrets",
        "https://169.254.169.254/latest/meta-data/",
        "https://10.0.0.5/internal",
        "https://evil-who.int/payload",
    ],
)
def test_the_client_refuses_unsafe_or_undeclared_hosts(url):
    client = http.Client(allowed_hosts=("who.int", "data.cdc.gov"))
    with pytest.raises(http.TransferError):
        client.get(url)


def test_a_subdomain_of_a_declared_host_is_allowed_but_a_lookalike_is_not():
    from backend.sync.http import _registrable_suffix_match

    assert _registrable_suffix_match("ghoapi.azureedge.net", "azureedge.net")
    assert _registrable_suffix_match("who.int", "who.int")
    assert not _registrable_suffix_match("evil-who.int", "who.int")
    assert not _registrable_suffix_match("whoint.example.com", "who.int")


def test_every_connector_declares_the_hosts_it_may_reach():
    from backend.sync import sources

    for connector in sources.CONNECTORS:
        assert connector.hosts, f"{connector.code} declares no host allowlist"


# --- Hugging Face and GitHub ------------------------------------------------------------

HF_DATASET_LICENSED = {
    "id": "HLSS/MassHumanBurns",
    "cardData": {"license": "apache-2.0"},
    "gated": False,
    "private": False,
    "sha": "abc123",
    "lastModified": "2025-02-01T10:00:00.000Z",
    "description": "Synthetic dataset for burn area estimation from 2D human body masks.",
    "siblings": [
        {"rfilename": "labels.npy"},
        {"rfilename": "images.7z"},
        {"rfilename": "README.md"},
    ],
}

HF_DATASET_UNLICENSED = {
    "id": "shubhambaid/skin-burn-dataset",
    "cardData": {},
    "gated": False,
    "private": False,
    "description": "Burn images with YOLO annotations.",
    "siblings": [{"rfilename": "archive.zip"}, {"rfilename": "img0.jpg"}],
}

HF_DATASET_GATED = {
    "id": "someone/private-burns",
    "cardData": {"license": "apache-2.0"},
    "gated": True,
    "private": False,
    "description": "Burn photographs.",
    "siblings": [{"rfilename": "data.zip"}],
}

HF_TREE = [
    {"type": "file", "path": "labels.npy", "size": 320_128},
    {"type": "file", "path": "README.md", "size": 7_651},
    {"type": "file", "path": "images.7z", "lfs": {"size": 23_201_076_325}},
]

GH_REPO_UNLICENSED = {
    "full_name": "VEDAs-Lab/EBIS",
    "html_url": "https://github.com/VEDAs-Lab/EBIS",
    "description": "Extended Burn Image Segmentation Dataset and BuRnSNet model",
    "license": None,
    "default_branch": "main",
    "pushed_at": "2024-07-01T00:00:00Z",
    "size": 4768,
}

GH_REPO_BY_REQUEST = {
    "full_name": "xjtu-mia/BurnAnalysis",
    "html_url": "https://github.com/xjtu-mia/BurnAnalysis",
    "description": "Burn analysis reference implementation",
    "license": {"name": "MIT License", "spdx_id": "MIT"},
    "default_branch": "master",
    "size": 1870,
}


def test_hugging_face_records_a_declared_spdx_licence(stub):
    stub({"/api/datasets/HLSS/MassHumanBurns": HF_DATASET_LICENSED})
    row = huggingface.HUGGING_FACE.discover(
        {"queries": [], "datasets": ["HLSS/MassHumanBurns"]}
    )[0]

    assert row.licence == "apache-2.0"
    assert licensing.verdict(row.licence) is LicenceVerdict.PERMISSIVE
    assert licensing.refusal(row.access_status, LicenceVerdict.PERMISSIVE) is None


def test_an_undeclared_licence_is_recorded_as_undeclared_not_guessed(stub):
    stub({"/api/datasets/shubhambaid/skin-burn-dataset": HF_DATASET_UNLICENSED})
    row = huggingface.HUGGING_FACE.discover(
        {"queries": [], "datasets": ["shubhambaid/skin-burn-dataset"]}
    )[0]

    assert row.licence is None
    assert licensing.verdict(row.licence) is LicenceVerdict.UNKNOWN
    assert "declares no licence" in row.notes
    assert licensing.refusal(row.access_status, LicenceVerdict.UNKNOWN) is not None


def test_a_gated_repository_is_never_fetched(stub, tmp_path):
    stub({"/api/datasets/someone/private-burns": HF_DATASET_GATED})
    row = huggingface.HUGGING_FACE.discover(
        {"queries": [], "datasets": ["someone/private-burns"]}
    )[0]

    assert row.access_status is SourceAccess.REGISTRATION_REQUIRED
    with pytest.raises(huggingface.Unavailable, match="gated"):
        huggingface.HUGGING_FACE.fetch(row, tmp_path, max_bytes=1 << 30)


def test_an_empty_query_list_means_no_search(stub):
    """A deployment naming its own repositories must not also get the default sweep."""
    stub({"/api/datasets/HLSS/MassHumanBurns": HF_DATASET_LICENSED})
    rows = huggingface.HUGGING_FACE.discover(
        {"queries": [], "datasets": ["HLSS/MassHumanBurns"]}
    )
    assert [row.external_id for row in rows] == ["HLSS/MassHumanBurns"]


def test_hugging_face_takes_the_small_files_and_says_what_it_left(stub, tmp_path, monkeypatch):
    """A 23 GB archive beside a 320 KB label file should yield the labels, not nothing."""
    stub(
        {
            "/api/datasets/HLSS/MassHumanBurns/tree/main": HF_TREE,
            "/api/datasets/HLSS/MassHumanBurns": HF_DATASET_LICENSED,
        }
    )
    row = huggingface.HUGGING_FACE.discover(
        {"queries": [], "datasets": ["HLSS/MassHumanBurns"]}
    )[0]

    def fake_download(self, url, destination, *, max_bytes):
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(b"x" * 1024)
        return http.Downloaded(destination, 1024, "e" * 64, "application/octet-stream", url)

    monkeypatch.setattr(http.Client, "download", fake_download)
    acquired = huggingface.HUGGING_FACE.fetch(row, tmp_path, max_bytes=1 << 20)

    stored = {path.name for path in acquired.files}
    assert "labels.npy" in stored
    assert "images.7z" not in stored, "the oversized archive must not be retrieved"
    assert "exceeded the size limit" in acquired.notes
    assert "partial" in acquired.notes


def test_a_repository_whose_every_file_is_oversized_fails_clearly(stub, tmp_path):
    stub(
        {
            "/api/datasets/HLSS/MassHumanBurns/tree/main": [HF_TREE[2]],
            "/api/datasets/HLSS/MassHumanBurns": HF_DATASET_LICENSED,
        }
    )
    row = huggingface.HUGGING_FACE.discover(
        {"queries": [], "datasets": ["HLSS/MassHumanBurns"]}
    )[0]
    with pytest.raises(huggingface.Unavailable, match="size limit"):
        huggingface.HUGGING_FACE.fetch(row, tmp_path, max_bytes=1 << 20)


def test_github_records_a_missing_license_file_as_missing(stub):
    stub({"/repos/VEDAs-Lab/EBIS": GH_REPO_UNLICENSED, "/readme": "Download the dataset here."})
    row = github.GITHUB.discover({"repositories": ["VEDAs-Lab/EBIS"]})[0]

    assert row.licence is None
    assert "declares no LICENSE file" in row.notes
    assert licensing.refusal(row.access_status, LicenceVerdict.UNKNOWN) is not None


def test_github_reads_a_request_route_out_of_the_readme(stub):
    stub(
        {
            "/repos/xjtu-mia/BurnAnalysis": GH_REPO_BY_REQUEST,
            "/readme": "The burn images are available upon request; please contact the authors.",
        }
    )
    row = github.GITHUB.discover({"repositories": ["xjtu-mia/BurnAnalysis"]})[0]

    assert row.access_status is SourceAccess.AGREEMENT_REQUIRED
    assert "by request" in row.notes
    assert licensing.refusal(row.access_status, LicenceVerdict.PERMISSIVE) is not None


def test_github_says_a_tarball_is_code_and_not_the_dataset(stub):
    stub({"/repos/xjtu-mia/BurnAnalysis": GH_REPO_BY_REQUEST, "/readme": "Open data here."})
    row = github.GITHUB.discover({"repositories": ["xjtu-mia/BurnAnalysis"]})[0]
    assert row.dataset_type == "source_code"
    assert "reference implementation" in row.notes


def test_github_with_no_repositories_configured_discovers_nothing(stub):
    assert github.GITHUB.discover({}) == []
