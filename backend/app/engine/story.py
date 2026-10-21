from __future__ import annotations

from dataclasses import dataclass

from backend.app.engine.pokemon import ByteRng, generate_player_starter
from backend.app.engine.text import resolve_text_pages
from backend.app.models.battle import BattleDefinition, BattlePokemon
from backend.app.models.common import Direction, Position
from backend.app.models.map import (
    BackgroundEvent,
    NPCDefinition,
    TextInteraction,
    WorldDefinition,
)
from backend.app.models.pokemon import PartyMember
from backend.app.models.protocol import DialogState, PlayerState
from backend.app.models.story import (
    ActorState,
    ChoiceCommand,
    ChoiceState,
    ControlMode,
    DialogCommand,
    GrantRivalStarterCommand,
    GrantStarterCommand,
    HealPartyCommand,
    InteractionTrigger,
    MapEnterTrigger,
    MapState,
    MoveActorToPlayerCommand,
    MovementCommand,
    MovementCue,
    MovementTrack,
    MovementTrackDefinition,
    PhaseBoundaryCommand,
    PositionTrigger,
    SelectRivalStarterCommand,
    SelectStarterCommand,
    SetActorCommand,
    SetFlagCommand,
    SetPlayerFacingCommand,
    StartBattleCommand,
    StartTrigger,
    StoryCommand,
    StoryCondition,
    StoryDefinition,
    StoryNode,
    TransitionCommand,
    TransitionState,
)


@dataclass(frozen=True)
class StoryResult:
    action: str
    reason: str | None = None


