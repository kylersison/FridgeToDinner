"""Generate -> validate -> retry loop.

1. Ask the model for meals.
2. Parse each meal (malformed meals become 'schema' violations) and run the
   rule checks in validator.py.
3. If anything failed and attempts remain, send the violations back to the
   model as feedback and try again.
The response reports which problems were fixed by a retry and which remain, so
the UI (and the evaluation) can show how often the first answer was valid.
"""

from pydantic import ValidationError

from .config import settings
from .llm import LLMClient, get_client
from .schemas import GenerateRequest, GenerateResponse, Meal, Usage, Violation
from .validator import validate_meals


def _parse(raw_meals: list[dict]) -> tuple[list[Meal], list[Violation]]:
    meals, bad = [], []
    for raw in raw_meals:
        try:
            meals.append(Meal(**raw))
        except (ValidationError, TypeError) as exc:
            name = raw.get("name", "unnamed meal") if isinstance(raw, dict) else "unnamed meal"
            bad.append(Violation(meal=str(name), rule="schema", detail=str(exc).splitlines()[0]))
    return meals, bad


def _key(v: Violation) -> tuple[str, str]:
    return (v.meal, v.rule)


def generate_meals(req: GenerateRequest, client: LLMClient | None = None) -> GenerateResponse:
    client = client or get_client()
    usage = Usage()
    seen: list[Violation] = []
    feedback: list[Violation] | None = None
    meals: list[Meal] = []
    violations: list[Violation] = []
    first_try_valid = False
    attempts = 0

    for attempt in range(1, max(1, settings.max_generation_attempts) + 1):
        attempts = attempt
        raw, u = client.generate(req, feedback)
        usage = usage.add(u)
        meals, violations = _parse(raw)
        violations += validate_meals(meals, req)
        if attempt == 1:
            first_try_valid = not violations and bool(meals)
        if not violations and meals:
            break
        seen += violations
        feedback = violations

    remaining = {_key(v) for v in violations}
    fixed = []
    for v in seen:
        if _key(v) not in remaining and _key(v) not in {_key(f) for f in fixed}:
            fixed.append(v)

    return GenerateResponse(
        meals=meals,
        attempts=attempts,
        first_try_valid=first_try_valid,
        violations_fixed=fixed,
        remaining_violations=violations,
        usage=usage,
        mock=client.mock,
    )
