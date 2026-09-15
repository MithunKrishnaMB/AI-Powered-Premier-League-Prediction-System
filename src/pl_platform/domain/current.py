"""Provider-neutral current-season football observations and field policy."""

from datetime import UTC, date, datetime, time, timedelta
from enum import StrEnum
from typing import Annotated, Final, Literal, Self
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from pl_platform.domain.fixtures import (
    FixtureScore,
    FixtureStatus,
    KickoffPrecision,
    MatchOutcome,
)

Identifier = Annotated[str, Field(pattern=r"^[a-z0-9]+(?:[a-z0-9_-]*[a-z0-9])?$")]
ExternalIdentifier = Annotated[str, Field(min_length=1, max_length=512)]
NonNegativeInt = Annotated[int, Field(strict=True, ge=0)]
PositiveInt = Annotated[int, Field(strict=True, ge=1)]
DATE_ONLY_BATCH_POLICY: Final[Literal["whole_source_local_date"]] = (
    "whole_source_local_date"
)
KNOWLEDGE_TIME_POLICY: Final[Literal["response_retrieved_at"]] = "response_retrieved_at"


def _must_be_utc(value: datetime, field_name: str) -> None:
    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise ValueError(f"{field_name} must be timezone-aware UTC")


class _ProviderIdentifier(BaseModel):
    """Opaque provider identity that must never substitute for canonical identity."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    source_id: Identifier
    external_id: ExternalIdentifier

    @field_validator("external_id")
    @classmethod
    def external_id_must_be_exact_and_printable(cls, value: str) -> str:
        if value != value.strip() or any(ord(character) < 32 for character in value):
            raise ValueError("provider external ID must be trimmed and printable")
        return value


class ProviderCompetitionIdentifier(_ProviderIdentifier):
    """Provider-owned competition identity."""


class ProviderSeasonIdentifier(_ProviderIdentifier):
    """Provider-owned season identity."""


class ProviderTeamIdentifier(_ProviderIdentifier):
    """Provider-owned team identity."""


class ProviderFixtureIdentifier(_ProviderIdentifier):
    """Provider-owned fixture identity."""


class ProviderPlayerIdentifier(_ProviderIdentifier):
    """Provider-owned player identity, separate from reviewed canonical UUIDs."""


class ProviderSquadIdentifier(_ProviderIdentifier):
    """Provider-owned squad identity, separate from canonical season/team scope."""


class CurrentSeasonScope(BaseModel):
    """Explicit canonical expectation paired with provider-owned scope identity."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    competition_id: Identifier
    season_id: Annotated[str, Field(pattern=r"^\d{4}-\d{4}$")]
    provider_competition_id: ProviderCompetitionIdentifier
    provider_season_id: ProviderSeasonIdentifier

    @model_validator(mode="after")
    def provider_scope_must_use_one_source(self) -> Self:
        if self.provider_competition_id.source_id != self.provider_season_id.source_id:
            raise ValueError("provider competition and season must use one source")
        start_year, end_year = (int(value) for value in self.season_id.split("-"))
        if end_year != start_year + 1:
            raise ValueError("season ID must span exactly one year")
        return self

    @property
    def source_id(self) -> str:
        return self.provider_competition_id.source_id


class ProviderKickoff(BaseModel):
    """UTC kickoff plus the provider's explicit source-local precision boundary."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kickoff_at: datetime
    precision: KickoffPrecision
    source_timezone: str = Field(min_length=1)
    source_local_date: date

    @model_validator(mode="after")
    def kickoff_must_preserve_source_precision(self) -> Self:
        _must_be_utc(self.kickoff_at, "kickoff_at")
        try:
            source_zone = ZoneInfo(self.source_timezone)
        except ZoneInfoNotFoundError as exc:
            raise ValueError("source_timezone must be a known IANA timezone") from exc
        if self.precision is KickoffPrecision.EXACT:
            if self.kickoff_at.astimezone(source_zone).date() != self.source_local_date:
                raise ValueError("exact kickoff does not match its source-local date")
            return self
        expected_anchor = datetime.combine(
            self.source_local_date,
            time(12, 0),
            tzinfo=source_zone,
        ).astimezone(UTC)
        if self.kickoff_at != expected_anchor:
            raise ValueError("date-only kickoff must use the source-local noon anchor")
        return self


class CurrentSeasonTeam(BaseModel):
    """Unresolved provider team observation without a canonical identity."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    provider_team_id: ProviderTeamIdentifier
    provider_name: str = Field(min_length=1)
    short_name: str | None = Field(default=None, min_length=1)
    team_code: str | None = Field(default=None, min_length=1)
    country_code: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")


