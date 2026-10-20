from __future__ import annotations

import re
from pathlib import Path
from typing import Literal

from backend.app.engine.text import normalize_source_name
from backend.app.models.common import Direction, Position
from backend.app.models.map import (
    BackgroundEvent,
    MapConnection,
    MapDefinition,
    NPCDefinition,
    SourceProvenance,
    TextInteraction,
    WarpDefinition,
    WorldDefinition,
)
from backend.app.models.rendering import RetroMapResources, SourceAsset, ThreeDMapResources
from backend.app.models.story import StoryDefinition

from .pallet_story import build_pallet_story
from .parsers import (
    ParseError,
    expand_blocks,
    expand_collision_tiles,
    parse_blocks,
    parse_collision_sets,
    parse_dimensions,
    parse_direct_text,
    parse_header,
    parse_incbin_aliases,
    parse_initial_visibility,
    parse_map_metadata,
    parse_map_objects,
    parse_new_game_warp,
    parse_sprite_assets,
    source_facing,
)
from .parsers.maps import ParsedMapMetadata
from .revision import read_git_revision, validate_clean_checkout

REPOSITORY_URL = "https://github.com/pret/pokered"
PINNED_REVISION = "af519899719f0754965776faac0e836a3b906e6d"
PINNED_TREE = "eacec23e007698e3e583be8131945cdc08c35f17"
SUPPORTED_MAPS = (
    "PalletTown",
    "RedsHouse1F",
    "RedsHouse2F",
    "BluesHouse",
    "OaksLab",
)
SUPPORTED_MAP_CONSTANTS = {
    "PALLET_TOWN",
    "REDS_HOUSE_1F",
    "REDS_HOUSE_2F",
    "BLUES_HOUSE",
    "OAKS_LAB",
}


class PokeredSourceError(RuntimeError):
    """A clear startup failure for missing or unsupported upstream source."""


