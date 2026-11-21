"""Rule-based checks applied to every meal the LLM returns.

The LLM is good at writing plausible recipes but can hallucinate ingredients,
assume a stove, blow the time limit, or forget food-safety steps. These
deterministic rules catch that. ``llm.generate_meals`` feeds the violations back
to the model for a corrective retry.

Public API (used by llm.py and the tests):
    normalize(name)                                   -> canonical ingredient name
    check_meal(meal, confirmed, appliances, max_min)  -> list[Violation]
    check_meals(meals, confirmed, appliances, max_min)-> list[Violation]
"""

import re

from .catalog import (
    ALLOWED_BASICS,
    EQUIPMENT_KEYWORDS,
    RAW_PROTEIN_KEYWORDS,
    SAFETY_KEYWORDS,
)
from .schemas import Meal, Violation

# --------------------------------------------------------------------------- names

# Descriptive words that should not block a match ("2% milk" == "milk").
_QUALIFIERS = {
    "leftover", "leftovers", "cooked", "raw", "fresh", "frozen", "shredded", "sliced", "diced",
    "chopped", "minced", "large", "small", "medium", "whole", "half", "of", "a", "the", "some",
    "low", "fat", "nonfat", "reduced", "organic", "plain", "store", "bought", "cup", "cups",
    "can", "canned", "bag", "pack", "package", "bottle", "jar", "and", "or", "optional",
}

# Words that turn one food into a different product. "peanut" is not "peanut butter",
# "chicken" is not "chicken broth", "orange" is not "orange juice".
_PRODUCT_WORDS = {
    "broth", "stock", "sauce", "juice", "soup", "noodle", "cake", "milk", "butter", "oil",
    "powder", "cream", "bread", "chip", "cracker", "syrup", "jam", "dressing", "paste",
    "seasoning", "salsa", "tortilla", "bun", "roll", "yogurt", "cereal",
}


def _singular(word: str) -> str:
    if len(word) > 4 and word.endswith("ies"):
        return word[:-3] + "y"
    if len(word) > 4 and word.endswith("oes"):
        return word[:-2]
    if len(word) > 3 and word.endswith("s") and not word.endswith(("ss", "us")):
        return word[:-1]
    return word


def normalize(name: str) -> str:
    """'2% Shredded Cheddar Cheese' -> 'cheddar cheese'."""
    words = re.findall(r"[a-z]+", name.lower())
    kept = [_singular(w) for w in words if w not in _QUALIFIERS]
    return " ".join(kept)


def _tokens(norm: str) -> list[str]:
    return norm.split()


def _same_food(candidate: str, listed: str) -> bool:
    """Is the meal's ingredient ``candidate`` the same food as the fridge item ``listed``?

    Both arguments are already normalized.
    - exact match
    - candidate is less specific ("cheese" for "cheddar cheese", "rice" for
      "white rice"), unless the listed item is a different product
      ("peanut" for "peanut butter")
    - candidate is more specific but ends in the same noun ("green onion" for
      "onion", "bell pepper" for "pepper")
    """
    c, p = set(_tokens(candidate)), set(_tokens(listed))
    if not c or not p:
        return False
    if c == p:
        return True
    if c < p:
        return not ((p - c) & _PRODUCT_WORDS)
    if p < c:
        return _tokens(candidate)[-1] == _tokens(listed)[-1]
    return False


def _basic_match(candidate: str, basic: str) -> bool:
    """Pantry basics are matched strictly so 'bell pepper' never passes as 'pepper'."""
    c, b = set(_tokens(candidate)), set(_tokens(basic))
    return bool(c) and (c == b or c < b)  # "oil" ok for "olive oil"; never the reverse


def _is_known(name: str, confirmed_pool: set[str], basics_pool: set[str]) -> bool:
    c = normalize(name)
    if not c:
        return True  # nothing meaningful to check ("some")
    return any(_same_food(c, p) for p in confirmed_pool) or any(
        _basic_match(c, b) for b in basics_pool
    )


# --------------------------------------------------------------------------- equipment

# Equipment the catalog does not list but a dorm student will not have either.
_EXTRA_BLOCKED: dict[str, list[str]] = {
    "_slow_cooker": ["slow cooker", "crockpot", "crock-pot", "crock pot", "instant pot",
                     "pressure cooker", "sous vide", "deep fryer"],
    "_pot": ["pot", "wok", "stockpot"],
}

# Phrases that contain an equipment word but mean something else.
_NEUTRALIZE = [
    "microwave oven",    # it is the microwave
    "microwave-safe", "microwave safe",
]

# Words the air fryer legitimately uses.
_AIR_FRYER_OK = {"preheat", "bake at"}


def _has_word(text: str, phrase: str) -> bool:
    """Whole-word / whole-phrase match, so 'grill' does not hit 'grilled' or 'oven' 'over'."""
    return re.search(rf"(?<![a-z]){re.escape(phrase.strip())}(?![a-z])", text) is not None


