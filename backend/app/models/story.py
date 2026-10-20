from __future__ import annotations

from typing import Annotated, Literal

from pydantic import ConfigDict, Field, model_validator

from .common import Direction, Position, StrictModel
from .map import SourceProvenance
from .pokemon import SpeciesDefinition

ControlMode = Literal[
    "free",
    "dialog",
    "choice",
    "scripted_movement",
    "transition",
    "phase_boundary",
]


class FrozenStrictModel(StrictModel):
    model_config = ConfigDict(frozen=True)


class ActorState(StrictModel):
    id: str
    position: Position
    facing: Direction = Field(strict=False)
    visible: bool
    sprite: str


class MapState(StrictModel):
    """Renderer-neutral map layout plus session-local mutable actors."""

    id: str
    source_name: str
    kind: Literal["outdoor", "indoor"]
    last_map_target: str | None = None
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    walkable: list[list[bool]]
    actors: list[ActorState]


class MovementTrack(StrictModel):
    model_config = ConfigDict(frozen=True)
    actor_id: str
    start: Position
    steps: tuple[Direction, ...]

    @property
    def end(self) -> Position:
        position = self.start
        for step in self.steps:
            position = position.moved(step)
        return position


class MovementCue(StrictModel):
    id: str = Field(min_length=1)
    tracks: tuple[MovementTrack, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def actor_tracks_are_unique(self) -> MovementCue:
        actor_ids = [track.actor_id for track in self.tracks]
        if len(actor_ids) != len(set(actor_ids)):
            raise ValueError("movement cue actor tracks must be unique")
        return self


class TransitionState(StrictModel):
    id: str = Field(min_length=1)


class ChoiceOption(StrictModel):
    model_config = ConfigDict(frozen=True)
    id: str
    label: str


class ChoiceState(StrictModel):
    id: str
    instance_id: str
    prompt: str
    options: tuple[ChoiceOption, ...] = Field(min_length=2)
    selected_index: int = Field(ge=0)
    cancel_index: int = Field(ge=0)

    @model_validator(mode="after")
    def indices_are_valid(self) -> ChoiceState:
        if self.selected_index >= len(self.options):
            raise ValueError("choice selected index is outside its options")
        if self.cancel_index >= len(self.options):
            raise ValueError("choice cancel index is outside its options")
        return self


class StoryText(StrictModel):
    model_config = ConfigDict(frozen=True)
    id: str
    pages: tuple[str, ...] = Field(min_length=1)
    provenance: SourceProvenance


class StarterDefinition(StrictModel):
    model_config = ConfigDict(frozen=True)
    species: SpeciesDefinition
    ball_actor: str
    rival_species: SpeciesDefinition
    rival_ball_actor: str
    prompt_text: str


class StoryCondition(FrozenStrictModel):
    flag: str | None = None
    flag_state: bool | None = None
    has_starter: bool | None = None
    player_x: int | None = None
    player_y: int | None = None

    @model_validator(mode="after")
    def flag_condition_is_complete(self) -> StoryCondition:
        if (self.flag is None) != (self.flag_state is None):
            raise ValueError("story flag conditions require both flag and flag_state")
        if (
            self.flag is None
            and self.has_starter is None
            and self.player_x is None
            and self.player_y is None
        ):
            raise ValueError("story conditions require at least one predicate")
        return self


class StartTrigger(FrozenStrictModel):
    type: Literal["start"] = "start"


class MapEnterTrigger(FrozenStrictModel):
    type: Literal["map_enter"] = "map_enter"
    map_id: str


class PositionTrigger(FrozenStrictModel):
    type: Literal["position"] = "position"
    map_id: str
    x: int | None = None
    y: int | None = None


class InteractionTrigger(FrozenStrictModel):
    type: Literal["interaction"] = "interaction"
    map_id: str
    actor_id: str | None = None
    background_id: str | None = None
    facing: Direction | None = Field(default=None, strict=False)

    @model_validator(mode="after")
    def has_one_target(self) -> InteractionTrigger:
        if (self.actor_id is None) == (self.background_id is None):
            raise ValueError("interaction triggers require exactly one target")
        return self


StoryTrigger = Annotated[
    StartTrigger | MapEnterTrigger | PositionTrigger | InteractionTrigger,
    Field(discriminator="type"),
]


class SetFlagCommand(FrozenStrictModel):
    type: Literal["set_flag"] = "set_flag"
    flag: str


class SetActorCommand(FrozenStrictModel):
    type: Literal["set_actor"] = "set_actor"
    map_id: str
    actor_id: str
    visible: bool | None = None
    position: Position | None = None
    facing: Direction | None = Field(default=None, strict=False)


class SetPlayerFacingCommand(FrozenStrictModel):
    type: Literal["set_player_facing"] = "set_player_facing"
    facing: Direction = Field(strict=False)


class DialogCommand(FrozenStrictModel):
    type: Literal["dialog"] = "dialog"
    interaction_id: str
    text_ids: tuple[str, ...] = Field(min_length=1)
    species_from: Literal["player", "rival"] | None = None


class MovementTrackDefinition(FrozenStrictModel):
    actor_id: str
    steps: tuple[Direction, ...]


class MovementCommand(FrozenStrictModel):
    type: Literal["movement"] = "movement"
    tracks: tuple[MovementTrackDefinition, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def actor_tracks_are_unique_and_nonempty(self) -> MovementCommand:
        actor_ids = [track.actor_id for track in self.tracks]
        if len(actor_ids) != len(set(actor_ids)):
            raise ValueError("movement command actor tracks must be unique")
        if any(not track.steps for track in self.tracks):
            raise ValueError("movement command tracks require at least one step")
        return self


class TransitionCommand(FrozenStrictModel):
    type: Literal["transition"] = "transition"
    map_id: str
    position: Position
    facing: Direction = Field(strict=False)


class MoveActorToPlayerCommand(FrozenStrictModel):
    type: Literal["move_actor_to_player"] = "move_actor_to_player"
    actor_id: str
    player_offset: Position


class ChoiceCommand(FrozenStrictModel):
    type: Literal["choice"] = "choice"
    id: str
    prompt: str
    options: tuple[ChoiceOption, ...] = Field(min_length=2)
    selected_index: int = 0
    cancel_index: int
    branches: dict[str, tuple[str, ...]]

    @model_validator(mode="after")
    def choice_is_complete(self) -> ChoiceCommand:
        if self.selected_index < 0 or self.selected_index >= len(self.options):
            raise ValueError("choice selected index is outside its options")
        if self.cancel_index < 0 or self.cancel_index >= len(self.options):
            raise ValueError("choice cancel index is outside its options")
        option_ids = [option.id for option in self.options]
        if len(option_ids) != len(set(option_ids)):
            raise ValueError("choice option ids must be unique")
        if set(self.branches) != set(option_ids):
            raise ValueError("choice branches must exactly match its option ids")
        if any(not candidates for candidates in self.branches.values()):
            raise ValueError("choice options require at least one branch candidate")
        if any(len(candidates) != len(set(candidates)) for candidates in self.branches.values()):
            raise ValueError("choice branch candidates must be unique")
        return self


class SelectStarterCommand(FrozenStrictModel):
    type: Literal["select_starter"] = "select_starter"
    starter_key: str


class GrantStarterCommand(FrozenStrictModel):
    type: Literal["grant_starter"] = "grant_starter"
    starter_key: str


class GrantRivalStarterCommand(FrozenStrictModel):
    type: Literal["grant_rival_starter"] = "grant_rival_starter"
    starter_key: str


class SelectRivalStarterCommand(FrozenStrictModel):
    type: Literal["select_rival_starter"] = "select_rival_starter"
    starter_key: str


class PhaseBoundaryCommand(FrozenStrictModel):
    type: Literal["phase_boundary"] = "phase_boundary"
    reason: str


StoryCommand = Annotated[
    SetFlagCommand
    | SetActorCommand
    | SetPlayerFacingCommand
    | DialogCommand
    | MovementCommand
    | MoveActorToPlayerCommand
    | TransitionCommand
    | ChoiceCommand
    | SelectStarterCommand
    | GrantStarterCommand
    | SelectRivalStarterCommand
    | GrantRivalStarterCommand
    | PhaseBoundaryCommand,
    Field(discriminator="type"),
]


class StoryNode(FrozenStrictModel):
    id: str
    trigger: StoryTrigger | None = None
    conditions: tuple[StoryCondition, ...] = ()
    commands: tuple[StoryCommand, ...] = ()
    provenance: SourceProvenance


class StoryDefinition(StrictModel):
    model_config = ConfigDict(frozen=True)
    start_map: str
    start_position: Position
    start_facing: Direction = Field(strict=False)
    event_flags: frozenset[str]
    initial_actors: dict[str, tuple[ActorState, ...]]
    texts: dict[str, StoryText]
    movements: dict[str, tuple[Direction, ...]]
    starters: dict[str, StarterDefinition]
    nodes: tuple[StoryNode, ...]
    provenance: SourceProvenance

    @model_validator(mode="after")
    def validate_story_references(self) -> StoryDefinition:
        if self.start_map not in self.initial_actors:
            raise ValueError(f"story start map {self.start_map} has no actor state")
        actor_ids = {actor.id for actors in self.initial_actors.values() for actor in actors}
        if len(actor_ids) != sum(len(actors) for actors in self.initial_actors.values()):
            raise ValueError("story actor ids must be globally unique")
        for starter in self.starters.values():
            if starter.ball_actor not in actor_ids or starter.rival_ball_actor not in actor_ids:
                raise ValueError("starter definition references an unknown ball actor")
        node_ids = {node.id for node in self.nodes}
        if len(node_ids) != len(self.nodes):
            raise ValueError("story node ids must be unique")
        nodes_by_id = {node.id: node for node in self.nodes}
        for node in self.nodes:
            trigger = node.trigger
            if (
                isinstance(trigger, (MapEnterTrigger, PositionTrigger, InteractionTrigger))
                and trigger.map_id not in self.initial_actors
            ):
                raise ValueError(f"story node {node.id} references unknown map {trigger.map_id}")
            if (
                isinstance(trigger, InteractionTrigger)
                and trigger.actor_id is not None
                and trigger.actor_id
                not in {actor.id for actor in self.initial_actors[trigger.map_id]}
            ):
                raise ValueError(
                    f"story node {node.id} references unknown actor {trigger.actor_id}"
                )
            for condition in node.conditions:
                if condition.flag is not None and condition.flag not in self.event_flags:
                    raise ValueError(
                        f"story node {node.id} references unknown flag {condition.flag}"
                    )
            for command in node.commands:
                if isinstance(command, SetFlagCommand) and command.flag not in self.event_flags:
                    raise ValueError(f"story node {node.id} sets unknown flag {command.flag}")
                if isinstance(command, SetActorCommand):
                    map_actors = self.initial_actors.get(command.map_id)
                    if map_actors is None:
                        raise ValueError(
                            f"story node {node.id} references unknown map {command.map_id}"
                        )
                    if command.actor_id not in {actor.id for actor in map_actors}:
                        raise ValueError(
                            f"story node {node.id} references unknown actor {command.actor_id}"
                        )
                if isinstance(command, MovementCommand):
                    missing_actors = {
                        track.actor_id
                        for track in command.tracks
                        if track.actor_id != "player" and track.actor_id not in actor_ids
                    }
                    if missing_actors:
                        raise ValueError(
                            f"story node {node.id} moves unknown actors: {sorted(missing_actors)}"
                        )
                if (
                    isinstance(command, MoveActorToPlayerCommand)
                    and command.actor_id not in actor_ids
                ):
                    raise ValueError(f"story node {node.id} moves unknown actor {command.actor_id}")
                if isinstance(command, DialogCommand):
                    missing_text = set(command.text_ids) - self.texts.keys()
                    if missing_text:
                        raise ValueError(
                            f"story node {node.id} references unknown text: {sorted(missing_text)}"
                        )
                if isinstance(command, ChoiceCommand):
                    branch_ids = {
                        branch_id
                        for candidates in command.branches.values()
                        for branch_id in candidates
                    }
                    missing_branches = branch_ids - node_ids
                    if missing_branches:
                        raise ValueError(
                            f"story node {node.id} has unknown continuations: "
                            f"{sorted(missing_branches)}"
                        )
                    triggered_branches = {
                        branch_id
                        for branch_id in branch_ids
                        if next(item for item in self.nodes if item.id == branch_id).trigger
                        is not None
                    }
                    if triggered_branches:
                        raise ValueError(
                            f"story node {node.id} continues into triggered nodes: "
                            f"{sorted(triggered_branches)}"
                        )
                    incomplete_options = {
                        option_id
                        for option_id, candidates in command.branches.items()
                        if nodes_by_id[candidates[-1]].conditions
                    }
                    if incomplete_options:
                        raise ValueError(
                            f"story node {node.id} lacks unconditional choice fallbacks: "
                            f"{sorted(incomplete_options)}"
                        )
                if (
                    isinstance(
                        command,
                        (
                            SelectStarterCommand,
                            GrantStarterCommand,
                            SelectRivalStarterCommand,
                            GrantRivalStarterCommand,
                        ),
                    )
                    and command.starter_key not in self.starters
                ):
                    raise ValueError(
                        f"story node {node.id} references unknown starter {command.starter_key}"
                    )
                if (
                    isinstance(command, TransitionCommand)
                    and command.map_id not in self.initial_actors
                ):
                    raise ValueError(
                        f"story node {node.id} transitions to unknown map {command.map_id}"
                    )
        return self