class PokeredSource:
    """Reads the selected Pallet maps directly from a pret/pokered checkout."""

    def __init__(
        self,
        root: Path,
        *,
        player_name: str = "RED",
        rival_name: str = "BLUE",
        expected_revision: str = PINNED_REVISION,
        expected_tree: str = PINNED_TREE,
    ) -> None:
        self._root = root.resolve()
        self._revision: str | None = None
        self._expected_revision = expected_revision
        self._expected_tree = expected_tree
        self._integrity_validated = False
        self._world: WorldDefinition | None = None
        self._story: StoryDefinition | None = None
        self._asset_allowlist: dict[tuple[str, str], Path] = {}
        self._retro_resources: dict[str, RetroMapResources] = {}
        self._three_d_resources: dict[str, ThreeDMapResources] = {}
        self._text_variables = {
            "PLAYER": normalize_source_name(player_name, "RED"),
            "RIVAL": normalize_source_name(rival_name, "BLUE"),
        }

    @property
    def root(self) -> Path:
        return self._root

    @property
    def revision(self) -> str:
        self._resolve_revision()
        if not self._integrity_validated:
            self._validate_integrity()
        assert self._revision is not None
        return self._revision

    def build_world(self) -> WorldDefinition:
        if self._world is not None:
            return self._world
        try:
            self._world = self._build_world()
        except (OSError, ParseError, ValueError) as error:
            raise PokeredSourceError(
                f"unable to build runtime from pret/pokered: {error}"
            ) from error
        return self._world

    def build_story(self) -> StoryDefinition:
        if self._story is not None:
            return self._story
        world = self.build_world()
        try:
            self._story = build_pallet_story(self._root, self.revision, world)
        except (OSError, ParseError, ValueError) as error:
            raise PokeredSourceError(
                f"unable to build Pallet story from pret/pokered: {error}"
            ) from error
        return self._story

    def resolve_asset(self, category: str, name: str) -> Path:
        if self._world is None:
            self.build_world()
        try:
            return self._asset_allowlist[(category, name)]
        except KeyError as error:
            raise PokeredSourceError(
                f"source asset is not allowlisted: {category}/{name}"
            ) from error

    def retro_resources(self, map_id: str) -> RetroMapResources:
        if self._world is None:
            self.build_world()
        try:
            return self._retro_resources[map_id]
        except KeyError as error:
            raise PokeredSourceError(f"retro resources are unavailable for map {map_id}") from error

    def three_d_resources(self, map_id: str) -> ThreeDMapResources:
        if self._world is None:
            self.build_world()
        try:
            return self._three_d_resources[map_id]
        except KeyError as error:
            raise PokeredSourceError(f"3D resources are unavailable for map {map_id}") from error

    def _build_world(self) -> WorldDefinition:
        self._validate_root()
        self._validate_integrity()
        dimensions = self._read_text("constants/map_constants.asm")
        map_metadata = parse_map_metadata(dimensions)
        collisions = parse_collision_sets(self._read_text("data/tilesets/collision_tile_ids.asm"))
        tileset_sources = self._read_text("gfx/tilesets.asm")
        tileset_images = parse_incbin_aliases(tileset_sources, "GFX", "gfx/tilesets")
        blocksets = parse_incbin_aliases(tileset_sources, "Block", "gfx/blocksets")
        visibility = parse_initial_visibility(self._read_text("data/maps/toggleable_objects.asm"))
        sprite_assets = parse_sprite_assets(
            self._read_text("data/sprites/sprites.asm"),
            self._read_text("gfx/sprites.asm"),
        )

        player_sprite_name = sprite_assets.get("SPRITE_RED")
        if player_sprite_name is None:
            raise ParseError("SPRITE_RED has no source graphic")
        player_asset = self._asset("sprites", player_sprite_name)

        maps: dict[str, MapDefinition] = {}
        for source_name in SUPPORTED_MAPS:
            map_definition = self._build_map(
                source_name,
                dimensions,
                map_metadata,
                collisions,
                tileset_images,
                blocksets,
                visibility,
                sprite_assets,
                player_asset,
            )
            maps[map_definition.id] = map_definition

        start_map, player_spawn = parse_new_game_warp(
            self._read_text("data/maps/special_warps.asm")
        )
        maps[start_map] = maps[start_map].model_copy(update={"player_spawn": player_spawn})
        return WorldDefinition(
            start_map=start_map,
            player_spawn=player_spawn,
            player_sprite="SPRITE_RED",
            text_variables=self._text_variables,
            source_repository=REPOSITORY_URL,
            source_revision=self.revision,
            maps=maps,
        )

    def _build_map(
        self,
        source_name: str,
        dimensions_content: str,
        map_metadata: dict[str, ParsedMapMetadata],
        collision_sets: dict[str, set[int]],
        tileset_images: dict[str, str],
        blocksets: dict[str, str],
        visibility: dict[str, bool],
        sprite_assets: dict[str, str],
        player_asset: SourceAsset,
    ) -> MapDefinition:
        header_file = f"data/maps/headers/{source_name}.asm"
        object_file = f"data/maps/objects/{source_name}.asm"
        script_file = f"scripts/{source_name}.asm"
        text_file = f"text/{source_name}.asm"
        header = parse_header(self._read_text(header_file))
        metadata = self._required(map_metadata, header.map_constant, "map metadata")
        block_width, block_height = parse_dimensions(dimensions_content, header.map_constant)
        parsed_objects = parse_map_objects(self._read_text(object_file))
        image_name = self._required(tileset_images, header.tileset, "tileset graphic")
        blockset_name = self._required(blocksets, header.tileset, "blockset")
        passable_tiles = self._required(collision_sets, header.tileset, "collision set")
        block_path = self._path(f"maps/{source_name}.blk")
        blocks = parse_blocks(block_path.read_bytes(), block_width, block_height, block_path)
        blockset_bytes = self._path(f"gfx/blocksets/{blockset_name}.bst").read_bytes()
        scripts = self._read_text(script_file)
        references = [item.text_reference for item in parsed_objects.objects]
        references.extend(event.text_reference for event in parsed_objects.background_events)
        texts = self._read_text(text_file) if references else ""

        map_sprite_assets: dict[str, SourceAsset] = {}
        npcs: list[NPCDefinition] = []
        for parsed in parsed_objects.objects:
            sprite_name = self._required(sprite_assets, parsed.sprite, "sprite graphic")
            map_sprite_assets[parsed.sprite] = self._asset("sprites", sprite_name)
            npcs.append(
                NPCDefinition(
                    id=parsed.source_id,
                    object_index=parsed.object_index,
                    position=parsed.position,
                    facing=source_facing(parsed.facing),
                    movement=parsed.movement,
                    visible=visibility.get(parsed.source_id, True),
                    sprite=parsed.sprite,
                    interaction=self._interaction(
                        parsed.text_reference, scripts, texts, script_file, text_file
                    ),
                    provenance=self._provenance(object_file, parsed.source_id),
                )
            )

        background_events = [
            BackgroundEvent(
                position=parsed.position,
                interaction=self._interaction(
                    parsed.text_reference, scripts, texts, script_file, text_file
                ),
                provenance=self._provenance(object_file, parsed.text_reference),
            )
            for parsed in parsed_objects.background_events
        ]
        warps: list[WarpDefinition] = []
        for parsed_warp in parsed_objects.warps:
            trigger, outward = self._warp_trigger(
                parsed_warp.position,
                parsed_warp.target_map,
                block_width * 2,
                block_height * 2,
            )
            warps.append(
                WarpDefinition(
                    index=parsed_warp.index,
                    position=parsed_warp.position,
                    target_map=parsed_warp.target_map,
                    target_warp=parsed_warp.target_warp,
                    uses_last_map=parsed_warp.target_map == "LAST_MAP",
                    trigger=trigger,
                    outward=outward,
                    provenance=self._provenance(object_file, f"warp_event_{parsed_warp.index}"),
                )
            )
        connections = [
            MapConnection(
                direction=parsed.direction,
                target_map=parsed.target_map,
                offset=parsed.offset,
                available=parsed.target_map in SUPPORTED_MAP_CONSTANTS,
                provenance=self._provenance(header_file, f"connection_{parsed.direction.value}"),
            )
            for parsed in header.connections
        ]
        collision_tile_ids = expand_collision_tiles(blocks, blockset_bytes)
        map_definition = MapDefinition(
            id=header.map_constant,
            source_name=header.source_name,
            kind=metadata.kind,
            last_map_target=metadata.last_map_target,
            width=block_width * 2,
            height=block_height * 2,
            walkable=[[tile_id in passable_tiles for tile_id in row] for row in collision_tile_ids],
            npcs=npcs,
            background_events=background_events,
            warps=warps,
            connections=connections,
            provenance=self._provenance(header_file, f"{source_name}_h"),
        )
        self._retro_resources[header.map_constant] = RetroMapResources(
            map_id=header.map_constant,
            tileset=header.tileset,
            tileset_asset=self._asset("tilesets", image_name),
            tile_ids=expand_blocks(blocks, blockset_bytes),
            block_ids=blocks,
            player_asset=player_asset,
            sprite_assets=map_sprite_assets,
        )
        self._three_d_resources[header.map_constant] = ThreeDMapResources(
            map_id=header.map_constant,
            tile_appearances=[
                [
                    self._three_d_tile_appearance(
                        header.tileset,
                        tile_id,
                        tile_id in passable_tiles,
                    )
                    for tile_id in row
                ]
                for row in collision_tile_ids
            ],
            player_appearance="character.player",
            npc_appearances={npc.id: "character.npc" for npc in npcs},
        )
        return map_definition

    @staticmethod
    def _warp_trigger(
        position: Position,
        target_map: str,
        width: int,
        height: int,
    ) -> tuple[Literal["on_step", "edge_exit"], Direction | None]:
        if target_map != "LAST_MAP":
            return "on_step", None
        outward = [
            direction
            for direction, at_boundary in (
                (Direction.NORTH, position.y == 0),
                (Direction.SOUTH, position.y == height - 1),
                (Direction.WEST, position.x == 0),
                (Direction.EAST, position.x == width - 1),
            )
            if at_boundary
        ]
        if not outward:
            return "on_step", None
        if len(outward) != 1:
            raise ParseError(
                f"LAST_MAP warp at {position} has ambiguous outward boundary directions"
            )
        return "edge_exit", outward[0]

    @staticmethod
    def _three_d_tile_appearance(tileset: str, tile_id: int, walkable: bool) -> str:
        """Project source tile semantics into the preserved 3D presentation vocabulary."""

        if tileset == "OVERWORLD":
            if tile_id == 0x14:
                return "tile.water"
            if tile_id == 0x52:
                return "tile.grass"
            return "tile.path" if walkable else "tile.tree"
        return "tile.floor" if walkable else "tile.wall"

    def _interaction(
        self,
        reference: str,
        scripts: str,
        texts: str,
        script_file: str,
        text_file: str,
    ) -> TextInteraction:
        parsed = parse_direct_text(reference, scripts, texts)
        provenance_file = text_file if parsed.status == "direct" else script_file
        return TextInteraction(
            reference=reference,
            status=parsed.status,
            template_pages=list(parsed.pages),
            reason=parsed.reason,
            provenance=self._provenance(provenance_file, parsed.source_symbol),
        )

    def _parse_start_position(self, map_constant: str) -> Position:
        content = self._read_text("data/maps/special_warps.asm")
        match = re.search(
            rf"^\s*(?:\.[A-Za-z0-9_]+:\s*)?fly_warp\s+{re.escape(map_constant)},"
            r"\s*(\d+),\s*(\d+)\s*$",
            content,
            re.MULTILINE,
        )
        if match is None:
            raise ParseError(f"missing fly_warp start for {map_constant}")
        return Position(x=int(match.group(1)), y=int(match.group(2)))

    def _asset(self, category: str, name: str) -> SourceAsset:
        directory = "tilesets" if category == "tilesets" else "sprites"
        path = self._path(f"gfx/{directory}/{name}.png")
        if not path.is_file():
            raise ParseError(f"missing source asset {path.relative_to(self._root)}")
        self._asset_allowlist[(category, name)] = path
        return SourceAsset(
            kind="tileset" if category == "tilesets" else "sprite",
            name=name,
            url=f"/source-assets/{category}/{name}.png",
        )

    def _provenance(self, file: str, symbol: str | None = None) -> SourceProvenance:
        return SourceProvenance(
            repository=REPOSITORY_URL,
            revision=self.revision,
            file=file,
            symbol=symbol,
        )

    def _read_text(self, relative: str) -> str:
        path = self._path(relative)
        try:
            return path.read_text(encoding="utf-8")
        except OSError as error:
            raise PokeredSourceError(f"unable to read required source file: {path}") from error

    def _path(self, relative: str) -> Path:
        path = (self._root / relative).resolve()
        if not path.is_relative_to(self._root):
            raise PokeredSourceError("source path escapes the configured pret/pokered root")
        return path

    def _validate_root(self) -> None:
        if not self._root.is_dir() or not (self._root / ".git").exists():
            raise PokeredSourceError(
                f"pret/pokered source root is not a Git checkout: {self._root}"
            )

    def _validate_integrity(self) -> None:
        self._resolve_revision()
        try:
            validate_clean_checkout(self._root, self._expected_tree)
        except (OSError, ParseError) as error:
            raise PokeredSourceError(
                f"pret/pokered checkout integrity validation failed at {self._root}: {error}"
            ) from error
        self._integrity_validated = True

    def _resolve_revision(self) -> None:
        if self._revision is not None:
            return
        self._validate_root()
        try:
            revision = read_git_revision(self._root)
        except (OSError, ParseError) as error:
            raise PokeredSourceError(
                f"unable to identify the pret/pokered revision: {error}"
            ) from error
        if revision != self._expected_revision:
            raise PokeredSourceError(
                f"unsupported pret/pokered revision {revision}; expected {self._expected_revision}"
            )
        self._revision = revision

    @staticmethod
    def _required[T](values: dict[str, T], key: str, label: str) -> T:
        try:
            return values[key]
        except KeyError as error:
            raise ParseError(f"missing {label} for {key}") from error
