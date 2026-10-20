from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from backend.app.models.common import Direction, Position
from backend.app.models.map import (
    MapDefinition,
    SourceProvenance,
    WarpDefinition,
    WorldDefinition,
)
from backend.app.models.pokemon import SpeciesDefinition
from backend.app.models.story import (
    ActorState,
    ChoiceCommand,
    ChoiceOption,
    DialogCommand,
    GrantRivalStarterCommand,
    GrantStarterCommand,
    InteractionTrigger,
    MapEnterTrigger,
    MoveActorToPlayerCommand,
    MovementCommand,
    MovementTrackDefinition,
    PhaseBoundaryCommand,
    PositionTrigger,
    SelectRivalStarterCommand,
    SelectStarterCommand,
    SetActorCommand,
    SetFlagCommand,
    SetPlayerFacingCommand,
    StarterDefinition,
    StartTrigger,
    StoryCondition,
    StoryDefinition,
    StoryNode,
    StoryText,
    TransitionCommand,
)

from .parsers import (
    ParseError,
    assert_source_patterns,
    parse_movement,
    parse_movement_sequence,
    parse_new_game_warp,
    parse_rgbds_constants,
    parse_simulated_joypad_rle,
    parse_source_text,
    require_constants,
)

REPOSITORY_URL = "https://github.com/pret/pokered"

EVENT_FLAGS = {
    "EVENT_FOLLOWED_OAK_INTO_LAB",
    "EVENT_FOLLOWED_OAK_INTO_LAB_2",
    "EVENT_OAK_ASKED_TO_CHOOSE_MON",
    "EVENT_GOT_STARTER",
    "EVENT_BATTLED_RIVAL_IN_OAKS_LAB",
    "EVENT_OAK_APPEARED_IN_PALLET",
}

TEXT_SOURCES = {
    "mom_wake": ("text/RedsHouse1F.asm", "_RedsHouse1FMomWakeUpText"),
    "tv_normal": ("text/RedsHouse1F.asm", "_RedsHouse1FTVStandByMeMovieText"),
    "tv_wrong_side": ("text/RedsHouse1F.asm", "_RedsHouse1FTVWrongSideText"),
    "oak_hey_wait": ("text/PalletTown.asm", "_PalletTownOakHeyWaitDontGoOutText"),
    "oak_unsafe": ("text/PalletTown.asm", "_PalletTownOakItsUnsafeText"),
    "rival_waiting": ("text/OaksLab.asm", "_OaksLabRivalFedUpWithWaitingText"),
    "rival_early": ("text/OaksLab.asm", "_OaksLabRivalGrampsIsntAroundText"),
    "rival_choose": ("text/OaksLab.asm", "_OaksLabRivalGoAheadAndChooseText"),
    "rival_stronger": ("text/OaksLab.asm", "_OaksLabRivalMyPokemonLooksStrongerText"),
    "oak_choose": ("text/OaksLab.asm", "_OaksLabOakChooseMonText"),
    "rival_what_about_me": ("text/OaksLab.asm", "_OaksLabRivalWhatAboutMeText"),
    "oak_be_patient": ("text/OaksLab.asm", "_OaksLabOakBePatientText"),
    "oak_dont_go": ("text/OaksLab.asm", "_OaksLabOakDontGoAwayYetText"),
    "poke_balls": ("text/OaksLab.asm", "_OaksLabThoseArePokeBallsText"),
    "last_mon": ("text/OaksLab.asm", "_OaksLabLastMonText"),
    "want_charmander": ("text/OaksLab.asm", "_OaksLabYouWantCharmanderText"),
    "want_squirtle": ("text/OaksLab.asm", "_OaksLabYouWantSquirtleText"),
    "want_bulbasaur": ("text/OaksLab.asm", "_OaksLabYouWantBulbasaurText"),
    "mon_energetic": ("text/OaksLab.asm", "_OaksLabMonEnergeticText"),
    "received_mon": ("text/OaksLab.asm", "_OaksLabReceivedMonText"),
    "rival_take": ("text/OaksLab.asm", "_OaksLabRivalIllTakeThisOneText"),
    "rival_received": ("text/OaksLab.asm", "_OaksLabRivalReceivedMonText"),
    "rival_challenge": ("text/OaksLab.asm", "_OaksLabRivalIllTakeYouOnText"),
}


