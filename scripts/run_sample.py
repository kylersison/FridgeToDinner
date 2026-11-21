"""Run the full flow on one photo without starting the server.

    python scripts/run_sample.py --photo data/photos/fridge_010.jpg
    python scripts/run_sample.py --photo data/photos/fridge_010.jpg --appliances microwave electric_kettle \
        --priorities speed use_expiring --max-minutes 15

Prints the detected ingredients and the validated meals as JSON. Without an
ANTHROPIC_API_KEY (or with MOCK_MODE=1) it uses canned mock answers.
"""

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.app.config import settings  # noqa: E402
from backend.app.image_utils import preprocess_image  # noqa: E402
from backend.app.llm import get_client  # noqa: E402
from backend.app.pipeline import generate_meals  # noqa: E402
from backend.app.schemas import GenerateRequest  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--photo", type=Path, default=ROOT / "data" / "photos" / "fridge_010.jpg")
    ap.add_argument("--appliances", nargs="+", default=["microwave"])
    ap.add_argument("--priorities", nargs="+", default=["speed", "use_expiring"])
    ap.add_argument("--max-minutes", type=int, default=20)
    ap.add_argument("--allergies", default="")
    args = ap.parse_args()

    client = get_client()
    print(f"mode: {'MOCK' if client.mock else settings.model}\n")

    jpeg = preprocess_image(args.photo.read_bytes(), settings.max_image_edge)
    ingredients, det_usage = client.detect(jpeg)
    print("Detected ingredients:")
    for i in ingredients:
        print(f"  - {i.name} ({i.quantity or '?'}) conf={i.confidence:.2f}{' EXPIRING' if i.expiring else ''}")

    req = GenerateRequest(ingredients=ingredients, appliances=args.appliances, priorities=args.priorities,
                          max_prep_minutes=args.max_minutes, allergies=args.allergies)
    result = generate_meals(req, client)
    total = det_usage.add(result.usage)

    print(f"\nMeals (attempts={result.attempts}, first_try_valid={result.first_try_valid}):")
    print(json.dumps([m.model_dump() for m in result.meals], indent=2))
    if result.violations_fixed:
        print("\nFixed by retry:", json.dumps([v.model_dump() for v in result.violations_fixed], indent=2))
    if result.remaining_violations:
        print("\nStill failing:", json.dumps([v.model_dump() for v in result.remaining_violations], indent=2))
    print(f"\nUsage: {total.calls} calls, {total.input_tokens} in / {total.output_tokens} out tokens, "
          f"~${total.est_cost_usd:.4f}")


if __name__ == "__main__":
    main()
