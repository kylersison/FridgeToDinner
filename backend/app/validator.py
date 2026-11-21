"""Rule-based checks on AI-generated meals.

The LLM is good at inventing recipes but can break the student's constraints:
it may add ingredients that are not in the fridge, use an oven the student does
not have, exceed the time limit, or skip a cook-through instruction for eggs or
meat. Every meal is checked here; violations are fed back to the model for a
retry (see pipeline.py).

Public API (used by pipeline.py, scripts/eval_detection.py and the tests):
    normalize(name)                -> canonical ingredient name
    names_match(a, b)              -> lenient match of two normalized names
    check_meal(meal, req)          -> list[Violation] for one meal
    validate_meals(meals, req)     -> list[Violation] for all meals
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
AMBIGUOUS_KEYWORDS = {"preheat", "bake at"}

# Equipment the catalog does not list but a dorm student will not have either.
EXTRA_BLOCKED: dict[str, list[str]] = {
    "_slow_cooker": ["slow cooker", "crockpot", "crock-pot", "crock pot", "instant pot",
                     "pressure cooker", "sous vide", "deep fryer"],
    "_pot": ["pot", "wok", "stockpot"],
}

NO_APPLIANCE = {"", "none", "no_cook", "no_appliance", "n_a", "na", "nothing"}

# Descriptive words that must not block a match ("leftover cooked rice" ~ "rice").
_QUALIFIERS = {
    "leftover", "leftovers", "cooked", "raw", "fresh", "frozen", "shredded", "sliced", "diced",
    "chopped", "minced", "large", "small", "medium", "whole", "half", "of", "a", "the", "some",
    "low", "fat", "nonfat", "reduced", "organic", "plain", "store", "bought", "cup", "cups",
    "can", "canned", "bag", "pack", "package", "bottle", "jar", "and", "or", "optional",
}

# Words that turn one food into a different product: "peanut" is not "peanut butter",
# "chicken" is not "chicken broth", "orange" is not "orange juice".
_PRODUCT_WORDS = {
    "broth", "stock", "sauce", "juice", "soup", "noodle", "cake", "milk", "butter", "oil",
    "powder", "cream", "bread", "chip", "cracker", "syrup", "jam", "dressing", "paste",
    "seasoning", "salsa", "tortilla", "bun", "roll", "yogurt", "cereal",
}

# Protein names that are already safe to eat, or that only contain a protein word.
_PRECOOKED = ("cooked", "canned", "smoked", "deli", "boiled", "pasteurized", "jerky",
              "rotisserie", "leftover")
_NOT_RAW = ("eggplant", "egg roll", "eggroll", "egg noodle", "fish sauce", "peanut", "bacon bit")


# --------------------------------------------------------------------------- names

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


def _core(name: str) -> list[str]:
    """Normalized words with descriptive qualifiers removed."""
    return [w for w in normalize(name).split() if w not in _QUALIFIERS]


def _same_food(candidate: list[str], listed: list[str]) -> bool:
    """Is a meal's ingredient the same food as a fridge item?

    - same words
    - meal ingredient is less specific ("cheese" for "cheddar cheese"), unless the
      fridge item is a different product ("peanut" for "peanut butter")
    - meal ingredient is more specific but ends in the same noun
      ("green onion" for "onion")
    """
    c, p = set(candidate), set(listed)
    if not c or not p:
        return False
    if c == p:
        return True
    if c < p:
        return not ((p - c) & _PRODUCT_WORDS)
    if p < c:
        return candidate[-1] == listed[-1]
    return False


def _basic_match(candidate: list[str], basic: list[str]) -> bool:
    """Pantry basics match strictly, so 'bell pepper' never passes as 'pepper'."""
    c, b = set(candidate), set(basic)
    return bool(c) and (c == b or c < b)  # "oil" ok for "olive oil", never the reverse


_BASICS = [_core(b) for b in ALLOWED_BASICS]


# --------------------------------------------------------------------------- equipment

def _has_word(text: str, keyword: str) -> bool:
    """Whole-word search that also accepts a plural ('egg' finds 'eggs', not 'eggplant')."""
    return re.search(rf"\b{re.escape(keyword.strip())}(e?s)?\b", text) is not None


def _appliance_key(value: str) -> str:
    v = re.sub(r"[\s\-/]+", "_", value.strip().lower())
    for key, label in APPLIANCES.items():
        if v in (key, re.sub(r"[\s\-/]+", "_", label.lower())):
            return key
    return v


# --------------------------------------------------------------------------- checks

def _is_raw_protein(name: str) -> str | None:
    n = name.lower()
    if any(x in n for x in _NOT_RAW) or any(x in n for x in _PRECOOKED):
        return None
    return next((k for k in RAW_PROTEIN_KEYWORDS if _has_word(n, k)), None)


def check_meal(meal: Meal, req: GenerateRequest) -> list[Violation]:
    """Return every rule this meal breaks (empty list means the meal is valid)."""
    out: list[Violation] = []
    owned = {_appliance_key(a) for a in req.appliances}
    fridge = [_core(i.name) for i in req.ingredients]

    # 1. every ingredient must be in the fridge or a pantry basic
    for ing in meal.ingredients:
        c = _core(ing.name)
        if not c:
            continue
        if any(_same_food(c, f) for f in fridge) or any(_basic_match(c, b) for b in _BASICS):
            continue
        out.append(Violation(meal=meal.name, rule="unknown_ingredient",
                             detail=f"'{ing.name}' is not in the fridge list or the pantry basics"))

    # 2. equipment: declared appliances, and equipment words hidden in the steps
    for a in meal.appliances_used:
        key = _appliance_key(a)
        if key not in owned and key not in NO_APPLIANCE:
            out.append(Violation(meal=meal.name, rule="equipment",
                                 detail=f"uses '{a}', which the student does not have"))
    blocked = {k: v for k, v in EQUIPMENT_KEYWORDS.items() if k not in owned}
    blocked.update(EXTRA_BLOCKED)
    flagged: set[str] = set()
    for step in [meal.name, *meal.steps]:
        text = step.lower().replace("microwave oven", "microwave")
        owned_mentioned = any(_has_word(text, kw) for k in owned
                              for kw in EQUIPMENT_KEYWORDS.get(k, []))
        for key, keywords in blocked.items():
            if key in flagged:
                continue
            for kw in keywords:
                if kw.strip() in AMBIGUOUS_KEYWORDS and owned_mentioned:
                    continue
                if _has_word(text, kw):
                    flagged.add(key)
                    out.append(Violation(meal=meal.name, rule="equipment",
                                         detail=f"step mentions '{kw.strip()}': \"{step[:80]}\""))
                    break

    # 3. prep time
    if meal.prep_minutes > req.max_prep_minutes:
        out.append(Violation(meal=meal.name, rule="prep_time",
                             detail=f"{meal.prep_minutes} min is over the {req.max_prep_minutes} min limit"))
    elif meal.prep_minutes <= 0:
        out.append(Violation(meal=meal.name, rule="schema",
                             detail=f"prep_minutes must be at least 1 (got {meal.prep_minutes})"))

    # 4. food safety: each raw egg/meat/fish ingredient needs a cook-through instruction.
    #    Checked per ingredient so "cooked rice" cannot hide a raw egg.
    proteins = sorted({p for i in meal.ingredients if (p := _is_raw_protein(i.name))})
    if proteins:
        instructions = " ".join([*meal.steps, meal.safety_note]).lower()
        if not any(s in instructions for s in SAFETY_KEYWORDS):
            out.append(Violation(meal=meal.name, rule="food_safety",
                                 detail=f"uses {', '.join(proteins)} but never says how to tell it is fully cooked"))

    # 5. basic shape
    if not any(s.strip() for s in meal.steps) or not meal.ingredients:
        out.append(Violation(meal=meal.name, rule="schema", detail="meal has no steps or no ingredients"))

    return out


def validate_meals(meals: list[Meal], req: GenerateRequest) -> list[Violation]:
    return [v for m in meals for v in check_meal(m, req)]
