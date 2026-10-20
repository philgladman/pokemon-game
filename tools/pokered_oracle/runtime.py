from __future__ import annotations

import copy

from backend.app.engine.game import ActionResult, GameSession
from backend.app.models.common import Direction
from backend.app.models.map import WorldDefinition
from backend.app.models.protocol import SessionSnapshot
from backend.app.models.story import StoryDefinition

from .trace import ActorTrace, SemanticState


class RuntimeAdapter:
    """Expose GameSession through the same semantic checkpoints as the ROM oracle."""

    def __init__(self, world: WorldDefinition, story: StoryDefinition) -> None:
        self.session = GameSession(world, story)
        self.species_by_id = {
            species.id: species.constant
            for starter in story.starters.values()
            for species in (starter.species, starter.rival_species)
        }
        self.frame = 0
        self.last_input: str | None = None

    def move(self, direction: Direction, *, continued: bool = False) -> ActionResult:
        self.frame += 1
        self.last_input = direction.value
        return self.session.move(direction, continued=continued)

    def interact(self) -> ActionResult:
        self.frame += 1
        self.last_input = "a"
        return self.session.interact()

    def choose(self, intent: str) -> ActionResult:
        choice = self.snapshot().choice
        if choice is None:
            return ActionResult("blocked", "choice_not_open")
        self.frame += 1
        self.last_input = intent
        return self.session.choose(choice.instance_id, intent)

    def acknowledge_cue(self) -> ActionResult:
        cue = self.snapshot().movement_cue
        if cue is None:
            return ActionResult("blocked", "stale_movement_cue")
        self.frame += max((len(track.steps) for track in cue.tracks), default=0) * 16
        self.last_input = None
        return self.session.acknowledge_cue(cue.id)

    def acknowledge_transition(self) -> ActionResult:
        transition = self.snapshot().transition
        if transition is None:
            return ActionResult("blocked", "stale_transition")
        self.frame += 32
        self.last_input = None
        return self.session.acknowledge_transition(transition.id)

    def save_checkpoint(self, name: str) -> None:
        if not hasattr(self, "_checkpoints"):
            self._checkpoints: dict[str, tuple[GameSession, int, str | None]] = {}
        self._checkpoints[name] = (copy.deepcopy(self.session), self.frame, self.last_input)

    def load_checkpoint(self, name: str) -> None:
        try:
            session, frame, last_input = self._checkpoints[name]
        except (AttributeError, KeyError) as error:
            raise ValueError(f"unknown runtime checkpoint: {name}") from error
        self.session = copy.deepcopy(session)
        self.frame = frame
        self.last_input = last_input

    def snapshot(self) -> SessionSnapshot:
        return self.session.response(None, ActionResult("connected")).state

    def capture(self, hook: str) -> SemanticState:
        state = self.snapshot()
        return SemanticState(
            frame=self.frame,
            hook=hook,
            input=self.last_input,
            map_id=state.map.id,
            player_x=state.player.position.x,
            player_y=state.player.position.y,
            facing=state.player.facing.value,
            actors=tuple(
                ActorTrace(
                    id=actor.id,
                    x=actor.position.x,
                    y=actor.position.y,
                    facing=actor.facing.value,
                    visible=actor.visible,
                )
                for actor in state.map.actors
            ),
            flags=tuple(state.flags),
            player_starter=state.player_starter,
            rival_starter=state.rival_starter,
            party=tuple(
                self.species_by_id.get(member.species_id, f"SPECIES_{member.species_id:02X}")
                for member in state.party
            ),
            party_levels=tuple(member.level for member in state.party),
            has_starter=state.has_starter,
            dialog_id=state.dialog.interaction_id if state.dialog is not None else None,
            control_mode=state.control_mode,
            choice_options=tuple(option.label for option in state.choice.options)
            if state.choice
            else None,
            choice_selected=state.choice.selected_index if state.choice else None,
        )
