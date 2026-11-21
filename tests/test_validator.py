from backend.app.schemas import Meal, MealIngredient
from backend.app.validator import check_meal, check_meals, normalize

FRIDGE = ["eggs", "leftover white rice", "cheddar cheese", "bell pepper", "peanut butter", "onion"]


def meal(**kw) -> Meal:
    base = dict(name="Test", prep_minutes=10, appliances_used=["microwave"],
                ingredients=[MealIngredient(name="leftover white rice")],
                steps=["Microwave the rice for 2 minutes until steaming hot."])
    base.update(kw)
    return Meal(**base)


def ings(*names) -> list[MealIngredient]:
    return [MealIngredient(name=n) for n in names]


def rules(m: Meal, appliances=("microwave",), limit=20, fridge=FRIDGE):
    return {v.rule for v in check_meal(m, fridge, list(appliances), limit)}


# ---- normalize / matching

def test_normalize():
    assert normalize("2% Shredded Cheddar Cheese") == "cheddar cheese"
    assert normalize("Tomatoes") == "tomato"
    assert normalize("Eggs") == "egg"
    assert normalize("hummus") == "hummus"


def test_valid_meal_passes():
    assert rules(meal()) == set()


def test_basics_and_partial_names_allowed():
    m = meal(ingredients=ings("rice", "salt", "shredded cheddar", "soy sauce", "oil", "green onion"))
    assert rules(m) == set()


def test_unknown_ingredient_flagged():
    assert "unknown_ingredient" in rules(meal(ingredients=ings("chicken breast")))


def test_pantry_basic_does_not_excuse_a_different_food():
    # 'butter' is a basic, but peanut butter / bell pepper are not blanket-allowed
    assert "unknown_ingredient" in rules(meal(ingredients=ings("peanut butter")), fridge=["eggs"])
    assert "unknown_ingredient" in rules(meal(ingredients=ings("bell pepper")), fridge=["eggs"])


def test_different_product_not_matched():
    assert "unknown_ingredient" in rules(meal(ingredients=ings("chicken broth")), fridge=["chicken"])
    assert "unknown_ingredient" in rules(meal(ingredients=ings("peanut")), fridge=["peanut butter"])


def test_empty_fridge_still_allows_basics():
    assert rules(meal(ingredients=ings("salt", "water")), fridge=[]) == set()


# ---- appliances

def test_unselected_appliance_declared():
    assert "equipment" in rules(meal(appliances_used=["air_fryer"]))


def test_declared_name_formats_accepted():
    m = meal(appliances_used=["Hot plate"], steps=["Warm the rice on the hot plate until steaming hot."])
    assert "equipment" not in rules(m, appliances=("hot_plate",))
    assert "equipment" not in rules(meal(appliances_used=["none"]))
    assert "equipment" not in rules(meal(appliances_used=[]))


def test_stove_in_steps_flagged():
    m = meal(steps=["Heat oil in a frying pan on the stove.", "Add rice."])
    assert "equipment" in rules(m)


def test_stove_ok_when_hot_plate_selected():
    m = meal(appliances_used=["hot_plate"],
             steps=["Heat oil in a frying pan on the hot plate.", "Fry rice until steaming hot."])
    assert "equipment" not in rules(m, appliances=("hot_plate",))


def test_oven_never_allowed():
    m = meal(steps=["Preheat the oven to 400F.", "Bake rice."])
    assert "equipment" in rules(m, appliances=("microwave", "toaster", "hot_plate"))


def test_microwave_oven_is_just_the_microwave():
    assert "equipment" not in rules(meal(steps=["Place in the microwave oven for 1 minute."]))


def test_grilled_cheese_name_is_not_a_grill():
    m = meal(steps=["Make a grilled sandwich shape, then microwave 30 seconds."])
    assert "equipment" not in rules(m)


def test_air_fryer_may_preheat():
    m = meal(appliances_used=["air_fryer"], steps=["Preheat the air fryer to 380F.", "Cook 5 minutes."])
    assert "equipment" not in rules(m, appliances=("air_fryer",))
    # without an air fryer or oven, preheating is still flagged
    assert "equipment" in rules(meal(steps=["Preheat to 380F."]))


def test_pot_and_slow_cooker_flagged():
    assert "equipment" in rules(meal(steps=["Boil rice in a pot."]))
    assert "equipment" in rules(meal(steps=["Use the slow cooker for an hour."]))


# ---- time

def test_prep_time_limit():
    assert "prep_time" in rules(meal(prep_minutes=35), limit=20)
    assert "prep_time" not in rules(meal(prep_minutes=20), limit=20)


def test_nonpositive_prep_time_is_schema_violation():
    assert "schema" in rules(meal(prep_minutes=0))


# ---- food safety

def test_raw_egg_needs_safety_step():
    m = meal(ingredients=ings("eggs"), steps=["Crack eggs into a mug.", "Microwave 1 minute."])
    assert "food_safety" in rules(m)
    ok = meal(ingredients=ings("eggs"),
              steps=["Crack eggs into a mug.", "Microwave 30 seconds at a time until fully set."])
    assert "food_safety" not in rules(ok)


def test_safety_note_counts():
    m = meal(ingredients=ings("eggs"), steps=["Microwave the eggs."], safety_note="Cook until fully set.")
    assert "food_safety" not in rules(m)


def test_cooked_rice_does_not_hide_raw_egg():
    m = meal(ingredients=ings("eggs", "leftover white rice"), steps=["Microwave eggs with rice."])
    assert "food_safety" in rules(m)


def test_precooked_or_non_meat_names_skip_safety():
    fridge = ["cooked chicken", "eggplant", "canned tuna"]
    m = meal(ingredients=ings("cooked chicken", "eggplant", "canned tuna"),
             steps=["Microwave everything for 2 minutes."])
    assert "food_safety" not in rules(m, fridge=fridge)


def test_raw_chicken_flagged_and_temperature_accepted():
    fridge = ["chicken breast"]
    bad = meal(ingredients=ings("chicken breast"), steps=["Microwave chicken for 3 minutes."])
    assert "food_safety" in rules(bad, fridge=fridge)
    good = meal(ingredients=ings("chicken breast"),
                steps=["Microwave chicken until it reaches 165F inside."])
    assert "food_safety" not in rules(good, fridge=fridge)


# ---- shape / multi

def test_missing_steps_and_ingredients():
    r = rules(meal(steps=[], ingredients=[]))
    assert "schema" in r


def test_check_meals_collects_all():
    good, bad = meal(name="Good"), meal(name="Bad", prep_minutes=99)
    vs = check_meals([good, bad], FRIDGE, ["microwave"], 20)
    assert [v.meal for v in vs] == ["Bad"]
