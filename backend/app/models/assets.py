from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field, model_validator

from .common import StrictModel

Color = Annotated[str, Field(pattern=r"^#[0-9a-fA-F]{6}$")]


class PrimitiveAsset(StrictModel):
    type: Literal["primitive"] = "primitive"
    shape: Literal["flat", "tree", "box", "capsule"]
    color: Color
    secondary_color: Color | None = None
    scale: list[float] = Field(default_factory=lambda: [1.0, 1.0, 1.0], min_length=3, max_length=3)


class GltfAsset(StrictModel):
    type: Literal["gltf"] = "gltf"
    url: str = Field(pattern=r"^/assets/[a-zA-Z0-9_./-]+\.glb$")
    scale: list[float] = Field(default_factory=lambda: [1.0, 1.0, 1.0], min_length=3, max_length=3)
    fallback: PrimitiveAsset


AssetSource = Annotated[PrimitiveAsset | GltfAsset, Field(discriminator="type")]


class AppearanceDefinition(StrictModel):
    id: str = Field(pattern=r"^[a-z][a-z0-9_.-]*$")
    source: AssetSource
    base_color: Color | None = None


class AssetManifest(StrictModel):
    appearances: list[AppearanceDefinition]

    @model_validator(mode="after")
    def ids_are_unique(self) -> AssetManifest:
        ids = [appearance.id for appearance in self.appearances]
        if len(ids) != len(set(ids)):
            raise ValueError("appearance ids must be unique")
        return self

    def as_registry(self) -> dict[str, AppearanceDefinition]:
        return {appearance.id: appearance for appearance in self.appearances}
