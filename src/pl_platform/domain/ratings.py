"""Versioned provider-independent Elo contracts."""

from math import isclose
from typing import Annotated, Final, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

ELO_SCHEMA_VERSION: Final = 1

FiniteFloat = Annotated[float, Field(strict=True, allow_inf_nan=False)]
PositiveFloat = Annotated[float, Field(strict=True, gt=0, allow_inf_nan=False)]
Probability = Annotated[float, Field(strict=True, ge=0, le=1, allow_inf_nan=False)]


class EloParameters(BaseModel):
    """Reviewed constants governing initialization, prediction and updates."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = ELO_SCHEMA_VERSION
    initial_rating: PositiveFloat = 1500.0
    home_advantage: Annotated[
        float,
        Field(strict=True, ge=0, allow_inf_nan=False),
    ] = 65.0
    k_factor: PositiveFloat = 20.0
    rating_scale: PositiveFloat = 400.0
    season_retention: Probability = 0.75


class EloMatchPrediction(BaseModel):
    """Pre-match Elo state and expected result before a fixture batch updates."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = ELO_SCHEMA_VERSION
    home_rating: FiniteFloat
    away_rating: FiniteFloat
    home_expected_score: Probability
    away_expected_score: Probability

    @model_validator(mode="after")
    def expected_scores_must_be_complements(self) -> Self:
        if not isclose(
            self.home_expected_score + self.away_expected_score,
            1.0,
            abs_tol=1e-12,
        ):
            msg = "Elo expected scores must sum to one"
            raise ValueError(msg)
        return self
