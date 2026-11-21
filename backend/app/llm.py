"""AI layer: one interface, two implementations.

- AnthropicClient calls the Claude API (vision for detection, text for meals).
- MockClient returns canned answers so the app runs with no API key and no cost
  (used by the tests, by graders without a key, and for offline demos).

Both expose:
    detect(jpeg_bytes)            -> (list[Ingredient], Usage)
    generate(request, feedback)   -> (list[dict], Usage)   raw meal dicts, parsed in pipeline.py
"""

import base64
from typing import Protocol

from .config import settings
from .prompts import (
    DETECT_SYSTEM,
    DETECT_TOOL,
    DETECT_USER,
    GENERATE_TOOL,
    generate_system,
    generate_user,
)
from .schemas import GenerateRequest, Ingredient, Usage, Violation


class LLMError(RuntimeError):
    """The AI provider failed or returned something unusable."""


class LLMClient(Protocol):
    mock: bool

    def detect(self, jpeg: bytes) -> tuple[list[Ingredient], Usage]: ...

    def generate(self, req: GenerateRequest, feedback: list[Violation] | None = None) -> tuple[list[dict], Usage]: ...


def _cost(input_tokens: int, output_tokens: int) -> float:
    return round(
        input_tokens / 1e6 * settings.price_in_per_mtok + output_tokens / 1e6 * settings.price_out_per_mtok, 6
    )


# --------------------------------------------------------------------- real


class AnthropicClient:
    mock = False

    def __init__(self, api_key: str, model: str):
        import anthropic  # imported here so mock mode works without the package configured

        self._anthropic = anthropic
        self._client = anthropic.Anthropic(api_key=api_key)
        self.model = model

    def _call(self, system: str, content: list[dict], tool: dict, max_tokens: int) -> tuple[dict, Usage]:
        try:
            resp = self._client.messages.create(
                model=self.model,
                max_tokens=max_tokens,
                system=system,
                tools=[tool],
                tool_choice={"type": "tool", "name": tool["name"]},  # force structured JSON output
                messages=[{"role": "user", "content": content}],
            )
        except self._anthropic.APIError as exc:
            raise LLMError(f"AI provider error: {exc}") from exc

        block = next((b for b in resp.content if b.type == "tool_use"), None)
        if block is None:
            raise LLMError("model did not return structured output")
        u = resp.usage
        usage = Usage(input_tokens=u.input_tokens, output_tokens=u.output_tokens, calls=1,
                      est_cost_usd=_cost(u.input_tokens, u.output_tokens))
        return block.input, usage

    def detect(self, jpeg: bytes) -> tuple[list[Ingredient], Usage]:
        content = [
            {"type": "image",
             "source": {"type": "base64", "media_type": "image/jpeg", "data": base64.b64encode(jpeg).decode()}},
            {"type": "text", "text": DETECT_USER},
        ]
        data, usage = self._call(DETECT_SYSTEM, content, DETECT_TOOL, max_tokens=1024)
        items = []
        for raw in data.get("ingredients", []):
            try:
                item = Ingredient(**raw)
            except Exception:  # skip a malformed item rather than failing the whole photo
                continue
            item.name = item.name.strip().lower()
            if item.name:
                items.append(item)
        return items, usage

    def generate(self, req: GenerateRequest, feedback: list[Violation] | None = None) -> tuple[list[dict], Usage]:
        content = [{"type": "text", "text": generate_user(req, feedback)}]
        data, usage = self._call(generate_system(), content, GENERATE_TOOL, max_tokens=2048)
        meals = data.get("meals", [])
        if not isinstance(meals, list):
            raise LLMError("model returned meals in the wrong format")
        return meals, usage


# --------------------------------------------------------------------- mock

MOCK_INGREDIENTS = [
    Ingredient(name="eggs", quantity="6", confidence=0.97),
    Ingredient(name="cheddar cheese", quantity="half a block", confidence=0.9),
    Ingredient(name="spinach", quantity="1 bag", confidence=0.85, expiring=True),
    Ingredient(name="tortillas", quantity="4", confidence=0.88),
    Ingredient(name="leftover white rice", quantity="1 container", confidence=0.8),
    Ingredient(name="milk", quantity="half a gallon", confidence=0.95),
]


class MockClient:
    """Deterministic fake. The first generate() call deliberately returns one meal
    that needs a stove, so the validate-and-retry loop can be seen working
    without an API key."""

    mock = True

    def detect(self, jpeg: bytes) -> tuple[list[Ingredient], Usage]:
        return [i.model_copy() for i in MOCK_INGREDIENTS], Usage(calls=1)

    def generate(self, req: GenerateRequest, feedback: list[Violation] | None = None) -> tuple[list[dict], Usage]:
        app = req.appliances[0]
        names = [i.name for i in req.ingredients] or ["instant rice"]
        expiring = [i.name for i in req.ingredients if i.expiring]
        first = expiring[0] if expiring else names[0]
        rest = [n for n in names if n != first]
        limit = req.max_prep_minutes

        def meal(title: str, ings: list[str], minutes: int) -> dict:
            return {
                "name": title,
                "prep_minutes": minutes,
                "appliances_used": [app],
                "ingredients": [{"name": n, "amount": "some"} for n in ings] + [{"name": "salt", "amount": "a pinch"}],
                "steps": [
                    f"Combine the {', '.join(ings)} in a {app.replace('_', ' ')}-safe container.",
                    f"Heat with the {app.replace('_', ' ')} in 1-minute bursts, stirring between, "
                    "until steaming hot and cooked through.",
                    "Season with salt and eat.",
                ],
                "why": f"Built around {ings[0]} and ready in {minutes} minutes.",
                "safety_note": "Eggs or meat must be fully set / steaming hot (165F) before eating.",
            }

        third = meal("Loaded fridge scramble", [*(rest[:2] or [first])], min(12, limit))
        if not feedback:  # first try: needs a stove the student does not have
            third["appliances_used"] = ["stove"]
            third["steps"][1] = "Cook in a frying pan on the stove over medium heat until cooked through."
        meals = [
            meal(f"Quick {first} bowl", [first, *rest[:1]], min(10, limit)),
            meal(f"{(rest[1:2] or rest[:1] or [first])[0].title()} wrap", [*(rest[1:3] or [first])], min(8, limit)),
            third,
        ]
        if req.exclude_meals:
            meals = [m for m in meals if m["name"] not in req.exclude_meals] or meals
        return meals, Usage(calls=1)


def get_client() -> LLMClient:
    if settings.mock_mode:
        return MockClient()
    return AnthropicClient(settings.api_key, settings.model)
