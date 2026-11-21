"""Prompts and tool (JSON) schemas sent to the model.

Both calls use Anthropic "tool use" with a forced tool choice, so the model must
answer with JSON matching the schema below instead of free text.
"""

from .catalog import ALLOWED_BASICS, APPLIANCES, PRIORITIES
from .schemas import GenerateRequest, Violation

# ---------------------------------------------------------------- detection

DETECT_SYSTEM = """You look at a photo of the inside of a refrigerator and list the food in it.
Rules:
- Only list items you can actually see. Do not guess what is behind closed containers or doors.
- Use short, common grocery names in lowercase and singular-or-plural as written on a shopping list
  (e.g. "eggs", "milk", "cheddar cheese", "soy sauce"). No brand names.
- quantity: a rough amount if visible ("2", "half a carton", "1 bottle"), otherwise "".
- confidence: 0.0-1.0, how sure you are the item is what you named.
- expiring: true only if the item visibly looks old or wilted, or a readable date shows it is near expiry.
- If the photo is not a fridge or shows no food, return an empty list."""

DETECT_USER = "List the food items visible in this fridge photo."

DETECT_TOOL = {
    "name": "report_ingredients",
    "description": "Report the food items visible in the fridge photo.",
    "input_schema": {
        "type": "object",
        "properties": {
            "ingredients": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "quantity": {"type": "string"},
                        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                        "expiring": {"type": "boolean"},
                    },
                    "required": ["name", "confidence"],
                },
            }
        },
        "required": ["ingredients"],
    },
}

# --------------------------------------------------------------- generation

GENERATE_SYSTEM = """You suggest quick meals for a college student living in a dorm room.
The student only has the appliances listed and the ingredients listed, plus these pantry basics:
{basics}.

Hard rules (every meal is checked automatically and rejected if it breaks one):
1. Use ONLY the listed ingredients and pantry basics. Do not add anything else, not even garnishes.
2. Use ONLY the listed appliances. Never use an oven, stove, grill, or blender unless listed.
   Put the appliance keys you use in appliances_used, or ["none"] for a no-cook meal.
3. prep_minutes must be at or under the time limit.
4. If a meal uses raw eggs, meat, poultry or fish, a step or the safety_note must say how to tell it
   is fully cooked (e.g. "until the eggs are fully set", "until steaming hot and no pink remains, 165F").
5. Respect the allergies. Leave out any ingredient the student is allergic to.
Write short, numbered-style steps a beginner can follow. "why" is one sentence on how the meal fits the
student's priorities."""

GENERATE_TOOL = {
    "name": "suggest_meals",
    "description": "Return 3 meal suggestions.",
    "input_schema": {
        "type": "object",
        "properties": {
            "meals": {
                "type": "array",
                "minItems": 1,
                "maxItems": 3,
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "prep_minutes": {"type": "integer"},
                        "appliances_used": {"type": "array", "items": {"type": "string"}},
                        "ingredients": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {"name": {"type": "string"}, "amount": {"type": "string"}},
                                "required": ["name"],
                            },
                        },
                        "steps": {"type": "array", "items": {"type": "string"}},
                        "why": {"type": "string"},
                        "safety_note": {"type": "string"},
                    },
                    "required": ["name", "prep_minutes", "appliances_used", "ingredients", "steps"],
                },
            }
        },
        "required": ["meals"],
    },
}


def generate_system() -> str:
    return GENERATE_SYSTEM.format(basics=", ".join(sorted(ALLOWED_BASICS)))


def generate_user(req: GenerateRequest, feedback: list[Violation] | None = None) -> str:
    ings = "\n".join(
        f"- {i.name}" + (f" ({i.quantity})" if i.quantity else "") + (" [EXPIRING SOON]" if i.expiring else "")
        for i in req.ingredients
    )
    apps = ", ".join(f"{a} ({APPLIANCES.get(a, a)})" for a in req.appliances)
    prios = ", ".join(f"{n}. {PRIORITIES.get(p, p)}" for n, p in enumerate(req.priorities, 1))
    parts = [
        f"Ingredients in the fridge:\n{ings}",
        f"Appliances (use these keys in appliances_used): {apps}",
        f"Priorities, most important first: {prios}",
        f"Time limit: {req.max_prep_minutes} minutes",
        f"Allergies: {req.allergies or 'none'}",
    ]
    if req.exclude_meals:
        parts.append("Do not suggest these meals again: " + ", ".join(req.exclude_meals))
    if feedback:
        problems = "\n".join(f"- {v.meal}: [{v.rule}] {v.detail}" for v in feedback)
        parts.append(
            "Your previous answer broke these rules. Return 3 meals again, fixing every problem "
            "(replace a meal if it cannot be fixed):\n" + problems
        )
    parts.append("Suggest 3 meals.")
    return "\n\n".join(parts)
