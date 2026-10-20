import shutil
import subprocess
from collections import deque
from pathlib import Path

import pytest

from backend.app.engine.game import ActionResult, GameSession
from backend.app.models.common import Direction, Position
from backend.app.models.map import MapDefinition, WorldDefinition
from backend.app.source.pokered import PokeredSource, PokeredSourceError
from backend.app.source.pokered.parsers import (
    ParseError,
    expand_blocks,
    expand_collision_tiles,
    parse_direct_text,
    parse_map_metadata,
    parse_map_objects,
)
from backend.app.source.pokered.revision import read_git_revision
from backend.app.source.pokered.source import PINNED_REVISION

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _pallet_exploration_world(world: WorldDefinition) -> WorldDefinition:
    """Keep Phase 2 exploration assertions independent from canonical NewGameWarp."""

    return world.model_copy(update={"start_map": "PALLET_TOWN", "player_spawn": Position(x=5, y=6)})


def _complete_direction(session: GameSession, direction: Direction) -> ActionResult:
    result = session.move(direction, continued=False)
    if result.action == "turned":
        result = session.move(direction, continued=True)
    return result


def test_block_expansion_separates_rendering_from_collision_sampling() -> None:
    blockset = bytes(range(16))

    assert expand_blocks([[0]], blockset) == [
        [0, 1, 2, 3],
        [4, 5, 6, 7],
        [8, 9, 10, 11],
        [12, 13, 14, 15],
    ]
    assert expand_collision_tiles([[0]], blockset) == [[4, 6], [12, 14]]


def test_object_parser_accepts_source_metadata_after_text_reference() -> None:
    parsed = parse_map_objects(
        """
        object_const_def
        const_export FIXTURE_PERSON
        def_warp_events
        warp_event 1, 2, LAST_MAP, 1
        def_bg_events
        bg_event 3, 4, TEXT_SIGN
        def_object_events
        object_event 5, 6, SPRITE_GIRL, WALK, ANY_DIR, TEXT_PERSON, 0
        """
    )

    assert parsed.objects[0].source_id == "FIXTURE_PERSON"
    assert parsed.warps[0].target_map == "LAST_MAP"
    assert parsed.background_events[0].text_reference == "TEXT_SIGN"


def test_map_metadata_assigns_canonical_indoor_last_map_groups() -> None:
    metadata = parse_map_metadata(
        """
        map_const PALLET_TOWN, 10, 9
        DEF FIRST_INDOOR_MAP EQU const_value
        map_const REDS_HOUSE_1F, 4, 4
        map_const REDS_HOUSE_2F, 4, 4
        end_indoor_group PALLET_TOWN
        map_const VIRIDIAN_HOUSE, 4, 4
        end_indoor_group VIRIDIAN_CITY
        """
    )

    assert metadata["PALLET_TOWN"].kind == "outdoor"
    assert metadata["PALLET_TOWN"].last_map_target is None
    assert metadata["REDS_HOUSE_1F"].last_map_target == "PALLET_TOWN"
    assert metadata["REDS_HOUSE_2F"].last_map_target == "PALLET_TOWN"
    assert metadata["VIRIDIAN_HOUSE"].last_map_target == "VIRIDIAN_CITY"


def test_direct_text_parser_preserves_source_pages() -> None:
    parsed = parse_direct_text(
        "TEXT_PERSON",
        "dw_const PersonText, TEXT_PERSON\nPersonText:\n\ttext_far _PersonText\n\ttext_end\n",
        '_PersonText::\n\ttext "First"\n\tline "line"\n\n\tpara "Second"\n\tdone\n',
    )

    assert parsed.status == "direct"
    assert parsed.pages == ("First\nline", "Second")


def test_direct_text_parser_preserves_controls_for_runtime_resolution() -> None:
    parsed = parse_direct_text(
        "TEXT_PERSON",
        "dw_const PersonText, TEXT_PERSON\nPersonText:\n\ttext_far _PersonText\n\ttext_end\n",
        '_PersonText::\n\ttext "<RIVAL> asks <PLAYER> about #MON."\n\tdone\n',
    )

    assert parsed.pages == ("<RIVAL> asks <PLAYER> about #MON.",)