def _equipment_text(meal: Meal) -> str:
    text = " ".join(meal.steps).lower()
    for phrase in _NEUTRALIZE:
        text = text.replace(phrase, " ")
    return text


def _declared_key(a: str) -> str:
    return re.sub(r"[\s\-/]+", "_", a.strip().lower())


_NO_APPLIANCE = {"", "none", "no_cook", "no_appliance", "n_a", "na", "nothing"}


# --------------------------------------------------------------------------- safety

# A protein name that already says it is safe to eat as-is.
_PRECOOKED = ("cooked", "canned", "smoked", "deli", "hard boiled", "hard-boiled", "boiled",
              "pasteurized", "jerky", "rotisserie", "leftover")
# Names that contain a protein word but are not raw protein.
_NOT_RAW = ("eggplant", "egg roll", "eggroll", "egg noodle", "fish sauce", "peanut", "bacon bit")


def _is_raw_protein(name: str) -> bool:
    n = name.lower()
    if any(x in n for x in _NOT_RAW) or any(x in n for x in _PRECOOKED):
        return False
    return any(_has_word(n, k) or _has_word(n, k + "s") for k in RAW_PROTEIN_KEYWORDS)


def _has_safety_instruction(text: str) -> bool:
    return any(k in text for k in SAFETY_KEYWORDS)


# --------------------------------------------------------------------------- main checks

def check_meal(
    meal: Meal,
    confirmed: list[str],
    appliances: list[str],
    max_prep_minutes: int,
) -> list[Violation]:
    """Return every rule this meal breaks (empty list means the meal is valid)."""
    out: list[Violation] = []
    confirmed_pool = {normalize(n) for n in confirmed} - {""}
    basics_pool = {normalize(n) for n in ALLOWED_BASICS}

    # 1. Every ingredient is in the confirmed fridge list or is an allowed basic.
    for ing in meal.ingredients:
        if not _is_known(ing.name, confirmed_pool, basics_pool):
            out.append(Violation(meal=meal.name, rule="unknown_ingredient",
                                 detail=f"'{ing.name}' is not in the fridge list or allowed basics"))

    # 2. Only selected appliances are used (declared list AND words in the steps).
    allowed = {_declared_key(a) for a in appliances}
    for a in meal.appliances_used:
        key = _declared_key(a)
        if key not in allowed and key not in _NO_APPLIANCE:
            out.append(Violation(meal=meal.name, rule="equipment",
                                 detail=f"declares appliance '{a}' that was not selected"))

    text = _equipment_text(meal)
    blocked = {k: v for k, v in EQUIPMENT_KEYWORDS.items() if k not in allowed}
    blocked.update(_EXTRA_BLOCKED)
    for appliance, words in blocked.items():
        for w in words:
            if "air_fryer" in allowed and w.strip() in _AIR_FRYER_OK:
                continue
            if _has_word(text, w):
                label = appliance.lstrip("_").replace("_", " ")
                out.append(Violation(meal=meal.name, rule="equipment",
                                     detail=f"steps mention '{w.strip()}' ({label}) which is not available"))
                break  # one violation per appliance is enough

    # 3. Prep time fits the limit (and is a real number).
    if meal.prep_minutes > max_prep_minutes:
        out.append(Violation(meal=meal.name, rule="prep_time",
                             detail=f"{meal.prep_minutes} min exceeds the {max_prep_minutes} min limit"))
    elif meal.prep_minutes <= 0:
        out.append(Violation(meal=meal.name, rule="schema",
                             detail=f"prep_minutes must be at least 1 (got {meal.prep_minutes})"))

    # 4. Any raw egg/meat/fish is paired with a cook-through instruction.
    raw = [i.name for i in meal.ingredients if _is_raw_protein(i.name)]
    if raw:
        safety_text = (" ".join(meal.steps) + " " + meal.safety_note).lower()
        if not _has_safety_instruction(safety_text):
            out.append(Violation(meal=meal.name, rule="food_safety",
                                 detail=f"uses raw {raw[0]} but has no cook-through instruction "
                                        "(e.g. 'until fully set', 'cooked through', 'to 165F')"))

    # 5. Basic shape.
    if not any(s.strip() for s in meal.steps):
        out.append(Violation(meal=meal.name, rule="schema", detail="no steps"))
    if not meal.ingredients:
        out.append(Violation(meal=meal.name, rule="schema", detail="no ingredients"))
    return out


def check_meals(meals: list[Meal], confirmed: list[str], appliances: list[str],
                max_prep_minutes: int) -> list[Violation]:
    violations: list[Violation] = []
    for m in meals:
        violations += check_meal(m, confirmed, appliances, max_prep_minutes)
    return violations
