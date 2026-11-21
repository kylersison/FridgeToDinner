from backend.app.schemas import GenerateRequest, Ingredient, Meal, MealIngredient
from backend.app.validator import check_meal, names_match, normalize, validate_meals


def req(**kw):
    base = dict(
        ingredients=[Ingredient(name="eggs"), Ingredient(name="cheddar cheese"), Ingredient(name="spinach")],
        appliances=["microwave"],
        priorities=["speed"],
        max_prep_minutes=15,
    )
    base.update(kw)
    return GenerateRequest(**base)


def meal(**kw):
    base = dict(
        name="Mug omelet",
        prep_minutes=5,
        appliances_used=["microwave"],
        ingredients=[MealIngredient(name="eggs"), MealIngredient(name="cheese"), MealIngredient(name="salt")],
        steps=["Whisk eggs in a mug.", "Microwave 90 seconds until the eggs are fully set."],
    )
    base.update(kw)
    return Meal(**base)


def rules(violations):
    return sorted(v.rule for v in violations)


def test_normalize():
    assert normalize("Eggs") == "egg"
    assert normalize("Tomatoes") == "tomato"
    assert normalize("tomatos") == "tomato"
    assert normalize("Frozen Berries") == "frozen berry"
    assert normalize("Mayonnaise") == "mayo"
    assert normalize("hummus") == "hummus"
    assert normalize("Milk (1 gallon)") == "milk"


def test_names_match():
    assert names_match("cheese", "cheddar cheese")
    assert not names_match("chicken", "cheddar cheese")


def test_valid_meal_passes():
    assert check_meal(meal(), req()) == []


def test_unknown_ingredient():
    m = meal(ingredients=[MealIngredient(name="eggs"), MealIngredient(name="bacon")])
    assert "unknown_ingredient" in rules(check_meal(m, req()))


def test_equipment_declared_and_in_steps():
    m = meal(appliances_used=["oven"], steps=["Preheat the oven to 400F.", "Bake until eggs are fully set."])
    assert rules(check_meal(m, req())).count("equipment") >= 2


def test_microwave_oven_phrase_is_not_an_oven():
    m = meal(steps=["Heat in the microwave oven until the eggs are fully set."])
    assert check_meal(m, req()) == []


def test_preheat_air_fryer_is_fine():
    m = meal(appliances_used=["air_fryer"], steps=["Preheat the air fryer.", "Cook until eggs are fully set."])
    assert check_meal(m, req(appliances=["air_fryer"])) == []


def test_prep_time():
    assert rules(check_meal(meal(prep_minutes=40), req())) == ["prep_time"]


def test_food_safety():
    m = meal(steps=["Whisk eggs in a mug.", "Microwave 90 seconds."])
    assert rules(check_meal(m, req())) == ["food_safety"]


def test_eggplant_is_not_egg():
    r = req(ingredients=[Ingredient(name="eggplant")])
    m = meal(ingredients=[MealIngredient(name="eggplant")], steps=["Slice and microwave 3 minutes."])
    assert check_meal(m, r) == []


# ---------------------------------------------------------------- extra edge cases

def ing(*names):
    return [MealIngredient(name=n) for n in names]


def run(m, fridge=("eggs", "leftover white rice", "cheddar cheese", "bell pepper", "peanut butter"),
        appliances=("microwave",), limit=20):
    r = GenerateRequest(ingredients=[Ingredient(name=n) for n in fridge], appliances=list(appliances),
                        priorities=["speed"], max_prep_minutes=limit)
    return check_meal(m, r)


def rule_set(m, **kw):
    return {v.rule for v in run(m, **kw)}


RICE = dict(name="Test", prep_minutes=10, appliances_used=["microwave"],
            ingredients=ing("leftover white rice"),
            steps=["Microwave the rice for 2 minutes until steaming hot."])


def rice(**kw):
    return Meal(**{**RICE, **kw})


def test_alias_and_parenthetical_fridge_names():
    m = rice(ingredients=ing("scallion", "milk"))
    assert rule_set(m, fridge=("green onion", "Milk (1 gallon)")) == set()


def test_basics_and_partial_names_allowed():
    m = rice(ingredients=ing("rice", "salt", "shredded cheddar", "soy sauce", "oil", "green onion"))
    assert rule_set(m, fridge=("leftover white rice", "cheddar cheese", "onion")) == set()


def test_pantry_basic_does_not_excuse_a_different_food():
    assert "unknown_ingredient" in rule_set(rice(ingredients=ing("peanut butter")), fridge=("eggs",))
    assert "unknown_ingredient" in rule_set(rice(ingredients=ing("bell pepper")), fridge=("eggs",))


def test_different_product_not_matched():
    assert "unknown_ingredient" in rule_set(rice(ingredients=ing("chicken broth")), fridge=("chicken",))
    assert "unknown_ingredient" in rule_set(rice(ingredients=ing("peanut")), fridge=("peanut butter",))


def test_empty_fridge_still_allows_basics():
    assert rule_set(rice(ingredients=ing("salt", "water")), fridge=()) == set()


def test_declared_appliance_formats():
    m = rice(appliances_used=["Hot plate"], steps=["Warm the rice on the hot plate until steaming hot."])
    assert "equipment" not in rule_set(m, appliances=("hot_plate",))
    assert "equipment" not in rule_set(rice(appliances_used=[]))
    assert "equipment" in rule_set(rice(appliances_used=["air_fryer"]))


def test_grilled_is_not_a_grill():
    assert "equipment" not in rule_set(rice(steps=["Make a grilled shape, then microwave 30 seconds."]))


def test_pot_and_slow_cooker_flagged():
    assert "equipment" in rule_set(rice(steps=["Boil rice in a pot."]))
    assert "equipment" in rule_set(rice(steps=["Use the slow cooker for an hour."]))


def test_preheat_without_owned_appliance_flagged():
    assert "equipment" in rule_set(rice(steps=["Preheat to 380F."]))


def test_nonpositive_prep_time_is_schema_violation():
    assert "schema" in rule_set(rice(prep_minutes=0))


def test_cooked_rice_does_not_hide_raw_egg():
    m = rice(ingredients=ing("eggs", "leftover white rice"), steps=["Microwave eggs with rice."])
    assert "food_safety" in rule_set(m)


def test_safety_note_counts():
    m = rice(ingredients=ing("eggs"), steps=["Microwave the eggs."], safety_note="Cook until fully set.")
    assert "food_safety" not in rule_set(m)


def test_precooked_or_non_meat_names_skip_safety():
    fridge = ("cooked chicken", "eggplant", "canned tuna")
    m = rice(ingredients=ing(*fridge), steps=["Microwave everything for 2 minutes."])
    assert "food_safety" not in rule_set(m, fridge=fridge)


def test_raw_chicken_flagged_and_temperature_accepted():
    bad = rice(ingredients=ing("chicken breast"), steps=["Microwave chicken for 3 minutes."])
    assert "food_safety" in rule_set(bad, fridge=("chicken breast",))
    good = rice(ingredients=ing("chicken breast"), steps=["Microwave chicken until it reaches 165F."])
    assert "food_safety" not in rule_set(good, fridge=("chicken breast",))


def test_empty_steps_or_ingredients():
    assert "schema" in rule_set(rice(steps=[]))
    assert "schema" in rule_set(rice(ingredients=[]))


def test_validate_meals_collects_all():
    r = req()
    vs = validate_meals([meal(), meal(name="Slow", prep_minutes=99)], r)
    assert [v.meal for v in vs] == ["Slow"]
