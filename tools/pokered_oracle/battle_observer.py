"""Read-only observation of the pinned ROM's battle decision random stream."""

from dataclasses import dataclass, field
from pathlib import Path

from .emulator import OracleEmulator
from .errors import OracleError


@dataclass(frozen=True)
class RandomDraw:
    bank: int
    return_address: int
    value: int
    reason: str


@dataclass
class ObservedAction:
    side: str
    move: int
    after: dict[str, object] = field(default_factory=dict)
    critical: bool = False
    missed: bool = False
    failed: bool = False


class BattleObserver:
    def __init__(self, emulator: OracleEmulator, rom: Path) -> None:
        self.emulator = emulator
        self.draws: list[RandomDraw] = []
        self.active = False
        self.actions: list[ObservedAction] = []
        self.boundary: str | None = None
        self.preheal: dict[str, object] | None = None
        self.printed_texts: list[str] = []
        self._rom = rom.read_bytes()
        symbols = emulator.symbols
        random = symbols["Random"]
        implementation = symbols["Random_"]
        bankswitch = symbols["Bankswitch"]
        # home/random.asm: push hl/de/bc; farcall Random_; load hRandomAdd;
        # pop bc/de/hl; ret. Validate every byte before deriving the ret hook.
        expected = bytes(
            (
                0xE5,
                0xD5,
                0xC5,
                0x06,
                implementation.bank,
                0x21,
                implementation.address & 255,
                implementation.address >> 8,
                0xCD,
                bankswitch.address & 255,
                bankswitch.address >> 8,
                0xF0,
                symbols["hRandomAdd"].address & 255,
                0xC1,
                0xD1,
                0xE1,
                0xC9,
            )
        )
        if self._bytes(random.bank, random.address, len(expected)) != expected:
            raise OracleError("Random implementation differs from pinned home/random.asm")
        trainer = symbols["TrainerAI.getpointer"]
        # engine/battle/trainer_ai.asm: load the AI pointer; call Random; jp hl.
        trainer_bytes = bytes(
            (0x2A, 0x66, 0x6F, 0xCD, random.address & 255, random.address >> 8, 0xE9)
        )
        if self._bytes(trainer.bank, trainer.address, len(trainer_bytes)) != trainer_bytes:
            raise OracleError("TrainerAI differs from pinned engine/battle/trainer_ai.asm")
        self._trainer_return = trainer.address + len(trainer_bytes) - 1
        emulator.port.hook(random.bank, random.address + len(expected) - 1, self._random_return)
        callbacks = {
            "DisplayUsedMoveText": self._move,
            "MainInBattleLoop": lambda _: self._finish("turn"),
            "HandlePlayerMonFainted": lambda _: self._finish("player_loss"),
            "HandleEnemyMonFainted": lambda _: self._finish("player_win"),
            "HandleIfPlayerMoveMissed": self._damage_test,
            "HandleIfEnemyMoveMissed": self._damage_test,
            "MoveMissed": lambda _: self._flag("missed"),
            "CantLowerAnymore": lambda _: self._flag("failed"),
            "OaksLabRivalEndBattleScript": self._preheal,
            "PrintText": self._printed_text,
        }
        for label, callback in callbacks.items():
            symbol = symbols[label]
            emulator.port.hook(symbol.bank, symbol.address, callback)

    def _printed_text(self, _: object) -> None:
        if not self.active:
            return
        address = self.emulator.port.register("HL")
        bank = self.read("hLoadedROMBank")
        for label in ("OaksLabOak1Text.RaiseYourYoungPokemonText", "OaksLabLastMonText"):
            symbol = self.emulator.symbols[label]
            if (bank, address) == (symbol.bank, symbol.address):
                self.printed_texts.append(label)

    def _preheal(self, _: object) -> None:
        if self.active and self.preheal is None:
            self.preheal = self.party_state()

    def party_state(self) -> dict[str, object]:
        money = "".join(f"{self.read('wPlayerMoney', i):02x}" for i in range(3))
        return {
            "species_id": self.read("wPartyMon1Species"),
            "level": self.read("wPartyMon1Level"),
            "dvs": [self.read("wPartyMon1DVs", i) for i in range(2)],
            "hp": self.word("wPartyMon1HP"),
            "stats": {
                name: self.word(f"wPartyMon1{label}")
                for name, label in (
                    ("hp", "MaxHP"),
                    ("attack", "Attack"),
                    ("defense", "Defense"),
                    ("speed", "Speed"),
                    ("special", "Special"),
                )
            },
            "moves": [self.read("wPartyMon1Moves", i) for i in range(4)],
            "pp": [self.read("wPartyMon1PP", i) for i in range(4)],
            "experience": sum(self.read("wPartyMon1Exp", i) << (16 - i * 8) for i in range(3)),
            "stat_experience": [
                self.word(f"wPartyMon1{name}Exp")
                for name in ("HP", "Attack", "Defense", "Speed", "Special")
            ],
            "status": self.read("wPartyMon1Status"),
            "money": int(money),
        }

    def read(self, label: str, offset: int = 0) -> int:
        return self.emulator.port.read(self.emulator.symbols[label].address + offset)

    def word(self, label: str) -> int:
        return self.read(label) * 256 + self.read(label, 1)

    def combat_state(self) -> dict[str, object]:
        return {
            "player_hp": self.word("wBattleMonHP"),
            "rival_hp": self.word("wEnemyMonHP"),
            "player_pp": [self.read("wBattleMonPP", i) for i in range(4)],
            "player_attack_stage": self.read("wPlayerMonAttackMod") - 7,
            "player_defense_stage": self.read("wPlayerMonDefenseMod") - 7,
            "rival_attack_stage": self.read("wEnemyMonAttackMod") - 7,
            "rival_defense_stage": self.read("wEnemyMonDefenseMod") - 7,
            "player_attack": self.word("wBattleMonAttack"),
            "player_defense": self.word("wBattleMonDefense"),
            "rival_attack": self.word("wEnemyMonAttack"),
            "rival_defense": self.word("wEnemyMonDefense"),
        }

    def _move(self, _: object) -> None:
        if not self.active:
            return
        self._finish_action()
        side = "rival" if self.read("hWhoseTurn") else "player"
        move = self.read("wEnemyMoveNum" if side == "rival" else "wPlayerMoveNum")
        self.actions.append(ObservedAction(side, move))

    def _finish_action(self) -> None:
        if self.actions and not self.actions[-1].after:
            self.actions[-1].after = self.combat_state()

    def _finish(self, boundary: str) -> None:
        if self.active and self.actions:
            self._finish_action()
            self.boundary = boundary

    def _flag(self, name: str) -> None:
        if self.active and self.actions:
            setattr(self.actions[-1], name, True)

    def _damage_test(self, _: object) -> None:
        if self.active and self.actions:
            self.actions[-1].critical = bool(self.read("wCriticalHitOrOHKO"))
            self.actions[-1].missed = bool(self.read("wMoveMissed"))

    def _bytes(self, bank: int, address: int, count: int) -> bytes:
        offset = address if address < 0x4000 else bank * 0x4000 + address - 0x4000
        return self._rom[offset : offset + count]

    def _random_return(self, _: object) -> None:
        if not self.active:
            return
        port, symbols = self.emulator.port, self.emulator.symbols
        stack = port.register("SP")
        returned = port.read(stack) | port.read(stack + 1) << 8
        bank = port.read(symbols["hLoadedROMBank"].address)
        caller = self._bytes(bank, returned - 3, 3)
        battle_random = symbols["BattleRandom"].address
        random = symbols["Random"].address
        battle_call = caller == bytes((0xCD, battle_random & 255, battle_random >> 8))
        trainer = symbols["TrainerAI.getpointer"]
        trainer_call = (
            bank == trainer.bank
            and returned == self._trainer_return
            and caller == bytes((0xCD, random & 255, random >> 8))
        )
        if (bank == symbols["BattleRandom"].bank and battle_call) or trainer_call:
            reason = (
                "TrainerAI"
                if trainer_call
                else max(
                    (
                        label
                        for label in (
                            "MainInBattleLoop",
                            "SelectEnemyMove",
                            "CriticalHitTest",
                            "MoveHitTest",
                            "RandomizeDamage",
                            "StatModifierDownEffect",
                        )
                        if symbols[label].bank == bank and symbols[label].address < returned
                    ),
                    key=lambda label: symbols[label].address,
                )
            )
            self.draws.append(RandomDraw(bank, returned, port.register("A"), reason))

    def reset(self) -> None:
        self.draws.clear()
        self.actions.clear()
        self.boundary = None
