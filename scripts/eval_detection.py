"""Score ingredient detection against hand-labeled ground truth.

Ground truth file format (eval/ground_truth.json):
    [{"photo": "data/photos/fridge_001.jpg", "cuisine": "mixed", "source": "stock",
      "items": ["eggs", "milk", "cheddar cheese"]}, ...]

    python scripts/eval_detection.py --truth eval/ground_truth.json [--save eval/raw_predictions.json]

Two scores are reported:
  strict  - names must match exactly after normalization ("eggs" == "egg")
  lenient - one name's words are contained in the other's ("cheese" ~ "cheddar cheese"),
            the same rule the app's validator uses; each truth item matches at most once
Per photo it prints the missed items (false negatives) and the extra items the model
reported that are not in the labels (false positives) so they can be reviewed by hand.
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


def _lenient_eq(a: str, b: str) -> bool:
    ta, tb = set(a.split()), set(b.split())
    return a == b or (ta and tb and (ta <= tb or tb <= ta))


def match(pred: list[str], truth: list[str], lenient: bool) -> tuple[int, list[str], list[str]]:
    """One-to-one greedy matching. Returns (tp, unmatched_pred, unmatched_truth)."""
    remaining = list(truth)
    extra = []
    tp = 0
    for p in pred:
        hit = next((t for t in remaining if (p == t if not lenient else _lenient_eq(p, t))), None)
        if hit is None:
            extra.append(p)
        else:
            remaining.remove(hit)
            tp += 1
    return tp, extra, remaining


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--truth", type=Path, default=ROOT / "eval" / "ground_truth.json")
    ap.add_argument("--save", type=Path, help="write raw model predictions to this JSON file")
    args = ap.parse_args()

    rows = json.loads(args.truth.read_text(encoding="utf-8-sig"))
    client = get_client()
    totals = {"strict": defaultdict(lambda: [0, 0, 0]), "lenient": defaultdict(lambda: [0, 0, 0])}
    saved = []

    for row in rows:
        jpeg = preprocess_image((ROOT / row["photo"]).read_bytes(), settings.max_image_edge)
        detected = client.detect(jpeg)[0]
        pred = sorted({normalize(i.name) for i in detected})
        truth = sorted({normalize(n) for n in row["items"]})
        saved.append({"photo": row["photo"], "predicted": [i.name for i in detected], "truth": row["items"]})

        for mode in ("strict", "lenient"):
            tp, extra, missed = match(pred, truth, lenient=(mode == "lenient"))
            groups = ["ALL", f"cuisine:{row.get('cuisine', '?')}", f"source:{row.get('source', '?')}"]
            for g in groups:
                t = totals[mode][g]
                t[0] += tp; t[1] += len(extra); t[2] += len(missed)
            if mode == "lenient":
                print(f"\n{row['photo']}: tp={tp} fp={len(extra)} fn={len(missed)}")
                print(f"   missed (in labels, not detected): {missed}")
                print(f"   extra  (detected, not in labels): {extra}")

    for mode in ("strict", "lenient"):
        print(f"\n[{mode}] group              precision  recall    F1")
        for g, (tp, fp, fn) in sorted(totals[mode].items()):
            p, r, f = prf(tp, fp, fn)
            print(f"  {g:<24} {p:9.2f} {r:7.2f} {f:6.2f}")

    if args.save:
        args.save.write_text(json.dumps(saved, indent=2), encoding="utf-8")
        print(f"\nraw predictions saved to {args.save}")


if __name__ == "__main__":
    main()
