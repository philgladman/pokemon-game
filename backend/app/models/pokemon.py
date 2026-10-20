from __future__ import annotations

from pydantic import ConfigDict, Field

from .common import StrictModel


class SpeciesDefinition(StrictModel):
    model_config = ConfigDict(frozen=True)
    id: int = Field(gt=0, le=255)
    constant: str = Field(pattern=r"^[A-Z0-9_]+$")
    name: str = Field(min_length=1)


class PartyMember(StrictModel):
    species_id: int = Field(gt=0, le=255)
    name: str = Field(min_length=1)
    level: int = Field(ge=1, le=100)
