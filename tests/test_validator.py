from backend.app.schemas import GenerateRequest, Ingredient, Meal, MealIngredient
from backend.app.validator import check_meal, names_match, normalize


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
