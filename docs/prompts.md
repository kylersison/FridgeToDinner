# Prompts and API workflow

Both model calls go through the Anthropic Messages API (`backend/app/llm.py`) with **forced tool use**:
the request includes one tool with a JSON schema and `tool_choice = {"type": "tool", "name": ...}`, so
the model must answer with JSON that fits the schema instead of free text. The model is set by
`ANTHROPIC_MODEL` (default `claude-haiku-4-5`). The prompt text lives in `backend/app/prompts.py`.

## Call 1: ingredient detection (`POST /api/detect`)

**Input:** the fridge photo after `image_utils.preprocess_image` (JPEG, longest edge ≤ 1024 px, EXIF/GPS removed), sent as a base64 image block, plus a short text instruction.
**Output:** `report_ingredients` tool call → list of `{name, quantity, confidence, expiring}`.
Malformed items are skipped, and names are lowercased.

System prompt:
```
You look at a photo of the inside of a refrigerator and list the food in it.
Rules:
- Only list items you can actually see. Do not guess what is behind closed containers or doors.
- Use short, common grocery names in lowercase and singular-or-plural as written on a shopping list
  (e.g. "eggs", "milk", "cheddar cheese", "soy sauce"). No brand names.
- quantity: a rough amount if visible ("2", "half a carton", "1 bottle"), otherwise "".
- confidence: 0.0-1.0, how sure you are the item is what you named.
- expiring: true only if the item visibly looks old or wilted, or a readable date shows it is near expiry.
- If the photo is not a fridge or shows no food, return an empty list.
```
User message: the image, then `List the food items visible in this fridge photo.`

Tool schema:
```json
{
  "type": "object",
  "properties": {
    "ingredients": {
      "type": "array",
      "items": {
        "type": "object",
        "properties": {
          "name": {
            "type": "string"
          },
          "quantity": {
            "type": "string"
          },
          "confidence": {
            "type": "number",
            "minimum": 0,
            "maximum": 1
          },
          "expiring": {
            "type": "boolean"
          }
        },
        "required": [
          "name",
          "confidence"
        ]
      }
    }
  },
  "required": [
    "ingredients"
  ]
}
```

## Call 2: meal generation (`POST /api/generate`)

**Input:** the user-edited ingredient list, appliance keys, ranked priorities, time limit, allergies, and meal names to avoid.
**Output:** `suggest_meals` tool call → up to 3 meals `{name, prep_minutes, appliances_used, ingredients, steps, why, safety_note}`.

System prompt:
```
You suggest quick meals for a college student living in a dorm room.
The student only has the appliances listed and the ingredients listed, plus these pantry basics:
black pepper, butter, chili flakes, cooking oil, garlic powder, honey, hot sauce, instant rice, ketchup, microwave rice, oil, olive oil, pepper, red pepper flakes, salt, soy sauce, sugar, vegetable oil, water.

Hard rules (every meal is checked automatically and rejected if it breaks one):
1. Use ONLY the listed ingredients and pantry basics. Do not add anything else, not even garnishes.
2. Use ONLY the listed appliances. Never use an oven, stove, grill, or blender unless listed.
   Put the appliance keys you use in appliances_used, or ["none"] for a no-cook meal.
3. prep_minutes must be at or under the time limit.
4. If a meal uses raw eggs, meat, poultry or fish, a step or the safety_note must say how to tell it
   is fully cooked (e.g. "until the eggs are fully set", "until steaming hot and no pink remains, 165F").
5. Respect the allergies. Leave out any ingredient the student is allergic to.
Write short, numbered-style steps a beginner can follow. "why" is one sentence on how the meal fits the
student's priorities.
```

Example user message (built by `prompts.generate_user`):
```
Ingredients in the fridge:
- eggs (6)
- spinach [EXPIRING SOON]
- cheddar cheese

Appliances (use these keys in appliances_used): microwave (Microwave)

Priorities, most important first: 1. Use expiring food first, 2. Fast to make

Time limit: 15 minutes

Allergies: none

Suggest 3 meals.
```

### Retry with feedback
`pipeline.py` parses each meal and runs the 5 checks in `validator.py`. If any fail and attempts remain
(`MAX_GENERATION_ATTEMPTS`, default 2), the same request is sent again with the violations appended:
```
Your previous answer broke these rules. Return 3 meals again, fixing every problem (replace a meal if it cannot be fixed):
- Loaded fridge scramble: [equipment] uses 'stove', which the student does not have
```

Tool schema:
```json
{
  "type": "object",
  "properties": {
    "meals": {
      "type": "array",
      "minItems": 1,
      "maxItems": 3,
      "items": {
        "type": "object",
        "properties": {
          "name": {
            "type": "string"
          },
          "prep_minutes": {
            "type": "integer"
          },
          "appliances_used": {
            "type": "array",
            "items": {
              "type": "string"
            }
          },
          "ingredients": {
            "type": "array",
            "items": {
              "type": "object",
              "properties": {
                "name": {
                  "type": "string"
                },
                "amount": {
                  "type": "string"
                }
              },
              "required": [
                "name"
              ]
            }
          },
          "steps": {
            "type": "array",
            "items": {
              "type": "string"
            }
          },
          "why": {
            "type": "string"
          },
          "safety_note": {
            "type": "string"
          }
        },
        "required": [
          "name",
          "prep_minutes",
          "appliances_used",
          "ingredients",
          "steps"
        ]
      }
    }
  },
  "required": [
    "meals"
  ]
}
```

## Why the rules are checked in code, not just in the prompt
The prompt states every rule, but the model still breaks them sometimes. It adds a garnish that isn't in the fridge,
says "skillet" when only a microwave was picked, or skips the cook-through line. The validator catches these
reliably. Each response reports `first_try_valid`, `violations_fixed` and `remaining_violations`, so how often the
model follows the rules on its own can be measured, and the retry's effect can be shown.

## Cost
Each call's `usage.input_tokens` / `output_tokens` from the API response is multiplied by
`PRICE_INPUT_PER_MTOK` / `PRICE_OUTPUT_PER_MTOK` from `.env` and returned as `usage.est_cost_usd`.

## Limitations
- The model can only list what is visible in the photo, and its names don't always match our labels ("strawberries" vs "berry").
- Allergies are passed in the prompt only. No code check yet.
- The validator matches keywords, so equipment described in unusual words can slip through.
- The food-safety check confirms a cook-through instruction exists. It doesn't check that the time or temperature is correct.