def test_conditional_text_is_explicitly_unsupported() -> None:
    parsed = parse_direct_text(
        "TEXT_PERSON",
        "dw_const PersonText, TEXT_PERSON\nPersonText:\n\ttext_asm\n\tcall Something\n",
        "",
    )

    assert parsed.status == "unsupported"
    assert parsed.reason == "conditional text_asm scripts are not implemented"


def test_parser_rejects_mismatched_object_constants() -> None:
    with pytest.raises(ParseError, match="one-to-one"):
        parse_map_objects("const_export PERSON\n")


def test_provider_rejects_missing_checkout(tmp_path: Path) -> None:
    with pytest.raises(PokeredSourceError, match="not a Git checkout"):
        PokeredSource(tmp_path).build_world()


def test_revision_reader_resolves_loose_ref_without_git_executable(tmp_path: Path) -> None:
    git_dir = tmp_path / ".git"
    ref = git_dir / "refs/heads/main"
    ref.parent.mkdir(parents=True)
    (git_dir / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")
    ref.write_text(f"{'b' * 40}\n", encoding="utf-8")

    assert read_git_revision(tmp_path) == "b" * 40


def test_revision_reader_resolves_packed_ref(tmp_path: Path) -> None:
    git_dir = tmp_path / ".git"
    git_dir.mkdir()
    (git_dir / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")
    (git_dir / "packed-refs").write_text(
        f"# pack-refs\n{'c' * 40} refs/heads/main\n",
        encoding="utf-8",
    )

    assert read_git_revision(tmp_path) == "c" * 40


def test_provider_rejects_an_unpinned_checkout(tmp_path: Path) -> None:
    git_dir = tmp_path / ".git"
    git_dir.mkdir()
    (git_dir / "HEAD").write_text(f"{'d' * 40}\n", encoding="utf-8")

    with pytest.raises(PokeredSourceError, match=f"expected {PINNED_REVISION}"):
        _ = PokeredSource(tmp_path).revision


def test_provider_validates_tracked_checkout_integrity_and_ignores_untracked_files(
    tmp_path: Path,
    pokered_world: WorldDefinition,
) -> None:
    del pokered_world  # Ensures the canonical checkout is present before copying it.
    checkout = tmp_path / "pokered"
    shutil.copytree(PROJECT_ROOT / "external/pokered", checkout)

    clean_world = PokeredSource(checkout).build_world()
    assert clean_world.source_revision == PINNED_REVISION

    untracked = checkout / "local-notes.txt"
    untracked.write_text("ignored local note\n", encoding="utf-8")
    assert PokeredSource(checkout).build_world().source_revision == PINNED_REVISION
    untracked.unlink()

    pallet_text = checkout / "text/PalletTown.asm"
    original = pallet_text.read_bytes()
    pallet_text.write_bytes(original + b"\n; local tracked edit\n")
    with pytest.raises(PokeredSourceError, match="tracked pret/pokered file differs") as modified:
        PokeredSource(checkout).build_world()
    assert str(checkout) in str(modified.value)

    pallet_text.write_bytes(original)
    pallet_text.unlink()
    with pytest.raises(PokeredSourceError, match="tracked pret/pokered file is missing") as deleted:
        PokeredSource(checkout).build_world()
    assert str(checkout) in str(deleted.value)

    pallet_text.write_bytes(original + b"\n; staged tracked edit\n")
    subprocess.run(
        ["git", "add", "text/PalletTown.asm"],
        cwd=checkout,
        check=True,
        capture_output=True,
        text=True,
    )
    with pytest.raises(PokeredSourceError, match="index differs from pinned tree") as staged:
        PokeredSource(checkout).build_world()
    assert str(checkout) in str(staged.value)


def test_pinned_pallet_source_builds_all_five_maps(pokered_world: WorldDefinition) -> None:
    assert set(pokered_world.maps) == {
        "PALLET_TOWN",
        "REDS_HOUSE_1F",
        "REDS_HOUSE_2F",
        "BLUES_HOUSE",
        "OAKS_LAB",
    }
    pallet = pokered_world.maps["PALLET_TOWN"]
    assert (pallet.width, pallet.height) == (20, 18)
    assert pokered_world.start_map == "REDS_HOUSE_2F"
    assert pokered_world.player_spawn == Position(x=3, y=6)
    assert pokered_world.maps["REDS_HOUSE_2F"].player_spawn == Position(x=3, y=6)
    assert pallet.npc_at(pallet.npcs[1].position) is not None
    assert pallet.npcs[1].interaction.template_pages[0] == "I'm raising\n#MON too!"
    assert pallet.background_events[0].interaction.template_pages[0] == "OAK #MON\nRESEARCH LAB"
    assert pallet.kind == "outdoor"
    assert pallet.last_map_target is None
    assert pokered_world.maps["REDS_HOUSE_1F"].kind == "indoor"
    assert pokered_world.maps["REDS_HOUSE_1F"].last_map_target == "PALLET_TOWN"


def test_source_collision_and_warps_match_pinned_values(
    pokered_world: WorldDefinition,
) -> None:
    pallet = pokered_world.maps["PALLET_TOWN"]
    assert pallet.warps[0].target_map == "REDS_HOUSE_1F"
    assert pallet.warps[1].target_map == "BLUES_HOUSE"
    assert pallet.warps[2].target_map == "OAKS_LAB"
    assert pokered_world.maps["REDS_HOUSE_1F"].warps[0].uses_last_map is True


def test_three_d_projection_is_source_derived_and_renderer_separate(
    pokered_world: WorldDefinition,
) -> None:
    source = PokeredSource(Path(__file__).resolve().parents[1] / "external/pokered")
    world = source.build_world()

    resources = source.three_d_resources("PALLET_TOWN")

    assert resources.map_id == "PALLET_TOWN"
    assert len(resources.tile_appearances) == world.maps["PALLET_TOWN"].height
    assert all(len(row) == world.maps["PALLET_TOWN"].width for row in resources.tile_appearances)
    assert set(resources.npc_appearances) == {npc.id for npc in world.maps["PALLET_TOWN"].npcs}


def test_source_npc_can_be_reached_and_displays_original_text(
    pokered_world: WorldDefinition,
) -> None:
    session = GameSession(_pallet_exploration_world(pokered_world))
    _complete_direction(session, Direction.SOUTH)
    _complete_direction(session, Direction.SOUTH)
    _complete_direction(session, Direction.WEST)

    collision = _complete_direction(session, Direction.WEST)
    interaction = session.interact()

    assert collision.reason == "npc"
    assert interaction.action == "dialog_opened"
    assert session.dialog is not None
    assert session.dialog.pages[0] == "I'm raising\nPOKéMON too!"


def _walk_to_warp(session: GameSession, map_definition: MapDefinition, warp_index: int) -> None:
    warp = map_definition.warps[warp_index - 1]
    start = (session.player.position.x, session.player.position.y)
    goal = (warp.position.x, warp.position.y)
    occupied = {(npc.position.x, npc.position.y) for npc in map_definition.npcs if npc.visible}
    occupied.update(
        (candidate.position.x, candidate.position.y)
        for candidate in map_definition.warps
        if candidate.index != warp_index
    )
    queue: deque[tuple[tuple[int, int], list[Direction]]] = deque([(start, [])])
    seen = {start}
    steps = {
        Direction.NORTH: (0, -1),
        Direction.SOUTH: (0, 1),
        Direction.WEST: (-1, 0),
        Direction.EAST: (1, 0),
    }
    path: list[Direction] | None = None
    while queue:
        current, directions = queue.popleft()
        if current == goal:
            path = directions
            break
        for direction, (dx, dy) in steps.items():
            candidate = (current[0] + dx, current[1] + dy)
            position = Position(x=candidate[0], y=candidate[1])
            if (
                candidate not in seen
                and candidate not in occupied
                and map_definition.contains(position)
                and map_definition.is_walkable(position)
            ):
                seen.add(candidate)
                queue.append((candidate, [*directions, direction]))
    assert path is not None, f"warp {warp_index} is unreachable in {map_definition.id}"
    for direction in path:
        _complete_direction(session, direction)


def _step_off_and_return(session: GameSession, map_definition: MapDefinition) -> None:
    reverse = {
        Direction.NORTH: Direction.SOUTH,
        Direction.SOUTH: Direction.NORTH,
        Direction.WEST: Direction.EAST,
        Direction.EAST: Direction.WEST,
    }
    for direction in Direction:
        neighbor = session.player.position.moved(direction)
        if (
            map_definition.contains(neighbor)
            and map_definition.is_walkable(neighbor)
            and map_definition.npc_at(neighbor) is None
            and map_definition.warp_at(neighbor) is None
        ):
            assert _complete_direction(session, direction).action == "moved"
            assert _complete_direction(session, reverse[direction]).action == "transitioned"
            return
    pytest.fail(f"no safe step away from warp in {map_definition.id}")


@pytest.mark.parametrize(
    ("source_map_id", "source_warp", "target_map_id", "target_warp"),
    [
        ("PALLET_TOWN", 1, "REDS_HOUSE_1F", 1),
        ("PALLET_TOWN", 2, "BLUES_HOUSE", 1),
        ("PALLET_TOWN", 3, "OAKS_LAB", 2),
    ],
)
def test_pallet_building_warps_round_trip_via_canonical_last_map(
    pokered_world: WorldDefinition,
    source_map_id: str,
    source_warp: int,
    target_map_id: str,
    target_warp: int,
) -> None:
    session = GameSession(_pallet_exploration_world(pokered_world))
    _walk_to_warp(session, pokered_world.maps[source_map_id], source_warp)

    assert session.map_id == target_map_id
    assert (
        session.player.position == pokered_world.maps[target_map_id].warps[target_warp - 1].position
    )

    result = _complete_direction(session, Direction.SOUTH)

    assert result.action == "transitioned"
    assert session.map_id == source_map_id
    assert session.player.position == pokered_world.maps[source_map_id].warps[
        source_warp - 1
    ].position.moved(Direction.SOUTH)
    assert session.player.facing == Direction.SOUTH

    assert _complete_direction(session, Direction.NORTH).action == "transitioned"
    assert session.map_id == target_map_id
    assert (
        session.player.position == pokered_world.maps[target_map_id].warps[target_warp - 1].position
    )


def test_reds_house_stairs_round_trip(pokered_world: WorldDefinition) -> None:
    session = GameSession(_pallet_exploration_world(pokered_world))
    _walk_to_warp(session, pokered_world.maps["PALLET_TOWN"], 1)
    _walk_to_warp(session, pokered_world.maps["REDS_HOUSE_1F"], 3)

    assert session.map_id == "REDS_HOUSE_2F"
    assert session.player.position == pokered_world.maps["REDS_HOUSE_2F"].warps[0].position
    _step_off_and_return(session, pokered_world.maps["REDS_HOUSE_2F"])

    assert session.map_id == "REDS_HOUSE_1F"
    assert session.player.position == pokered_world.maps["REDS_HOUSE_1F"].warps[2].position


@pytest.mark.parametrize(
    ("source_map_id", "source_warp", "target_map_id", "target_warp", "uses_last_map"),
    [
        ("PALLET_TOWN", 1, "REDS_HOUSE_1F", 1, False),
        ("PALLET_TOWN", 2, "BLUES_HOUSE", 1, False),
        ("PALLET_TOWN", 3, "OAKS_LAB", 2, False),
        ("REDS_HOUSE_1F", 1, "PALLET_TOWN", 1, True),
        ("REDS_HOUSE_1F", 2, "PALLET_TOWN", 1, True),
        ("REDS_HOUSE_1F", 3, "REDS_HOUSE_2F", 1, False),
        ("REDS_HOUSE_2F", 1, "REDS_HOUSE_1F", 3, False),
        ("BLUES_HOUSE", 1, "PALLET_TOWN", 2, True),
        ("BLUES_HOUSE", 2, "PALLET_TOWN", 2, True),
        ("OAKS_LAB", 1, "PALLET_TOWN", 3, True),
        ("OAKS_LAB", 2, "PALLET_TOWN", 3, True),
    ],
)
def test_every_pallet_warp_uses_its_canonical_return_position(
    pokered_world: WorldDefinition,
    source_map_id: str,
    source_warp: int,
    target_map_id: str,
    target_warp: int,
    uses_last_map: bool,
) -> None:
    source_map = pokered_world.maps[source_map_id]
    warp = source_map.warps[source_warp - 1]
    if warp.trigger == "edge_exit":
        assert warp.outward is not None
        test_world = pokered_world.model_copy(
            update={"start_map": source_map_id, "player_spawn": warp.position}
        )
        session = GameSession(test_world)
        direction = warp.outward
    else:
        session, direction = _session_next_to_warp(pokered_world, source_map_id, source_warp)

    result = _complete_direction(session, direction)

    assert result.action == "transitioned"
    assert warp.uses_last_map is uses_last_map
    assert session.map_id == target_map_id
    expected = pokered_world.maps[target_map_id].warps[target_warp - 1].position
    if warp.trigger == "edge_exit":
        expected = expected.moved(direction)
    assert session.player.position == expected


@pytest.mark.parametrize("map_id", ["REDS_HOUSE_1F", "BLUES_HOUSE", "OAKS_LAB"])
def test_paired_building_exits_move_sideways_without_transition(
    pokered_world: WorldDefinition,
    map_id: str,
) -> None:
    map_definition = pokered_world.maps[map_id]
    left, right = map_definition.warps[:2]
    assert left.trigger == right.trigger == "edge_exit"
    assert left.outward == right.outward == Direction.SOUTH
    assert right.position == left.position.moved(Direction.EAST)
    test_world = pokered_world.model_copy(
        update={"start_map": map_id, "player_spawn": left.position}
    )
    session = GameSession(test_world)

    sideways = _complete_direction(session, Direction.EAST)

    assert sideways.action == "moved"
    assert session.map_id == map_id
    assert session.player.position == right.position
    assert _complete_direction(session, Direction.SOUTH).action == "transitioned"


def test_house_stairs_remain_on_step_warps(pokered_world: WorldDefinition) -> None:
    assert pokered_world.maps["REDS_HOUSE_1F"].warps[2].trigger == "on_step"
    assert pokered_world.maps["REDS_HOUSE_2F"].warps[0].trigger == "on_step"


def _session_next_to_warp(
    world: WorldDefinition,
    map_id: str,
    warp_index: int,
) -> tuple[GameSession, Direction]:
    map_definition = world.maps[map_id]
    warp = map_definition.warps[warp_index - 1]
    reverse = {
        Direction.NORTH: Direction.SOUTH,
        Direction.SOUTH: Direction.NORTH,
        Direction.WEST: Direction.EAST,
        Direction.EAST: Direction.WEST,
    }
    for direction in Direction:
        start = warp.position.moved(reverse[direction])
        if (
            map_definition.contains(start)
            and map_definition.is_walkable(start)
            and map_definition.npc_at(start) is None
            and map_definition.warp_at(start) is None
        ):
            test_world = world.model_copy(update={"start_map": map_id, "player_spawn": start})
            return GameSession(test_world), direction
    pytest.fail(f"no passable position beside warp {warp_index} in {map_id}")
