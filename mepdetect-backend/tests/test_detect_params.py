"""
Detection parameter binding tests.

The upload is multipart, so settings sent as form fields are the natural
thing to reach for; they used to bind as query parameters only, which meant
a form field was dropped in silence and the job ran with the defaults. Both
forms are accepted now, and these tests pin that down so neither way of
calling the endpoint can regress into doing nothing.
"""

import sys
from pathlib import Path

import pytest
from fastapi import Depends, FastAPI, File, UploadFile
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from main import DetectionSettings, detection_settings


@pytest.fixture(scope="module")
def client():
    """A stand-in endpoint using the real dependency, with no model to load."""

    app = FastAPI()

    @app.post("/detect")
    async def detect(
        file: UploadFile = File(...),
        settings: DetectionSettings = Depends(detection_settings),
    ):
        return settings.__dict__

    return TestClient(app)


UPLOAD = {"file": ("plan.pdf", b"%PDF-1.4 stub")}


def test_form_fields_bind(client):
    response = client.post("/detect", files=UPLOAD, data={
        "confidence": "0.4",
        "dpi": "300",
        "trace_circuits": "true",
        "export_formats": "netlist,dxf",
        "ref_points": "0,0,300,400",
        "real_distance": "50",
    })

    assert response.status_code == 200
    body = response.json()
    assert body["confidence"] == pytest.approx(0.4)
    assert body["dpi"] == 300
    assert body["trace_circuits"] is True
    assert body["export_formats"] == "netlist,dxf"
    assert body["ref_points"] == "0,0,300,400"
    assert body["real_distance"] == pytest.approx(50.0)


def test_query_parameters_still_bind(client):
    """The frontend calls it this way; the fix must not break it."""

    response = client.post(
        "/detect?confidence=0.6&dpi=200&trace_circuits=true&export_formats=json",
        files=UPLOAD,
    )

    assert response.status_code == 200
    body = response.json()
    assert body["confidence"] == pytest.approx(0.6)
    assert body["dpi"] == 200
    assert body["trace_circuits"] is True
    assert body["export_formats"] == "json"


def test_form_wins_over_query(client):
    response = client.post("/detect?confidence=0.1", files=UPLOAD,
                           data={"confidence": "0.9"})

    assert response.json()["confidence"] == pytest.approx(0.9)


def test_defaults_when_nothing_is_sent(client):
    body = client.post("/detect", files=UPLOAD).json()

    assert body["confidence"] == pytest.approx(0.25)
    assert body["dpi"] == 400
    assert body["trace_circuits"] is False
    assert body["save_annotated"] is True
    assert body["export_formats"] == "json,csv,excel"
    assert body["units"] == "feet"
    assert body["ref_points"] is None


@pytest.mark.parametrize("text,expected", [
    ("true", True), ("True", True), ("1", True), ("yes", True), ("on", True),
    ("false", False), ("0", False), ("no", False), ("", False),
])
def test_query_booleans_read_as_written(client, text, expected):
    body = client.post(f"/detect?trace_circuits={text}", files=UPLOAD).json()
    assert body["trace_circuits"] is expected


def test_unparseable_query_value_is_rejected(client):
    """A typo used to fall through to the default; it is an error now."""

    response = client.post("/detect?dpi=abc", files=UPLOAD)
    assert response.status_code == 400
    assert "dpi" in response.json()["detail"]
