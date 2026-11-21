"""Rule-based checks on AI-generated meals.

The LLM is good at inventing recipes but can break the student's constraints:
it may add ingredients that are not in the fridge, use an oven the student does
not have, exceed the time limit, or skip a cook-through instruction for eggs or
meat. Every meal is checked here; violations are fed back to the model for a
retry (see pipeline.py).
"""

import re

from .catalog import (
    ALLOWED_BASICS,
    APPLIANCES,
    EQUIPMENT_KEYWORDS,
    RAW_PROTEIN_KEYWORDS,
    SAFETY_KEYWORDS,
)
from .schemas import GenerateRequest, Meal, Violation

# A few common synonyms so "mayonnaise" and "mayo" count as the same thing.
ALIASES: dict[str, str] = {
    "mayonnaise": "mayo",
    "scallion": "green onion",
    "spring onion": "green onion",
    "catsup": "ketchup",
    "bbq sauce": "barbecue sauce",
    "tomatoe": "tomato",
}

# Words that only point to an oven when no owned appliance is mentioned
# ("preheat the air fryer" is fine, "preheat to 400F" is not).
AMBIGUOUS_KEYWORDS = {"preheat"}


def _singular(word: str) -> str:
    if len(word) <= 3 or word.endswith(("ss", "us", "is")):
        return word
    if word.endswith("ies"):
        return word[:-3] + "y"  # berries -> berry
    if word.endswith("oes"):
        return word[:-2]  # tomatoes -> tomato
    if word.endswith("s"):
        return word[:-1]  # eggs -> egg, tomatos -> tomato
    return word


def normalize(name: str) -> str:
    """Lowercase, drop punctuation and plurals: 'Eggs (6)' -> 'egg'."""
    text = re.sub(r"\(.*?\)", " ", name.lower())
    text = re.sub(r"[^a-z\s-]", " ", text).replace("-", " ")
    text = " ".join(_singular(w) for w in text.split())
    return ALIASES.get(text, text)


def names_match(a: str, b: str) -> bool:
    """Lenient match: equal, or one name's words are contained in the other's
    ("cheese" ~ "cheddar cheese"). Both names must already be normalized."""
    ta, tb = set(a.split()), set(b.split())
    return a == b or bool(ta and tb and (ta <= tb or tb <= ta))


_BASICS = {normalize(b) for b in ALLOWED_BASICS}


def _has_word(text: str, keyword: str) -> bool:
    """Whole-word search that also accepts a plural ('egg' finds 'eggs', not 'eggplant')."""
    return re.search(rf"\b{re.escape(keyword.strip())}(e?s)?\b", text) is not None


def _appliance_key(value: str) -> str:
    v = value.strip().lower().replace("-", "_").replace(" ", "_")
    for key, label in APPLIANCES.items():
        if v in (key, label.lower().replace(" ", "_")):
            return key
    return v


def check_meal(meal: Meal, req: GenerateRequest) -> list[Violation]:
    out: list[Violation] = []
    owned = {_appliance_key(a) for a in req.appliances}
    fridge = [normalize(i.name) for i in req.ingredients]

    # 1. every ingredient must be in the fridge or a pantry basic
    for ing in meal.ingredients:
        n = normalize(ing.name)
        if not n:
            continue
        if n in _BASICS or any(names_match(n, f) for f in fridge):
            continue
        out.append(Violation(meal=meal.name, rule="unknown_ingredient",
                             detail=f"'{ing.name}' is not in the fridge list or the pantry basics"))

    # 2. equipment: declared appliances, and equipment words hidden in the steps
    for a in meal.appliances_used:
        key = _appliance_key(a)
        if key not in owned and key != "none":
            out.append(Violation(meal=meal.name, rule="equipment",
                                 detail=f"uses '{a}', which the student does not have"))
    for step in [meal.name, *meal.steps]:
        text = step.lower().replace("microwave oven", "microwave")
        owned_mentioned = any(_has_word(text, kw) for k in owned for kw in EQUIPMENT_KEYWORDS.get(k, []))
        for key, keywords in EQUIPMENT_KEYWORDS.items():
            if key in owned:
                continue
            for kw in keywords:
                if kw.strip() in AMBIGUOUS_KEYWORDS and owned_mentioned:
                    continue
                if _has_word(text, kw):
                    out.append(Violation(meal=meal.name, rule="equipment",
                                         detail=f"step mentions '{kw.strip()}': \"{step[:80]}\""))
                    break

    # 3. prep time
    if meal.prep_minutes > req.max_prep_minutes:
        out.append(Violation(meal=meal.name, rule="prep_time",
                             detail=f"{meal.prep_minutes} min is over the {req.max_prep_minutes} min limit"))

    # 4. food safety: raw eggs/meat/fish need a cook-through instruction
    ing_text = " ".join(i.name.lower() for i in meal.ingredients)
    proteins = [kw for kw in RAW_PROTEIN_KEYWORDS if _has_word(ing_text, kw)]
    if proteins:
        instructions = " ".join([*meal.steps, meal.safety_note]).lower()
        if not any(s in instructions for s in SAFETY_KEYWORDS):
            out.append(Violation(meal=meal.name, rule="food_safety",
                                 detail=f"uses {', '.join(proteins)} but never says how to tell it is fully cooked"))

    # 5. basic shape
    if not meal.steps or not meal.ingredients:
        out.append(Violation(meal=meal.name, rule="schema", detail="meal has no steps or no ingredients"))

    return out


def validate_meals(meals: list[Meal], req: GenerateRequest) -> list[Violation]:
    return [v for m in meals for v in check_meal(m, req)]
