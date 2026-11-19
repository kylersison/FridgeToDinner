"""Request/response models shared by the API, the LLM layer and the validator."""

from typing import Literal

from pydantic import BaseModel, Field


class Ingredient(BaseModel):
    name: str = Field(..., description="Common grocery name, lowercase, e.g. 'eggs'")
    quantity: str = Field("", description="Rough amount, e.g. '2', 'half a bag'")
    confidence: float = Field(1.0, ge=0, le=1)
    expiring: bool = False


class DetectResponse(BaseModel):
    ingredients: list[Ingredient]
    usage: "Usage"
    mock: bool


class MealIngredient(BaseModel):
    name: str
    amount: str = ""


class Meal(BaseModel):
    name: str
    prep_minutes: int
    appliances_used: list[str]
    ingredients: list[MealIngredient]
    steps: list[str]
    why: str = Field("", description="One line on how it fits the priorities")
    safety_note: str = ""


class GenerateRequest(BaseModel):
    ingredients: list[Ingredient]
    appliances: list[str] = Field(..., min_length=1)
    priorities: list[Literal["speed", "healthy", "filling", "use_expiring"]] = Field(
        ..., min_length=1, description="Ranked, most important first"
    )
    max_prep_minutes: int = Field(20, ge=5, le=90)
    allergies: str = ""
    exclude_meals: list[str] = Field(default_factory=list, description="Names to avoid (regenerate)")


class Violation(BaseModel):
    meal: str
    rule: Literal["unknown_ingredient", "equipment", "prep_time", "food_safety", "schema"]
    detail: str


class Usage(BaseModel):
    input_tokens: int = 0
    output_tokens: int = 0
    calls: int = 0
    est_cost_usd: float = 0.0

    def add(self, other: "Usage") -> "Usage":
        return Usage(
            input_tokens=self.input_tokens + other.input_tokens,
            output_tokens=self.output_tokens + other.output_tokens,
            calls=self.calls + other.calls,
            est_cost_usd=round(self.est_cost_usd + other.est_cost_usd, 6),
        )


class GenerateResponse(BaseModel):
    meals: list[Meal]
    attempts: int
    first_try_valid: bool
    violations_fixed: list[Violation]
    remaining_violations: list[Violation]
    usage: Usage
    mock: bool


DetectResponse.model_rebuild()
