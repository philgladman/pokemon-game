from __future__ import annotations

from pathlib import Path
from typing import Protocol

from backend.app.models.map import WorldDefinition
from backend.app.models.rendering import RetroMapResources, ThreeDMapResources
from backend.app.models.story import StoryDefinition


class GameSource(Protocol):
    """Renderer-neutral source boundary used by the authoritative runtime."""

    @property
    def root(self) -> Path: ...

    @property
    def revision(self) -> str: ...

    def build_world(self) -> WorldDefinition: ...

    def build_story(self) -> StoryDefinition: ...


class SourceAssetProvider(Protocol):
    def resolve_asset(self, category: str, name: str) -> Path: ...


class RetroResourceProvider(Protocol):
    def retro_resources(self, map_id: str) -> RetroMapResources: ...


class ThreeDResourceProvider(Protocol):
    def three_d_resources(self, map_id: str) -> ThreeDMapResources: ...


class ApplicationSource(
    GameSource,
    SourceAssetProvider,
    RetroResourceProvider,
    ThreeDResourceProvider,
    Protocol,
):
    """The app composition root combines logical and presentation providers."""
