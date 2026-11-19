"""Score ingredient detection against hand-labeled ground truth (Phase 3 evaluation).

Ground truth file format (eval/ground_truth.json):
    [{"photo": "data/photos/fridge_001.jpg", "cuisine": "mixed",
      "items": ["eggs", "milk", "cheddar cheese"]}, ...]

    python scripts/eval_detection.py --truth eval/ground_truth.json

Prints micro precision / recall / F1 overall and per cuisine tag.
Matching uses the same name normalization as the validator.
"""

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.app.config import settings  # noqa: E402
from backend.app.image_utils import preprocess_image  # noqa: E402
from backend.app.llm import get_client  # noqa: E402
from backend.app.validator import normalize  # noqa: E402


def prf(tp: int, fp: int, fn: int) -> tuple[float, float, float]:
    p = tp / (tp + fp) if tp + fp else 0.0
    r = tp / (tp + fn) if tp + fn else 0.0
    f = 2 * p * r / (p + r) if p + r else 0.0
    return p, r, f


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--truth", type=Path, default=ROOT / "eval" / "ground_truth.json")
    args = ap.parse_args()

    rows = json.loads(args.truth.read_text())
    client = get_client()
    totals = defaultdict(lambda: [0, 0, 0])  # tp, fp, fn per group

    for row in rows:
        jpeg = preprocess_image((ROOT / row["photo"]).read_bytes(), settings.max_image_edge)
        pred = {normalize(i.name) for i in client.detect(jpeg)[0]}
        truth = {normalize(n) for n in row["items"]}
        tp, fp, fn = len(pred & truth), len(pred - truth), len(truth - pred)
        for group in ("ALL", row.get("cuisine", "unspecified")):
            t = totals[group]
            t[0] += tp; t[1] += fp; t[2] += fn
        print(f"{row['photo']}: tp={tp} fp={fp} fn={fn}  missed={sorted(truth - pred)}")

    print("\ngroup            precision  recall   F1")
    for group, (tp, fp, fn) in sorted(totals.items()):
        p, r, f = prf(tp, fp, fn)
        print(f"{group:<16} {p:9.2f} {r:7.2f} {f:6.2f}")


if __name__ == "__main__":
    main()
