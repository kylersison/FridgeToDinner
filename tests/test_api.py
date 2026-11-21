"""End-to-end API tests in mock mode (no API key, no network)."""

import os

import pytest

os.environ["MOCK_MODE"] = "1"
pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from pathlib import Path  # noqa: E402

from fastapi.testclient import TestClient  # noqa: E402

from backend.app.main import app  # noqa: E402

client = TestClient(app)
PHOTO = Path(__file__).resolve().parents[1] / "data" / "photos" / "fridge_007.jpg"


def test_health():
    assert client.get("/api/health").json()["status"] == "ok"


def test_options():
    body = client.get("/api/options").json()
    assert body["appliances"]["microwave"] == "Microwave"


def test_detect_then_generate():
    with PHOTO.open("rb") as f:
        r = client.post("/api/detect", files={"photo": ("fridge.jpg", f, "image/jpeg")})
    assert r.status_code == 200, r.text
    ingredients = r.json()["ingredients"]
    assert ingredients

    r = client.post("/api/generate", json={
        "ingredients": ingredients,
        "appliances": ["microwave"],
        "priorities": ["speed"],
        "max_prep_minutes": 15,
    })
    assert r.status_code == 200, r.text
    body = r.json()
    assert len(body["meals"]) == 3 and body["remaining_violations"] == []


def test_detect_rejects_non_image():
    r = client.post("/api/detect", files={"photo": ("x.jpg", b"nope", "image/jpeg")})
    assert r.status_code == 400


def test_generate_rejects_unknown_appliance():
    r = client.post("/api/generate", json={"ingredients": [{"name": "eggs"}], "appliances": ["oven"],
                                       "priorities": ["speed"]})
    assert r.status_code == 400


def test_website_served():
    r = client.get("/")
    assert r.status_code == 200 and "FridgeToDinner" in r.text
    assert client.get("/static/app.js").status_code == 200