@dataclass(frozen=True)
class WarpInterruptedMovement:
    """The visible prefix of source input ending on its first on-step warp."""

    steps: tuple[Direction, ...]
    warp: WarpDefinition


def compile_warp_interrupted_movement(
    map_definition: MapDefinition,
    start: Position,
    steps: tuple[Direction, ...],
) -> WarpInterruptedMovement:
    """Stop a decoded source path on, and including, its first on-step warp."""

    position = start
    visible_steps: list[Direction] = []
    for direction in steps:
        position = position.moved(direction)
        visible_steps.append(direction)
        warp = map_definition.warp_at(position, "on_step")
        if warp is not None:
            return WarpInterruptedMovement(steps=tuple(visible_steps), warp=warp)
    raise ParseError(
        f"source movement from {start} does not encounter an on-step warp in {map_definition.id}"
    )


def build_pallet_story(root: Path, revision: str, world: WorldDefinition) -> StoryDefinition:
    """Compile the deliberately narrow Pallet opening from the pinned source."""

    def read(relative: str) -> str:
        return (root / relative).read_text(encoding="utf-8")

    start_map, start_position = parse_new_game_warp(read("data/maps/special_warps.asm"))
    if (start_map, start_position.x, start_position.y) != ("REDS_HOUSE_2F", 3, 6):
        raise ParseError("NewGameWarp source drift: expected REDS_HOUSE_2F, 3, 6")

    event_values = parse_rgbds_constants(read("constants/event_constants.asm"))
    require_constants(event_values, EVENT_FLAGS)
    pokemon_constants = parse_rgbds_constants(read("constants/pokemon_constants.asm"))
    required_species = require_constants(
        pokemon_constants,
        {"STARTER1", "STARTER2", "STARTER3", "CHARMANDER", "SQUIRTLE", "BULBASAUR"},
    )
    if (
        required_species["STARTER1"] != required_species["CHARMANDER"]
        or required_species["STARTER2"] != required_species["SQUIRTLE"]
        or required_species["STARTER3"] != required_species["BULBASAUR"]
    ):
        raise ParseError("starter aliases no longer map to Charmander, Squirtle, Bulbasaur")

    species = {
        constant: SpeciesDefinition(id=required_species[constant], constant=constant, name=constant)
        for constant in ("CHARMANDER", "SQUIRTLE", "BULBASAUR")
    }
    names = read("data/pokemon/names.asm")
    for definition in species.values():
        if re.search(rf'^\s*dname\s+"{definition.constant}"\s*$', names, re.MULTILINE) is None:
            raise ParseError(f"missing source monster name for {definition.constant}")

    oaks_lab = read("scripts/OaksLab.asm")
    pallet = read("scripts/PalletTown.asm")
    assert_source_patterns(
        pallet,
        {
            "north-exit intercept": r"cp 1\s*; is player near north exit",
            "Oak appeared event": r"SetEvent EVENT_OAK_APPEARED_IN_PALLET",
            "followed guard": r"CheckEvent EVENT_FOLLOWED_OAK_INTO_LAB",
        },
        "scripts/PalletTown.asm",
    )
    assert_source_patterns(
        oaks_lab,
        {
            "asked-to-choose event": r"SetEvent EVENT_OAK_ASKED_TO_CHOOSE_MON",
            "player starter bit": r"set BIT_GOT_STARTER",
            "rival starter event": r"SetEvent EVENT_GOT_STARTER",
            "battle boundary": r"SetEvent EVENT_BATTLED_RIVAL_IN_OAKS_LAB",
            "exit warning faces Oak and rival down": (
                r"OaksLabPlayerDontGoAwayScript:[\s\S]*?OAKSLAB_OAK1"
                r"[\s\S]*?SPRITE_FACING_DOWN[\s\S]*?OAKSLAB_RIVAL"
                r"[\s\S]*?SPRITE_FACING_DOWN[\s\S]*?OAKSLAB_OAK_DONT_GO_AWAY_YET"
            ),
            "rival faces up before taking starter": (
                r"OaksLabRivalChoosesStarterScript:[\s\S]*?OAKSLAB_RIVAL"
                r"[\s\S]*?SPRITE_FACING_UP[\s\S]*?OAKSLAB_RIVAL_ILL_TAKE_THIS_ONE"
            ),
            "rival approaches before battle": (
                r"OaksLabRivalChallengesPlayerScript:[\s\S]*?SPRITE_FACING_DOWN"
                r"[\s\S]*?OAKSLAB_RIVAL_ILL_TAKE_YOU_ON[\s\S]*?FindPathToPlayer"
                r"[\s\S]*?call MoveSprite[\s\S]*?OaksLabRivalStartBattleScript"
            ),
            "Charmander rival path branch": (
                r"\.Charmander[\s\S]*?cp 4[\s\S]*?\.MiddleBallMovement1"
            ),
            "Squirtle rival path branch": r"\.Squirtle[\s\S]*?cp 4[\s\S]*?\.RightBallMovement1",
            "Bulbasaur rival path branch": r"\.Bulbasaur[\s\S]*?cp 9[\s\S]*?\.LeftBallMovement1",
            "Charmander counter starter": (
                r"OaksLabCharmanderPokeBallText:[\s\S]*?ld a, STARTER2"
                r"[\s\S]*?ld a, OAKSLAB_SQUIRTLE_POKE_BALL"
            ),
            "Squirtle counter starter": (
                r"OaksLabSquirtlePokeBallText:[\s\S]*?ld a, STARTER3"
                r"[\s\S]*?ld a, OAKSLAB_BULBASAUR_POKE_BALL"
            ),
            "Bulbasaur counter starter": (
                r"OaksLabBulbasaurPokeBallText:[\s\S]*?ld a, STARTER1"
                r"[\s\S]*?ld a, OAKSLAB_CHARMANDER_POKE_BALL"
            ),
        },
        "scripts/OaksLab.asm",
    )
    assert_source_patterns(
        read("text/OaksLab.asm"),
        {"runtime species name": r"text_ram wNameBuffer"},
        "text/OaksLab.asm",
    )

    auto_movement = read("engine/overworld/auto_movement.asm")
    assert_source_patterns(
        auto_movement,
        {
            "right exit moves Oak before player": (
                r"PalletMovementScript_OakMoveLeft:[\s\S]*?call MoveSprite"
                r"[\s\S]*?PalletMovementScript_PlayerMoveLeft:"
            )
        },
        "engine/overworld/auto_movement.asm",
    )
    movements = {
        "player_walk_to_lab": parse_simulated_joypad_rle(auto_movement, "RLEList_PlayerWalkToLab"),
        "oak_walk_to_lab": parse_movement(auto_movement, "RLEList_ProfOakWalkToLab", rle=True),
        "oak_lab_entry": parse_movement(oaks_lab, "OakEntryMovement", rle=False),
        "player_lab_entry": parse_simulated_joypad_rle(oaks_lab, "PlayerEntryMovementRLE"),
        "rival_charmander_below": parse_movement(oaks_lab, ".MiddleBallMovement1", rle=False),
        "rival_charmander_other": parse_movement(oaks_lab, ".MiddleBallMovement2", rle=False),
        "rival_squirtle_below": parse_movement(oaks_lab, ".RightBallMovement1", rle=False),
        "rival_squirtle_other": parse_movement(oaks_lab, ".RightBallMovement2", rle=False),
        "rival_bulbasaur_other": parse_movement_sequence(
            oaks_lab,
            (".LeftBallMovement1", ".LeftBallMovement2"),
            rle=False,
        ),
        "rival_bulbasaur_right": parse_movement(oaks_lab, ".LeftBallMovement2", rle=False),
    }
    if len(movements["player_walk_to_lab"]) != 17:
        raise ParseError("PlayerWalkToLab RLE no longer expands to 17 steps")
    if len(movements["oak_walk_to_lab"]) != 15:
        raise ParseError("ProfOakWalkToLab RLE no longer expands to 15 movement steps")

    escort = compile_warp_interrupted_movement(
        world.maps["PALLET_TOWN"],
        Position(x=10, y=1),
        movements["player_walk_to_lab"],
    )
    if escort.warp.uses_last_map or escort.warp.target_map != "OAKS_LAB":
        raise ParseError("PlayerWalkToLab no longer enters OAKS_LAB")
    target_map = world.maps[escort.warp.target_map]
    target_warp = next(
        (warp for warp in target_map.warps if warp.index == escort.warp.target_warp),
        None,
    )
    if target_warp is None:
        raise ParseError(
            f"PlayerWalkToLab warp targets missing warp {escort.warp.target_warp} "
            f"in {target_map.id}"
        )

    texts: dict[str, StoryText] = {}
    for text_id, (file, symbol) in TEXT_SOURCES.items():
        pages = parse_source_text(read(file), symbol)
        if text_id in {"received_mon", "rival_received"}:
            pages = (
                f"{'<PLAYER>' if text_id == 'received_mon' else '<RIVAL>'} received\na <SPECIES>!",
            )
        texts[text_id] = StoryText(
            id=text_id,
            pages=pages,
            provenance=_provenance(revision, file, symbol),
        )

    initial_actors = {
        map_id: tuple(
            ActorState(
                id=npc.id,
                position=npc.position,
                facing=npc.facing,
                visible=npc.visible,
                sprite=npc.sprite,
            )
            for npc in map_definition.npcs
        )
        for map_id, map_definition in world.maps.items()
    }
    starters = {
        "OAKSLAB_CHARMANDER_POKE_BALL": StarterDefinition(
            species=species["CHARMANDER"],
            ball_actor="OAKSLAB_CHARMANDER_POKE_BALL",
            rival_species=species["SQUIRTLE"],
            rival_ball_actor="OAKSLAB_SQUIRTLE_POKE_BALL",
            prompt_text="want_charmander",
        ),
        "OAKSLAB_SQUIRTLE_POKE_BALL": StarterDefinition(
            species=species["SQUIRTLE"],
            ball_actor="OAKSLAB_SQUIRTLE_POKE_BALL",
            rival_species=species["BULBASAUR"],
            rival_ball_actor="OAKSLAB_BULBASAUR_POKE_BALL",
            prompt_text="want_squirtle",
        ),
        "OAKSLAB_BULBASAUR_POKE_BALL": StarterDefinition(
            species=species["BULBASAUR"],
            ball_actor="OAKSLAB_BULBASAUR_POKE_BALL",
            rival_species=species["CHARMANDER"],
            rival_ball_actor="OAKSLAB_CHARMANDER_POKE_BALL",
            prompt_text="want_bulbasaur",
        ),
    }
    return StoryDefinition(
        start_map=start_map,
        start_position=start_position,
        start_facing=Direction.NORTH,
        event_flags=frozenset(EVENT_FLAGS),
        initial_actors=initial_actors,
        texts=texts,
        movements=movements,
        starters=starters,
        nodes=_story_nodes(
            revision,
            movements,
            starters,
            escort,
            target_warp.position,
        ),
        provenance=_provenance(revision, "data/maps/special_warps.asm", "NewGameWarp"),
    )