class CurrentSeasonFixture(BaseModel):
    """Provider-neutral scheduled-fixture observation without result data."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    provider_fixture_id: ProviderFixtureIdentifier
    home_provider_team_id: ProviderTeamIdentifier
    away_provider_team_id: ProviderTeamIdentifier
    kickoff: ProviderKickoff
    status: FixtureStatus
    matchweek: PositiveInt | None = None
    venue: str | None = Field(default=None, min_length=1)
    referee: str | None = Field(default=None, min_length=1)
    provider_updated_at: datetime | None = None

    @model_validator(mode="after")
    def fixture_references_must_be_consistent(self) -> Self:
        sources = {
            self.provider_fixture_id.source_id,
            self.home_provider_team_id.source_id,
            self.away_provider_team_id.source_id,
        }
        if len(sources) != 1:
            raise ValueError("fixture and team identifiers must use one source")
        if self.home_provider_team_id == self.away_provider_team_id:
            raise ValueError("home and away provider teams must differ")
        if self.provider_updated_at is not None:
            _must_be_utc(self.provider_updated_at, "provider_updated_at")
        return self


class FixtureStatusObservation(BaseModel):
    """One score-free provider fixture-state observation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    provider_fixture_id: ProviderFixtureIdentifier
    status: FixtureStatus
    observed_at: datetime
    provider_updated_at: datetime | None = None

    @model_validator(mode="after")
    def timestamps_must_be_utc(self) -> Self:
        _must_be_utc(self.observed_at, "observed_at")
        if self.provider_updated_at is not None:
            _must_be_utc(self.provider_updated_at, "provider_updated_at")
        return self


class CompletedFixtureResult(BaseModel):
    """Official provider result; provisional and abandoned scores are excluded."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    provider_fixture_id: ProviderFixtureIdentifier
    home_provider_team_id: ProviderTeamIdentifier
    away_provider_team_id: ProviderTeamIdentifier
    status: Literal[FixtureStatus.FINISHED] = FixtureStatus.FINISHED
    full_time_score: FixtureScore
    outcome: MatchOutcome
    completed_at: datetime | None = None

    @model_validator(mode="after")
    def completed_result_must_be_official_and_consistent(self) -> Self:
        sources = {
            self.provider_fixture_id.source_id,
            self.home_provider_team_id.source_id,
            self.away_provider_team_id.source_id,
        }
        if len(sources) != 1:
            raise ValueError("result and team identifiers must use one source")
        if self.home_provider_team_id == self.away_provider_team_id:
            raise ValueError("home and away provider teams must differ")
        if self.outcome is not self.full_time_score.outcome:
            raise ValueError("completed-result outcome does not match its score")
        if self.completed_at is not None:
            _must_be_utc(self.completed_at, "completed_at")
        return self


class StandingRow(BaseModel):
    """One internally reconciled row from an authoritative standings snapshot."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    provider_team_id: ProviderTeamIdentifier
    position: PositiveInt
    played: NonNegativeInt
    won: NonNegativeInt
    drawn: NonNegativeInt
    lost: NonNegativeInt
    goals_for: NonNegativeInt
    goals_against: NonNegativeInt
    goal_difference: Annotated[int, Field(strict=True)]
    points: NonNegativeInt
    points_adjustment: Annotated[int, Field(strict=True)] = 0

    @model_validator(mode="after")
    def standing_totals_must_reconcile(self) -> Self:
        if self.played != self.won + self.drawn + self.lost:
            raise ValueError("standing played count does not match results")
        if self.goal_difference != self.goals_for - self.goals_against:
            raise ValueError("standing goal difference does not reconcile")
        expected_points = 3 * self.won + self.drawn + self.points_adjustment
        if self.points != expected_points:
            raise ValueError("standing points do not reconcile")
        return self


