# FridgeToDinner

CECS 451 term project, Group 9 (Kyler Sison, Huy Khuc, Kevin Luu, Kennedy Le)

A lot of students in the CSULB dorms only have a mini fridge and a microwave. The dining hall closes, you're hungry, and you've got some random leftovers but no idea what to make. FridgeToDinner lets you take a picture of your fridge and gives you three meals you can actually make with what's in there and the appliances you have.

How it works: you upload a photo, an AI model (Claude Haiku) lists the food it sees, and you fix anything it got wrong. Then you rank what you care about (fast, healthy, filling, or using stuff that's about to go bad) and it suggests three meals. Before you see them, every meal goes through our validator, which checks that it only uses food you have, only uses appliances you picked, fits your time limit, and tells you to fully cook any raw eggs or meat. If a meal breaks a rule, we send it back to the model with the reason and ask again.

## Setup

You need Python 3.10+.

```
git clone https://github.com/kylersison/FridgeToDinner
cd FridgeToDinner
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

(On Mac/Linux, activate with `source .venv/bin/activate` instead.)

Copy `.env.example` to `.env`. If you have an Anthropic API key, put it after `ANTHROPIC_API_KEY=`. If you don't, just leave it blank and the app runs in mock mode, which uses fake AI responses so you can still click through everything for free.

Run it:

```
uvicorn backend.app.main:app --reload
```

and go to http://localhost:8000.

In mock mode, the first batch of meals includes one that needs a stove on purpose, so you can see the validator catch it. Open "Validator & cost details" under the meals to see what got caught.

## Running a sample / tests

To get meals from the command line without the website:

```
python scripts/run_sample.py --photo data/photos/fridge_010.jpg
```

It prints the detected ingredients, the three meals, how many tries it took, what the validator caught, and roughly how much the API calls cost.

Tests (these run in mock mode, no key needed):

```
python -m pytest
```

## Evaluation

We labeled 10 fridge photos from Wikimedia Commons by hand (they're in `data/photos/`, with sources and licenses in `data/photos/SOURCES.md`). `eval/ground_truth.json` has what's actually in each one. To see how well the AI detects ingredients compared to our labels:

```
python scripts/eval_detection.py --truth eval/ground_truth.json
```

On our first live run it found 21 of the 41 labeled items (recall 0.51, precision 0.27, F1 0.35). A lot of the misses are naming differences, like it saying "strawberries" when we labeled "berry", so we're planning to clean up the labels and add real dorm fridge photos for Phase 3.

## Where things are

- `backend/app/main.py` is the server and the two API routes, `/api/detect` and `/api/generate`
- `backend/app/llm.py` calls the model and runs the validate-and-retry loop
- `backend/app/prompts.py` has the prompts and the JSON format we make the model answer in
- `backend/app/validator.py` has the meal rules
- `backend/app/image_utils.py` shrinks photos and strips location data before they get sent anywhere
- `backend/app/schemas.py`, `catalog.py`, `config.py` have the data models, appliance list, and settings
- `frontend/` is the website (plain HTML/CSS/JS)
- `scripts/` has the sample runner and the eval script
- `tests/` has the tests
- `docs/` has more detail on the architecture and the prompts

Settings like the model name and image size live in `.env`. See `.env.example` for all of them.

## What doesn't work yet

The allergy box gets passed to the model, but nothing actually checks it yet. The validator matches ingredient names by words, so it can miss things like "scallion" vs "green onion". Detection misses stuff hidden behind other things or in containers, which is why you can edit the list. Our test photos are stock images, which are a lot cleaner than a real dorm fridge.

Photos aren't saved anywhere, there are no accounts, and your API key stays in `.env`, which git ignores.
