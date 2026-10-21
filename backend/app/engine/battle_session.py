"""A single battle's intent and acknowledged presentation lifecycle."""

from uuid import uuid4

from backend.app.engine.battle import resolve_turn
from backend.app.engine.pokemon import ByteRng, award_battle_experience, create_rival_battle
from backend.app.engine.text import resolve_text_pages
from backend.app.models.battle import BattleDefinition, BattlePokemon, MoveCommand
from backend.app.models.battle_view import (
    BattleBatch,
    BattleFrame,
    BattleMoveView,
    BattlePokemonView,
    BattleSnapshot,
)


class BattleSession:
    def __init__(
        self, definition: BattleDefinition, player: BattlePokemon, variables: dict[str, str]
    ) -> None:
        self.definition = definition
        self.variables = variables
        self.id = str(uuid4())
        self.state = create_rival_battle(definition, player)
        self.action_token: str | None = None
        self.batch: BattleBatch | None = BattleBatch(
            id=self._batch_id(),
            frames=[
                self._frame(self._text(symbol))
                for symbol in (
                    "_TrainerWantsToFightText",
                    "_TrainerSentOutText",
                )
            ]
            + [self._frame(self._text("_GoText") + self._name(player.species) + "!")],
        )

    def _name(self, species: str) -> str:
        return self.definition.species_named(species).species.name

    def _text(self, symbol: str, **extra: str) -> str:
        variables = {
            **self.variables,
            "ENEMY": self._name(self.state.rival.species),
            "PLAYER_MON": self._name(self.state.player.species),
            **extra,
        }
        return resolve_text_pages([dict(self.definition.text_templates)[symbol]], variables)[0]

    def _batch_id(self) -> str:
        return f"{self.id}:batch:{self.state.turn}"

    def _frame(self, text: str) -> BattleFrame:
        return BattleFrame(
            text=text,
            player_hp=self.state.player.hp,
            rival_hp=self.state.rival.hp,
            player_pp=[move.pp for move in self.state.player.moves],
            player_level=self.state.player.level,
            player_max_hp=self.state.player.stats.hp,
            player_stats=self.state.player.stats,
            rival_level=self.state.rival.level,
            rival_max_hp=self.state.rival.stats.hp,
            rival_stats=self.state.rival.stats,
        )

    def _pokemon(self, pokemon: BattlePokemon, *, back: bool) -> BattlePokemonView:
        names = dict(self.definition.move_names)
        name = pokemon.species.lower() + ("b" if back else "")
        category = "pokemon-back" if back else "pokemon-front"
        return BattlePokemonView(
            species=pokemon.species,
            name=self._name(pokemon.species),
            level=pokemon.level,
            hp=pokemon.hp,
            max_hp=pokemon.stats.hp,
            image_url=f"/source-assets/{category}/{name}.png",
            moves=[
                BattleMoveView(
                    slot=slot,
                    name=names[move.constant],
                    pp=move.pp,
                    max_pp=self.definition.move_named(move.constant).pp,
                )
                for slot, move in enumerate(pokemon.moves)
            ],
            stats=pokemon.stats,
            experience=pokemon.experience,
            stat_experience=pokemon.stat_experience,
        )

    def snapshot(self) -> BattleSnapshot:
        return BattleSnapshot(
            id=self.id,
            turn=self.state.turn,
            outcome=self.state.outcome,
            player=self._pokemon(self.state.player, back=True),
            rival=self._pokemon(self.state.rival, back=False),
            action_token=self.action_token,
            batch=self.batch,
        )

    def acknowledge(self, battle_id: str, batch_id: str) -> str | None:
        if battle_id != self.id or self.batch is None or batch_id != self.batch.id:
            return "stale_battle_batch"
        self.batch = None
        if self.state.outcome == "ongoing":
            self.action_token = f"{self.id}:turn:{self.state.turn}"
        return None

    def act(self, battle_id: str, token: str, slot: int | None, rng: ByteRng) -> str | None:
        if battle_id != self.id or token != self.action_token or self.action_token is None:
            return "stale_battle_action"
        if self.state.outcome != "ongoing" or self.batch is not None:
            return "battle_not_ready"
        try:
            # resolve_turn validates slots and PP before its first random draw.
            result = resolve_turn(self.definition, self.state, MoveCommand(slot=slot), rng)
        except ValueError:
            return "invalid_battle_move"
        self.action_token = None
        names = dict(self.definition.move_names)
        player_hp, rival_hp = self.state.player.hp, self.state.rival.hp
        pp = [move.pp for move in self.state.player.moves]
        display = self._frame("")
        frames: list[BattleFrame] = []
        for event in result.events:
            actor = self.state.player if event.side == "player" else self.state.rival
            target = self.state.rival if event.side == "player" else self.state.player
            user = ("Enemy " if event.side == "rival" else "") + self._name(actor.species)
            target_name = ("Enemy " if event.side == "player" else "") + self._name(target.species)
            text = ""
            if event.type == "move":
                text = (
                    user
                    + self._text("_UsedMove1Text")
                    + names[event.move]
                    + self._text("_EndUsedMove1Text")
                )
                if event.side == "player" and slot is not None:
                    pp[slot] -= 1
            elif event.type == "damage":
                if event.side == "player":
                    rival_hp -= event.amount
                else:
                    player_hp -= event.amount
                text = self._text("_CriticalHitText") if event.critical else ""
            elif event.type == "recoil":
                if event.side == "player":
                    player_hp -= event.amount
                else:
                    rival_hp -= event.amount
                text = self._text("_HitWithRecoilText", USER=user)
            elif event.type == "faint":
                text = self._text(
                    "_PlayerMonFaintedText" if event.side == "player" else "_EnemyMonFaintedText"
                )
            elif event.type == "miss":
                text = self._text("_AttackMissedText", USER=user)
            elif event.type == "stat_failed":
                text = self._text("_ButItFailedText")
            elif event.type == "stat_down":
                stat = (
                    "ATTACK"
                    if self.definition.move_named(event.move).effect == "attack_down"
                    else "DEFENSE"
                )
                text = self._text(
                    "_MonsStatsFellText", TARGET=target_name, BUFFER=stat
                ) + self._text("_FellText")
            if not text:
                text = frames[-1].text if frames else ""
            frames.append(
                display.model_copy(
                    update={
                        "text": text,
                        "player_hp": player_hp,
                        "rival_hp": rival_hp,
                        "player_pp": list(pp),
                    }
                )
            )
        self.state = award_battle_experience(self.definition, result.state)
        if self.state.outcome == "player_win":
            gained = self.state.player.experience - result.state.player.experience
            frames.append(
                frames[-1].model_copy(
                    update={
                        "text": self._text("_GainedText")
                        + self._text("_ExpPointsText", EXPERIENCE=str(gained))
                    }
                )
            )
            level_frame = self._frame(
                self._text("_GrewLevelText", LEVEL=str(self.state.player.level))
            )
            frames.append(level_frame.model_copy(update={"show_stats": True}))
            for symbol, extra in (
                ("_TrainerDefeatedText", {}),
                ("_OaksLabRivalIPickedTheWrongPokemonText", {}),
                (
                    "_MoneyForWinningText",
                    {"MONEY": str(self.definition.trainer_base_money * self.state.rival.level)},
                ),
            ):
                frames.append(self._frame(self._text(symbol, **extra)))
        elif self.state.outcome == "player_loss":
            frames.append(self._frame(self._text("_Rival1WinText")))
        self.batch = BattleBatch(id=self._batch_id(), frames=frames)
        return None