class StoryRunner:
    """Generic executor for a validated, source-compiled story command graph."""

    def __init__(
        self,
        world: WorldDefinition,
        definition: StoryDefinition,
        battle: BattleDefinition | None = None,
        rng: ByteRng | None = None,
    ) -> None:
        self._validate_world(definition, world)
        self.world = world
        self.definition = definition
        self.battle_definition = battle
        self.rng = rng
        self.player_pokemon: BattlePokemon | None = None
        self.map_id = definition.start_map
        self.player = PlayerState(
            position=definition.start_position,
            facing=definition.start_facing,
            sprite=world.player_sprite,
        )
        self.flags: set[str] = set()
        self.has_starter = False
        self.player_starter: str | None = None
        self.rival_starter: str | None = None
        self.party: list[PartyMember] = []
        self.dialog: DialogState | None = None
        self.choice: ChoiceState | None = None
        self.movement_cue: MovementCue | None = None
        self.transition: TransitionState | None = None
        self.control_mode: ControlMode = "free"
        self._actors = {
            map_id: {actor.id: actor.model_copy(deep=True) for actor in actors}
            for map_id, actors in definition.initial_actors.items()
        }
        self._nodes = {node.id: node for node in definition.nodes}
        self._commands: list[StoryCommand] = []
        self._choice_branches: dict[str, tuple[str, ...]] = {}
        self._battle_continuations: tuple[str, ...] = ()
        self._next_cue = 1
        self._next_choice = 1
        self._next_transition = 1
        self._selected_player_starter: str | None = None
        self._selected_rival_starter: str | None = None
        start = self._match_trigger(StartTrigger())
        if start is not None:
            result = self._start_node(start)
            if result.action != "story_complete":
                raise RuntimeError("start story node may contain only immediate commands")

    @staticmethod
    def _validate_world(definition: StoryDefinition, world: WorldDefinition) -> None:
        if (
            definition.start_map != world.start_map
            or definition.start_position != world.player_spawn
        ):
            raise ValueError("story start does not match the source world start")
        if set(definition.initial_actors) != set(world.maps):
            raise ValueError("story actor maps do not match the source world maps")
        for map_id, source_map in world.maps.items():
            source_actors = {
                npc.id: (npc.position, npc.facing, npc.visible, npc.sprite)
                for npc in source_map.npcs
            }
            story_actors = {
                actor.id: (actor.position, actor.facing, actor.visible, actor.sprite)
                for actor in definition.initial_actors[map_id]
            }
            if story_actors != source_actors:
                raise ValueError(f"story actors do not match source map {map_id}")

    def map_state(self) -> MapState:
        source = self.world.maps[self.map_id]
        return MapState(
            id=source.id,
            source_name=source.source_name,
            kind=source.kind,
            last_map_target=source.last_map_target,
            width=source.width,
            height=source.height,
            walkable=source.walkable,
            actors=list(self._actors[self.map_id].values()),
        )

    def actor_at(self, map_id: str, position: Position) -> ActorState | None:
        return next(
            (
                actor
                for actor in self._actors[map_id].values()
                if actor.visible and actor.position == position
            ),
            None,
        )

    def set_player(self, map_id: str, player: PlayerState) -> None:
        self.map_id = map_id
        self.player = player

    def before_move(self, destination: Position) -> StoryResult | None:
        del destination
        if self.control_mode != "free":
            return StoryResult("blocked", f"control_{self.control_mode}")
        return None

    def after_move(self) -> StoryResult | None:
        node = self._match_trigger(
            PositionTrigger(
                map_id=self.map_id,
                x=self.player.position.x,
                y=self.player.position.y,
            )
        )
        return self._start_node(node) if node is not None else None

    def after_transition(self) -> StoryResult | None:
        node = self._match_trigger(MapEnterTrigger(map_id=self.map_id))
        return self._start_node(node) if node is not None else None

    def interact(
        self,
        actor: ActorState | None,
        npc: NPCDefinition | None,
        background: BackgroundEvent | None,
    ) -> StoryResult | None:
        del npc
        if self.control_mode == "dialog":
            return self.advance_dialog()
        if self.control_mode != "free":
            return StoryResult("blocked", f"control_{self.control_mode}")
        actor_id = actor.id if actor is not None else None
        background_id = background.interaction.reference if background is not None else None
        if actor_id is None and background_id is None:
            return None
        node = self._match_trigger(
            InteractionTrigger(
                map_id=self.map_id,
                actor_id=actor_id,
                background_id=background_id,
                facing=self.player.facing,
            )
        )
        return self._start_node(node) if node is not None else None

    def open_source_dialog(self, interaction_id: str, interaction: TextInteraction) -> None:
        """Open a direct source interaction through the story-owned dialog state."""

        if interaction.status != "direct":
            raise ValueError("only direct source interactions can open a dialog")
        self._set_dialog(
            interaction_id,
            resolve_text_pages(interaction.template_pages, self.world.text_variables),
        )

    def advance_dialog(self) -> StoryResult:
        assert self.dialog is not None
        next_page = self.dialog.page_index + 1
        if next_page < len(self.dialog.pages):
            self.dialog = self.dialog.model_copy(update={"page_index": next_page})
            return StoryResult("dialog_advanced")
        self.dialog = None
        self.control_mode = "free"
        return self._resume("dialog_closed")

    def choose(self, choice_id: str, intent: str) -> StoryResult:
        if self.control_mode != "choice" or self.choice is None:
            return StoryResult("blocked", "choice_not_open")
        if self.choice.instance_id != choice_id:
            return StoryResult("blocked", "stale_choice")
        selected = self.choice.selected_index
        if intent == "previous":
            selected = (selected - 1) % len(self.choice.options)
        elif intent == "next":
            selected = (selected + 1) % len(self.choice.options)
        elif intent == "cancel":
            return self._finish_choice(self.choice.cancel_index)
        elif intent == "confirm":
            return self._finish_choice(selected)
        self.choice = self.choice.model_copy(update={"selected_index": selected})
        return StoryResult("choice_updated")

    def acknowledge_cue(self, cue_id: str) -> StoryResult:
        cue = self.movement_cue
        if cue is None or cue.id != cue_id:
            return StoryResult("blocked", "stale_movement_cue")
        for track in cue.tracks:
            facing = track.steps[-1] if track.steps else None
            if track.actor_id == "player":
                update: dict[str, object] = {"position": track.end}
                if facing is not None:
                    update["facing"] = facing
                self.player = self.player.model_copy(update=update)
            else:
                actor = self._actor(self.map_id, track.actor_id)
                update = {"position": track.end}
                if facing is not None:
                    update["facing"] = facing
                self._actors[self.map_id][track.actor_id] = actor.model_copy(update=update)
        self.movement_cue = None
        self.control_mode = "free"
        return self._resume("movement_completed")

    def acknowledge_transition(self, transition_id: str) -> StoryResult:
        transition = self.transition
        if transition is None or transition.id != transition_id:
            return StoryResult("blocked", "stale_transition")
        self.transition = None
        self.control_mode = "free"
        entered = self._match_trigger(MapEnterTrigger(map_id=self.map_id))
        if entered is not None:
            self._commands = [*entered.commands, *self._commands]
        return self._resume("transition_completed")

    def complete_battle(self) -> StoryResult:
        """Resume the source script only after its terminal presentation was acknowledged."""
        if self.control_mode != "battle":
            raise RuntimeError("no story battle is suspended")
        branch = next(
            (
                self._nodes[node_id]
                for node_id in self._battle_continuations
                if all(
                    self._condition_matches(condition)
                    for condition in self._nodes[node_id].conditions
                )
            ),
            None,
        )
        self._battle_continuations = ()
        if branch is not None:
            self._commands = [*branch.commands, *self._commands]
        self.control_mode = "free"
        return self._resume("battle_presented")

    def sync_player_pokemon(self, pokemon: BattlePokemon) -> None:
        self.player_pokemon = pokemon
        if self.party:
            self.party = [self.party[0].model_copy(update={"level": pokemon.level})]

    def _start_node(self, node: StoryNode) -> StoryResult:
        if self._commands:
            raise RuntimeError(f"cannot start story node {node.id} while another node is active")
        self._commands = list(node.commands)
        return self._resume()

    def _resume(self, completion_action: str = "story_complete") -> StoryResult:
        while self._commands:
            command = self._commands.pop(0)
            if isinstance(command, SetFlagCommand):
                self.flags.add(command.flag)
            elif isinstance(command, SetActorCommand):
                self._set_actor(command)
            elif isinstance(command, SetPlayerFacingCommand):
                self.player = self.player.model_copy(update={"facing": command.facing})
            elif isinstance(command, SelectStarterCommand):
                self._select_starter(command.starter_key)
            elif isinstance(command, GrantStarterCommand):
                self._grant_starter(command.starter_key)
            elif isinstance(command, DialogCommand):
                self._open_dialog(command)
                return StoryResult("dialog_opened")
            elif isinstance(command, MovementCommand):
                self._open_movement(command)
                return StoryResult("scripted_movement")
            elif isinstance(command, ChoiceCommand):
                self.choice = ChoiceState(
                    id=command.id,
                    instance_id=f"choice-{self._next_choice}",
                    prompt=command.prompt,
                    options=command.options,
                    selected_index=command.selected_index,
                    cancel_index=command.cancel_index,
                )
                self._next_choice += 1
                self._choice_branches = command.branches
                self.control_mode = "choice"
                return StoryResult("choice_opened")
            elif isinstance(command, SelectRivalStarterCommand):
                self._select_rival_starter(command.starter_key)
            elif isinstance(command, GrantRivalStarterCommand):
                self._grant_rival_starter(command.starter_key)
            elif isinstance(command, MoveActorToPlayerCommand):
                if self._open_actor_movement_to_player(command):
                    return StoryResult("scripted_movement")
            elif isinstance(command, TransitionCommand):
                self.map_id = command.map_id
                self.player = self.player.model_copy(
                    update={"position": command.position, "facing": command.facing}
                )
                self.transition = TransitionState(id=f"transition-{self._next_transition}")
                self._next_transition += 1
                self.control_mode = "transition"
                return StoryResult("transitioned")
            elif isinstance(command, PhaseBoundaryCommand):
                self.control_mode = "phase_boundary"
                return StoryResult("phase_boundary", command.reason)
            elif isinstance(command, StartBattleCommand):
                if self.battle_definition is None:
                    self.control_mode = "phase_boundary"
                    return StoryResult("phase_boundary", "rival_battle_deferred")
                self.control_mode = "battle"
                self._battle_continuations = command.continuations
                return StoryResult("battle_started")
            elif isinstance(command, HealPartyCommand):
                if self.player_pokemon is None or self.battle_definition is None:
                    raise RuntimeError("HealParty requires the realized starter")
                pokemon = self.player_pokemon
                self.sync_player_pokemon(
                    pokemon.model_copy(
                        update={
                            "hp": pokemon.stats.hp,
                            "moves": tuple(
                                move.model_copy(
                                    update={
                                        "pp": self.battle_definition.move_named(move.constant).pp
                                    }
                                )
                                for move in pokemon.moves
                            ),
                            "attack_stage": 0,
                            "defense_stage": 0,
                        }
                    )
                )
            else:  # pragma: no cover
                raise AssertionError("unhandled story command")
        return StoryResult(completion_action)

    def _match_trigger(
        self, actual: StartTrigger | MapEnterTrigger | PositionTrigger | InteractionTrigger
    ) -> StoryNode | None:
        for node in self.definition.nodes:
            trigger = node.trigger
            if trigger is None or trigger.type != actual.type:
                continue
            matches = False
            if isinstance(trigger, StartTrigger) and isinstance(actual, StartTrigger):
                matches = True
            elif isinstance(trigger, MapEnterTrigger) and isinstance(actual, MapEnterTrigger):
                matches = trigger.map_id == actual.map_id
            elif isinstance(trigger, PositionTrigger) and isinstance(actual, PositionTrigger):
                matches = (
                    trigger.map_id == actual.map_id
                    and (trigger.x is None or trigger.x == actual.x)
                    and (trigger.y is None or trigger.y == actual.y)
                )
            elif isinstance(trigger, InteractionTrigger) and isinstance(actual, InteractionTrigger):
                matches = (
                    trigger.map_id == actual.map_id
                    and trigger.actor_id == actual.actor_id
                    and trigger.background_id == actual.background_id
                    and (trigger.facing is None or trigger.facing == actual.facing)
                )
            if matches and all(self._condition_matches(item) for item in node.conditions):
                return node
        return None

    def _condition_matches(self, condition: StoryCondition) -> bool:
        if condition.flag is not None:
            assert condition.flag_state is not None
            if (condition.flag in self.flags) != condition.flag_state:
                return False
        if condition.has_starter is not None and self.has_starter != condition.has_starter:
            return False
        if condition.player_x is not None and self.player.position.x != condition.player_x:
            return False
        return condition.player_y is None or self.player.position.y == condition.player_y

    def _finish_choice(self, selected: int) -> StoryResult:
        assert self.choice is not None
        option = self.choice.options[selected]
        self.choice = None
        self.control_mode = "free"
        candidates = self._choice_branches.get(option.id, ())
        branch = next(
            (
                self._nodes[node_id]
                for node_id in candidates
                if all(
                    self._condition_matches(condition)
                    for condition in self._nodes[node_id].conditions
                )
            ),
            None,
        )
        if branch is None:
            raise RuntimeError(f"choice {option.id} has no matching validated branch")
        self._choice_branches = {}
        self._commands = [*branch.commands, *self._commands]
        result = self._resume()
        return StoryResult("choice_closed", "declined") if not branch.commands else result

    def _open_dialog(self, command: DialogCommand) -> None:
        species: str | None = None
        if command.species_from == "player":
            species = self.player_starter
        elif command.species_from == "rival":
            species = self.rival_starter
        pages = [page for text_id in command.text_ids for page in self._pages(text_id, species)]
        self._set_dialog(command.interaction_id, pages)

    def _set_dialog(self, interaction_id: str, pages: list[str]) -> None:
        self.dialog = DialogState(
            interaction_id=interaction_id,
            pages=pages,
            page_index=0,
        )
        self.control_mode = "dialog"

    def _pages(self, text_id: str, species: str | None = None) -> list[str]:
        variables = dict(self.world.text_variables)
        if species is not None:
            variables["SPECIES"] = species
        return resolve_text_pages(list(self.definition.texts[text_id].pages), variables)

    def _open_movement(self, command: MovementCommand) -> None:
        tracks = tuple(
            MovementTrack(
                actor_id=track.actor_id,
                start=(
                    self.player.position
                    if track.actor_id == "player"
                    else self._actor(self.map_id, track.actor_id).position
                ),
                steps=track.steps,
            )
            for track in command.tracks
        )
        self.movement_cue = MovementCue(id=f"cue-{self._next_cue}", tracks=tracks)
        self._next_cue += 1
        self.control_mode = "scripted_movement"

    def _open_actor_movement_to_player(self, command: MoveActorToPlayerCommand) -> bool:
        actor = self._actor(self.map_id, command.actor_id)
        target = Position(
            x=self.player.position.x + command.player_offset.x,
            y=self.player.position.y + command.player_offset.y,
        )
        steps = self._source_direct_path(actor.position, target)
        if not steps:
            return False
        self._open_movement(
            MovementCommand(
                tracks=(MovementTrackDefinition(actor_id=command.actor_id, steps=steps),)
            )
        )
        return True

    @staticmethod
    def _source_direct_path(start: Position, target: Position) -> tuple[Direction, ...]:
        """Mirror Gen 1 FindPathToPlayer: reduce X on ties, otherwise the larger axis."""

        position = start
        steps: list[Direction] = []
        while position != target:
            x_distance = abs(target.x - position.x)
            y_distance = abs(target.y - position.y)
            if x_distance >= y_distance and x_distance:
                direction = Direction.EAST if target.x > position.x else Direction.WEST
            else:
                direction = Direction.SOUTH if target.y > position.y else Direction.NORTH
            steps.append(direction)
            position = position.moved(direction)
        return tuple(steps)

    def _select_starter(self, starter_key: str) -> None:
        starter = self.definition.starters[starter_key]
        self._selected_player_starter = starter_key
        self.player_starter = starter.species.constant
        self._set_actor(
            SetActorCommand(map_id=self.map_id, actor_id=starter.ball_actor, visible=False)
        )

    def _grant_starter(self, starter_key: str) -> None:
        if self._selected_player_starter != starter_key:
            raise RuntimeError("player starter grant does not match the selected starter")
        starter = self.definition.starters[starter_key]
        if self.battle_definition is not None:
            if self.rng is None or self.player_pokemon is not None:
                raise RuntimeError("starter may only be realized once")
            self.player_pokemon = generate_player_starter(
                self.battle_definition, starter.species.constant, self.rng
            )
        self.has_starter = True
        self.party = [
            PartyMember(species_id=starter.species.id, name=starter.species.name, level=5)
        ]
        self._selected_player_starter = None

    def _select_rival_starter(self, starter_key: str) -> None:
        starter = self.definition.starters[starter_key]
        self._selected_rival_starter = starter_key
        self._set_actor(
            SetActorCommand(
                map_id=self.map_id,
                actor_id=starter.rival_ball_actor,
                visible=False,
            )
        )

    def _grant_rival_starter(self, starter_key: str) -> None:
        if self._selected_rival_starter != starter_key:
            raise RuntimeError("rival starter grant does not match the selected starter")
        starter = self.definition.starters[starter_key]
        self.rival_starter = starter.rival_species.constant
        self._selected_rival_starter = None

    def _actor(self, map_id: str, actor_id: str) -> ActorState:
        try:
            return self._actors[map_id][actor_id]
        except KeyError as error:
            raise RuntimeError(f"story actor {actor_id} is unavailable in {map_id}") from error

    def _set_actor(self, command: SetActorCommand) -> None:
        actor = self._actor(command.map_id, command.actor_id)
        update: dict[str, object] = {}
        if command.visible is not None:
            update["visible"] = command.visible
        if command.position is not None:
            update["position"] = command.position
        if command.facing is not None:
            update["facing"] = command.facing
        self._actors[command.map_id][command.actor_id] = actor.model_copy(update=update)
