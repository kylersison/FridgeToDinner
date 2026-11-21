import io

import pytest
from PIL import Image

from backend.app.image_utils import InvalidImageError, preprocess_image
from backend.app.llm import MockClient
from backend.app.pipeline import generate_meals
from backend.app.schemas import GenerateRequest, Ingredient, Usage


def make_req(**kw):
    ingredients, _ = MockClient().detect(b"")
    base = dict(ingredients=ingredients, appliances=["microwave"], priorities=["use_expiring", "speed"],
                max_prep_minutes=15)
    base.update(kw)
    return GenerateRequest(**base)


def test_mock_retry_fixes_stove():
    res = generate_meals(make_req(), MockClient())
    assert res.mock
    assert res.attempts == 2
    assert not res.first_try_valid
    assert {v.rule for v in res.violations_fixed} == {"equipment"}
    assert res.remaining_violations == []
    assert len(res.meals) == 3
    assert all(m.prep_minutes <= 15 for m in res.meals)


def test_expiring_item_used_first():
    res = generate_meals(make_req(), MockClient())
    assert "spinach" in res.meals[0].name


class BadThenGood:
    """Fake client: first answer is malformed, second is fine."""

    mock = True

    def __init__(self):
        self.calls = 0

    def generate(self, req, feedback=None):
        self.calls += 1
        if self.calls == 1:
            return [{"name": "Broken", "steps": "not a list"}], Usage(calls=1)
        return MockClient().generate(req, feedback=[None])[0], Usage(calls=1)


def test_schema_error_triggers_retry():
    res = generate_meals(make_req(), BadThenGood())
    assert res.attempts == 2
    assert res.violations_fixed[0].rule == "schema"
    assert res.remaining_violations == []


def test_preprocess_resizes_and_strips():
    buf = io.BytesIO()
    Image.new("RGBA", (3000, 1500), (200, 10, 10, 255)).save(buf, format="PNG")
    out = preprocess_image(buf.getvalue(), max_edge=1024)
    img = Image.open(io.BytesIO(out))
    assert img.format == "JPEG" and max(img.size) == 1024 and img.size[1] == 512
    assert not img.getexif()


def test_preprocess_rejects_garbage():
    with pytest.raises(InvalidImageError):
        preprocess_image(b"definitely not an image")


def test_real_photo_preprocesses():
    from pathlib import Path

    photo = Path(__file__).resolve().parents[1] / "data" / "photos" / "fridge_001.jpg"
    out = preprocess_image(photo.read_bytes(), max_edge=512)
    assert max(Image.open(io.BytesIO(out)).size) == 512


def test_empty_ingredient_names_ignored():
    r = make_req(ingredients=[Ingredient(name="eggs")])
    assert generate_meals(r, MockClient()).remaining_violations == []