class SquadMembershipKind(StrEnum):
    PERMANENT = "permanent"
    LOAN = "loan"
    ACADEMY = "academy"


class CurrentSeasonPlayer(BaseModel):
    """Unresolved current player metadata; identity resolution is explicit."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    provider_player_id: ProviderPlayerIdentifier
    provider_name: str = Field(min_length=1)
    date_of_birth: date | None = None
    nationality_code: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")
    provider_position: str | None = Field(default=None, min_length=1)


class CurrentSquadMembership(BaseModel):
    """One current registration with explicit employment and eligibility dates."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    provider_player_id: ProviderPlayerIdentifier
    provider_player_name: str = Field(min_length=1)
    kind: SquadMembershipKind
    effective_from: date
    effective_to: date | None = None
    registered_from: date
    registered_to: date | None = None
    loan_parent_provider_team_id: ProviderTeamIdentifier | None = None
    shirt_number: PositiveInt | None = None

    @model_validator(mode="after")
    def membership_window_must_be_consistent(self) -> Self:
        if self.effective_to is not None and self.effective_to < self.effective_from:
            raise ValueError("membership effective range is reversed")
        if self.registered_from < self.effective_from or (
            self.registered_to is not None and self.registered_to < self.registered_from
        ):
            raise ValueError("registration range is outside chronological order")
        if (
            self.effective_to is not None
            and self.registered_to is not None
            and self.registered_to > self.effective_to
        ):
            raise ValueError("registration cannot outlive effective membership")
        if self.kind is SquadMembershipKind.LOAN:
            if self.loan_parent_provider_team_id is None:
                raise ValueError("loan membership requires its parent team")
        elif self.loan_parent_provider_team_id is not None:
            raise ValueError("only loan membership may declare a parent team")
        return self


class CurrentSeasonSquad(BaseModel):
    """Provider squad snapshot for one team at one explicit source-local date."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    provider_squad_id: ProviderSquadIdentifier
    provider_team_id: ProviderTeamIdentifier
    as_of_date: date
    memberships: tuple[CurrentSquadMembership, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def squad_must_be_scoped_ordered_and_current(self) -> Self:
        sources = {self.provider_squad_id.source_id, self.provider_team_id.source_id}
        sources.update(
            membership.provider_player_id.source_id for membership in self.memberships
        )
        sources.update(
            membership.loan_parent_provider_team_id.source_id
            for membership in self.memberships
            if membership.loan_parent_provider_team_id is not None
        )
        if len(sources) != 1:
            raise ValueError("squad, team and player identifiers must use one source")
        keys = tuple(
            membership.provider_player_id.external_id for membership in self.memberships
        )
        if keys != tuple(sorted(set(keys))):
            raise ValueError("squad memberships must be unique and ordered")
        for membership in self.memberships:
            if membership.registered_from > self.as_of_date or (
                membership.registered_to is not None
                and membership.registered_to < self.as_of_date
            ):
                raise ValueError("squad membership is not registered on as-of date")
            if (
                membership.loan_parent_provider_team_id is not None
                and membership.loan_parent_provider_team_id == self.provider_team_id
            ):
                raise ValueError("loan parent and registered team must differ")
        return self


class FieldAuthority(StrEnum):
    AUTHORITATIVE = "authoritative"
    OPTIONAL = "optional"
    RETAINED_ONLY = "retained_only"


class PredictorUsePolicy(StrEnum):
    CONTROL_OR_IDENTITY_ONLY = "control_or_identity_only"
    PRIOR_STATE_AFTER_KNOWLEDGE_CUTOFF = "prior_state_after_knowledge_cutoff"
    REVIEWED_SCHEMA_REQUIRED = "reviewed_schema_required"
    PROHIBITED = "prohibited"


class ProviderFieldPolicy(BaseModel):
    """Classification of a provider field family and its predictor boundary."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    field_path: str = Field(min_length=1)
    authority: FieldAuthority
    predictor_use: PredictorUsePolicy
    notes: str = Field(min_length=1)