def _provenance(revision: str, file: str, symbol: str) -> SourceProvenance:
    return SourceProvenance(
        repository=REPOSITORY_URL,
        revision=revision,
        file=file,
        symbol=symbol,
    )


def _story_nodes(
    revision: str,
    movements: dict[str, tuple[Direction, ...]],
    starters: dict[str, StarterDefinition],
    escort: WarpInterruptedMovement,
    escort_destination: Position,
) -> tuple[StoryNode, ...]:
    """Build the validated graph consumed by the story runtime."""

    lab_script = _provenance(revision, "scripts/OaksLab.asm", "OaksLab_ScriptPointers")
    pallet_script = _provenance(revision, "scripts/PalletTown.asm", "PalletTown_ScriptPointers")
    home_script = _provenance(revision, "scripts/RedsHouse1F.asm", "RedsHouse1F_TextPointers")
    common_choice = (
        ChoiceOption(id="yes", label="YES"),
        ChoiceOption(id="no", label="NO"),
    )
    nodes: list[StoryNode] = [
        StoryNode(
            id="new_game",
            trigger=StartTrigger(),
            commands=(SetPlayerFacingCommand(facing=Direction.NORTH),),
            provenance=_provenance(revision, "data/maps/special_warps.asm", "NewGameWarp"),
        ),
        StoryNode(
            id="mom_pre_starter",
            trigger=InteractionTrigger(map_id="REDS_HOUSE_1F", actor_id="REDSHOUSE1F_MOM"),
            conditions=(StoryCondition(has_starter=False),),
            commands=(DialogCommand(interaction_id="mom_wake", text_ids=("mom_wake",)),),
            provenance=home_script,
        ),
        StoryNode(
            id="tv_normal",
            trigger=InteractionTrigger(
                map_id="REDS_HOUSE_1F",
                background_id="TEXT_REDSHOUSE1F_TV",
                facing=Direction.NORTH,
            ),
            commands=(DialogCommand(interaction_id="tv", text_ids=("tv_normal",)),),
            provenance=home_script,
        ),
        StoryNode(
            id="tv_wrong_side",
            trigger=InteractionTrigger(map_id="REDS_HOUSE_1F", background_id="TEXT_REDSHOUSE1F_TV"),
            commands=(DialogCommand(interaction_id="tv", text_ids=("tv_wrong_side",)),),
            provenance=home_script,
        ),
        StoryNode(
            id="rival_early",
            trigger=InteractionTrigger(map_id="OAKS_LAB", actor_id="OAKSLAB_RIVAL"),
            conditions=(StoryCondition(flag="EVENT_FOLLOWED_OAK_INTO_LAB_2", flag_state=False),),
            commands=(DialogCommand(interaction_id="rival", text_ids=("rival_early",)),),
            provenance=lab_script,
        ),
        StoryNode(
            id="rival_choose",
            trigger=InteractionTrigger(map_id="OAKS_LAB", actor_id="OAKSLAB_RIVAL"),
            conditions=(
                StoryCondition(flag="EVENT_FOLLOWED_OAK_INTO_LAB_2", flag_state=True),
                StoryCondition(flag="EVENT_GOT_STARTER", flag_state=False),
            ),
            commands=(DialogCommand(interaction_id="rival", text_ids=("rival_choose",)),),
            provenance=lab_script,
        ),
        StoryNode(
            id="rival_stronger",
            trigger=InteractionTrigger(map_id="OAKS_LAB", actor_id="OAKSLAB_RIVAL"),
            conditions=(StoryCondition(flag="EVENT_GOT_STARTER", flag_state=True),),
            commands=(DialogCommand(interaction_id="rival", text_ids=("rival_stronger",)),),
            provenance=lab_script,
        ),
    ]
    for column in (10, 11):
        adjustment = (
            (
                MovementCommand(
                    tracks=(
                        MovementTrackDefinition(actor_id="PALLETTOWN_OAK", steps=(Direction.WEST,)),
                    )
                ),
                MovementCommand(
                    tracks=(MovementTrackDefinition(actor_id="player", steps=(Direction.WEST,)),)
                ),
            )
            if column == 11
            else ()
        )
        nodes.append(
            StoryNode(
                id=f"oak_intercept_{column}",
                trigger=PositionTrigger(map_id="PALLET_TOWN", x=column, y=1),
                conditions=(StoryCondition(flag="EVENT_FOLLOWED_OAK_INTO_LAB", flag_state=False),),
                commands=(
                    SetFlagCommand(flag="EVENT_OAK_APPEARED_IN_PALLET"),
                    SetPlayerFacingCommand(facing=Direction.SOUTH),
                    DialogCommand(interaction_id="oak_hey_wait", text_ids=("oak_hey_wait",)),
                    SetActorCommand(map_id="PALLET_TOWN", actor_id="PALLETTOWN_OAK", visible=True),
                    MoveActorToPlayerCommand(
                        actor_id="PALLETTOWN_OAK",
                        player_offset=Position(x=0, y=1),
                    ),
                    DialogCommand(interaction_id="oak_unsafe", text_ids=("oak_unsafe",)),
                    *adjustment,
                    MovementCommand(
                        tracks=(
                            MovementTrackDefinition(actor_id="player", steps=escort.steps),
                            MovementTrackDefinition(
                                actor_id="PALLETTOWN_OAK",
                                steps=movements["oak_walk_to_lab"][: len(escort.steps)],
                            ),
                        )
                    ),
                    SetActorCommand(map_id="PALLET_TOWN", actor_id="PALLETTOWN_OAK", visible=False),
                    TransitionCommand(
                        map_id=escort.warp.target_map,
                        position=escort_destination,
                        facing=escort.steps[-1],
                    ),
                ),
                provenance=pallet_script,
            )
        )
    nodes.extend(
        [
            StoryNode(
                id="lab_entry",
                trigger=MapEnterTrigger(map_id="OAKS_LAB"),
                conditions=(
                    StoryCondition(flag="EVENT_OAK_APPEARED_IN_PALLET", flag_state=True),
                    StoryCondition(flag="EVENT_FOLLOWED_OAK_INTO_LAB", flag_state=False),
                ),
                commands=(
                    SetActorCommand(map_id="OAKS_LAB", actor_id="OAKSLAB_OAK2", visible=True),
                    MovementCommand(
                        tracks=(
                            MovementTrackDefinition(
                                actor_id="OAKSLAB_OAK2", steps=movements["oak_lab_entry"]
                            ),
                        )
                    ),
                    SetActorCommand(map_id="OAKS_LAB", actor_id="OAKSLAB_OAK2", visible=False),
                    SetActorCommand(
                        map_id="OAKS_LAB",
                        actor_id="OAKSLAB_OAK1",
                        visible=True,
                        facing=Direction.SOUTH,
                    ),
                    SetActorCommand(
                        map_id="OAKS_LAB",
                        actor_id="OAKSLAB_RIVAL",
                        facing=Direction.SOUTH,
                    ),
                    MovementCommand(
                        tracks=(
                            MovementTrackDefinition(
                                actor_id="player", steps=movements["player_lab_entry"]
                            ),
                        )
                    ),
                    SetFlagCommand(flag="EVENT_FOLLOWED_OAK_INTO_LAB"),
                    SetFlagCommand(flag="EVENT_FOLLOWED_OAK_INTO_LAB_2"),
                    SetActorCommand(
                        map_id="OAKS_LAB",
                        actor_id="OAKSLAB_RIVAL",
                        facing=Direction.NORTH,
                    ),
                    DialogCommand(
                        interaction_id="lab_intro",
                        text_ids=(
                            "rival_waiting",
                            "oak_choose",
                            "rival_what_about_me",
                            "oak_be_patient",
                        ),
                    ),
                    SetFlagCommand(flag="EVENT_OAK_ASKED_TO_CHOOSE_MON"),
                ),
                provenance=lab_script,
            ),
            StoryNode(
                id="lab_exit_pre_starter",
                trigger=PositionTrigger(map_id="OAKS_LAB", y=6),
                conditions=(
                    StoryCondition(flag="EVENT_OAK_ASKED_TO_CHOOSE_MON", flag_state=True),
                    StoryCondition(has_starter=False),
                ),
                commands=(
                    SetActorCommand(
                        map_id="OAKS_LAB",
                        actor_id="OAKSLAB_OAK1",
                        facing=Direction.SOUTH,
                    ),
                    SetActorCommand(
                        map_id="OAKS_LAB",
                        actor_id="OAKSLAB_RIVAL",
                        facing=Direction.SOUTH,
                    ),
                    DialogCommand(interaction_id="oak_dont_go", text_ids=("oak_dont_go",)),
                    MovementCommand(
                        tracks=(
                            MovementTrackDefinition(actor_id="player", steps=(Direction.NORTH,)),
                        )
                    ),
                ),
                provenance=lab_script,
            ),
            StoryNode(
                id="rival_battle_boundary",
                trigger=PositionTrigger(map_id="OAKS_LAB", y=6),
                conditions=(StoryCondition(flag="EVENT_GOT_STARTER", flag_state=True),),
                commands=(
                    SetActorCommand(
                        map_id="OAKS_LAB",
                        actor_id="OAKSLAB_RIVAL",
                        facing=Direction.SOUTH,
                    ),
                    DialogCommand(interaction_id="rival_challenge", text_ids=("rival_challenge",)),
                    MoveActorToPlayerCommand(
                        actor_id="OAKSLAB_RIVAL",
                        player_offset=Position(x=0, y=-1),
                    ),
                    PhaseBoundaryCommand(reason="rival_battle_deferred"),
                ),
                provenance=lab_script,
            ),
        ]
    )
    for ball, starter in starters.items():
        species_name = starter.species.constant.lower()
        yes_nodes = (
            f"choose_{species_name}_source_branch",
            f"choose_{species_name}_fallback",
        )
        no_node = f"decline_{starter.species.constant.lower()}"
        nodes.extend(
            [
                StoryNode(
                    id=f"inspect_{starter.species.constant.lower()}_early",
                    trigger=InteractionTrigger(map_id="OAKS_LAB", actor_id=ball),
                    conditions=(
                        StoryCondition(flag="EVENT_OAK_ASKED_TO_CHOOSE_MON", flag_state=False),
                    ),
                    commands=(DialogCommand(interaction_id=ball, text_ids=("poke_balls",)),),
                    provenance=lab_script,
                ),
                StoryNode(
                    id=f"inspect_{starter.species.constant.lower()}",
                    trigger=InteractionTrigger(map_id="OAKS_LAB", actor_id=ball),
                    conditions=(
                        StoryCondition(flag="EVENT_OAK_ASKED_TO_CHOOSE_MON", flag_state=True),
                        StoryCondition(has_starter=False),
                    ),
                    commands=(
                        DialogCommand(interaction_id=ball, text_ids=(starter.prompt_text,)),
                        ChoiceCommand(
                            id="starter_yes_no",
                            prompt="Choose this Pokémon?",
                            options=common_choice,
                            cancel_index=1,
                            branches={"yes": yes_nodes, "no": (no_node,)},
                        ),
                    ),
                    provenance=lab_script,
                ),
                StoryNode(
                    id=f"inspect_{starter.species.constant.lower()}_after",
                    trigger=InteractionTrigger(map_id="OAKS_LAB", actor_id=ball),
                    conditions=(StoryCondition(has_starter=True),),
                    commands=(DialogCommand(interaction_id=ball, text_ids=("last_mon",)),),
                    provenance=lab_script,
                ),
                StoryNode(
                    id=no_node,
                    provenance=lab_script,
                ),
            ]
        )
        branch_condition, source_steps, fallback_steps = {
            "CHARMANDER": (
                StoryCondition(player_y=4),
                movements["rival_charmander_below"],
                movements["rival_charmander_other"],
            ),
            "SQUIRTLE": (
                StoryCondition(player_y=4),
                movements["rival_squirtle_below"],
                movements["rival_squirtle_other"],
            ),
            "BULBASAUR": (
                StoryCondition(player_x=9),
                movements["rival_bulbasaur_right"],
                movements["rival_bulbasaur_other"],
            ),
        }[starter.species.constant]
        shared_commands = (
            SelectStarterCommand(starter_key=ball),
            DialogCommand(
                interaction_id=ball,
                text_ids=("mon_energetic", "received_mon"),
                species_from="player",
            ),
            GrantStarterCommand(starter_key=ball),
        )
        rival_commands = (
            SetActorCommand(
                map_id="OAKS_LAB",
                actor_id="OAKSLAB_RIVAL",
                facing=Direction.NORTH,
            ),
            DialogCommand(interaction_id="rival_take", text_ids=("rival_take",)),
            SelectRivalStarterCommand(starter_key=ball),
            GrantRivalStarterCommand(starter_key=ball),
            DialogCommand(
                interaction_id="rival_received",
                text_ids=("rival_received",),
                species_from="rival",
            ),
            SetFlagCommand(flag="EVENT_GOT_STARTER"),
        )
        source_setup = (
            (
                SetActorCommand(
                    map_id="OAKS_LAB",
                    actor_id="OAKSLAB_RIVAL",
                    position=Position(x=9, y=8),
                ),
            )
            if starter.species.constant == "BULBASAUR"
            else ()
        )
        nodes.extend(
            (
                StoryNode(
                    id=yes_nodes[0],
                    conditions=(branch_condition,),
                    commands=(
                        *shared_commands,
                        *source_setup,
                        MovementCommand(
                            tracks=(
                                MovementTrackDefinition(
                                    actor_id="OAKSLAB_RIVAL", steps=source_steps
                                ),
                            )
                        ),
                        *rival_commands,
                    ),
                    provenance=_provenance(
                        revision, "scripts/OaksLab.asm", "OaksLabChoseStarterScript"
                    ),
                ),
                StoryNode(
                    id=yes_nodes[1],
                    commands=(
                        *shared_commands,
                        MovementCommand(
                            tracks=(
                                MovementTrackDefinition(
                                    actor_id="OAKSLAB_RIVAL", steps=fallback_steps
                                ),
                            )
                        ),
                        *rival_commands,
                    ),
                    provenance=_provenance(
                        revision, "scripts/OaksLab.asm", "OaksLabChoseStarterScript"
                    ),
                ),
            )
        )
    return tuple(nodes)
