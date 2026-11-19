"""Fixed vocabularies: appliances, priorities, pantry basics and food-safety keywords."""

# Appliances a student can pick. The key is what the API and validator use.
APPLIANCES: dict[str, str] = {
    "microwave": "Microwave",
    "electric_kettle": "Electric kettle",
    "rice_cooker": "Rice cooker",
    "toaster": "Toaster",
    "air_fryer": "Air fryer",
    "hot_plate": "Hot plate / induction burner",
}

# Equipment words that imply an appliance. Used to catch steps that sneak in
# equipment the student does not own. "none" means always allowed.
EQUIPMENT_KEYWORDS: dict[str, list[str]] = {
    "microwave": ["microwave"],
    "electric_kettle": ["kettle"],
    "rice_cooker": ["rice cooker"],
    "toaster": ["toaster", "toast "],
    "air_fryer": ["air fryer", "air-fryer", "airfryer"],
    "hot_plate": ["hot plate", "burner", "stovetop", "stove", "skillet", "frying pan", "saucepan", "pan over"],
    # Never available in a dorm room:
    "_oven": ["oven", "bake at", "preheat", "broil"],
    "_grill": ["grill"],
    "_blender": ["blender", "food processor"],
}

PRIORITIES: dict[str, str] = {
    "speed": "Fast to make",
    "healthy": "Healthy",
    "filling": "Filling",
    "use_expiring": "Use expiring food first",
}

# Pantry basics a student is assumed to have; meals may use these without
# them appearing in the fridge list.
ALLOWED_BASICS: set[str] = {
    "salt", "pepper", "black pepper", "oil", "olive oil", "vegetable oil", "cooking oil",
    "water", "sugar", "soy sauce", "hot sauce", "ketchup", "instant rice", "microwave rice",
    "butter", "garlic powder", "chili flakes", "red pepper flakes", "honey",
}

# Raw animal proteins that need a cook-through/safety instruction.
RAW_PROTEIN_KEYWORDS: list[str] = [
    "egg", "chicken", "beef", "pork", "turkey", "ground meat", "sausage", "bacon",
    "fish", "salmon", "shrimp", "tuna steak",
]

SAFETY_KEYWORDS: list[str] = [
    "cooked through", "until set", "fully set", "until cooked", "no pink", "165", "160", "145", "internal temperature",
    "fully cooked", "steaming hot", "until firm", "opaque", "until the yolk",
]