CURRENT_PROVIDER_FIELD_POLICIES: Final[tuple[ProviderFieldPolicy, ...]] = (
    ProviderFieldPolicy(
        field_path="completed_result.full_time_score",
        authority=FieldAuthority.AUTHORITATIVE,
        predictor_use=PredictorUsePolicy.PRIOR_STATE_AFTER_KNOWLEDGE_CUTOFF,
        notes="A final result may update only later fixture batches.",
    ),
    ProviderFieldPolicy(
        field_path="fixture.kickoff",
        authority=FieldAuthority.AUTHORITATIVE,
        predictor_use=PredictorUsePolicy.CONTROL_OR_IDENTITY_ONLY,
        notes="Kickoff controls chronology and never grants feature eligibility.",
    ),
    ProviderFieldPolicy(
        field_path="fixture.status",
        authority=FieldAuthority.AUTHORITATIVE,
        predictor_use=PredictorUsePolicy.PROHIBITED,
        notes="Same-fixture and post-cutoff states are not predictors.",
    ),
    ProviderFieldPolicy(
        field_path="optional.descriptive_metadata",
        authority=FieldAuthority.OPTIONAL,
        predictor_use=PredictorUsePolicy.REVIEWED_SCHEMA_REQUIRED,
        notes="Round, venue, referee, codes and timestamps require schema review.",
    ),
    ProviderFieldPolicy(
        field_path="player.descriptive_metadata",
        authority=FieldAuthority.OPTIONAL,
        predictor_use=PredictorUsePolicy.REVIEWED_SCHEMA_REQUIRED,
        notes="Birth date, nationality and provider position are not predictors.",
    ),
    ProviderFieldPolicy(
        field_path="player.identifiers_and_name",
        authority=FieldAuthority.AUTHORITATIVE,
        predictor_use=PredictorUsePolicy.CONTROL_OR_IDENTITY_ONLY,
        notes="Player identity requires an exact reviewed registry mapping.",
    ),
    ProviderFieldPolicy(
        field_path="provider.identifiers",
        authority=FieldAuthority.AUTHORITATIVE,
        predictor_use=PredictorUsePolicy.CONTROL_OR_IDENTITY_ONLY,
        notes="Provider identity is separate from canonical identity.",
    ),
    ProviderFieldPolicy(
        field_path="provider.team_name",
        authority=FieldAuthority.AUTHORITATIVE,
        predictor_use=PredictorUsePolicy.CONTROL_OR_IDENTITY_ONLY,
        notes="Names are inputs to explicit reviewed alias resolution only.",
    ),
    ProviderFieldPolicy(
        field_path="response.unmodeled_fields",
        authority=FieldAuthority.RETAINED_ONLY,
        predictor_use=PredictorUsePolicy.PROHIBITED,
        notes="Unmodeled fields survive only in exact response bytes.",
    ),
    ProviderFieldPolicy(
        field_path="squad.registration_membership",
        authority=FieldAuthority.AUTHORITATIVE,
        predictor_use=PredictorUsePolicy.PRIOR_STATE_AFTER_KNOWLEDGE_CUTOFF,
        notes="Membership may affect only later batches after reviewed feature work.",
    ),
    ProviderFieldPolicy(
        field_path="squad.shirt_number",
        authority=FieldAuthority.OPTIONAL,
        predictor_use=PredictorUsePolicy.PROHIBITED,
        notes="Shirt number is retained context and not an approved predictor.",
    ),
    ProviderFieldPolicy(
        field_path="standings.snapshot",
        authority=FieldAuthority.AUTHORITATIVE,
        predictor_use=PredictorUsePolicy.REVIEWED_SCHEMA_REQUIRED,
        notes="Provider standings are reconciliation data, not schema-v2 predictors.",
    ),
    ProviderFieldPolicy(
        field_path="wagering.betting_odds",
        authority=FieldAuthority.RETAINED_ONLY,
        predictor_use=PredictorUsePolicy.PROHIBITED,
        notes="Odds and bookmaker markets remain outside the predictor schema.",
    ),
)
