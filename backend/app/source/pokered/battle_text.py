"""Strict translation of only the text controls used by the lab battle UI."""

import re

from .parsers.errors import ParseError

RAM_VARIABLES = {
    "wTrainerName": "RIVAL",
    "wEnemyMonNick": "ENEMY",
    "wBattleMonNick": "PLAYER_MON",
    "wStringBuffer": "BUFFER",
    "wNameBuffer": "PLAYER_MON",
}


def battle_text(content: str, symbol: str) -> str:
    match = re.search(rf"^{re.escape(symbol)}::\n(.*?)(?=^\w+::|\Z)", content, re.M | re.S)
    if match is None:
        raise ParseError(f"missing battle text {symbol}")
    result = ""
    for raw in match[1].splitlines():
        line = raw.split(";", 1)[0].strip()
        quoted = re.fullmatch(r'(text|line|cont|para) "([^"]*)"', line)
        if quoted:
            if quoted[1] in {"line", "cont", "para"}:
                result += "\n"
            result += quoted[2].replace("@", "")
        elif line.startswith("text_ram "):
            variable = RAM_VARIABLES.get(line.removeprefix("text_ram "))
            if variable is None:
                raise ParseError(f"unsupported battle RAM text {line}")
            result += f"<{variable}>"
        elif line in {
            "text_decimal wExpAmountGained, 2, 4",
            "text_decimal wCurEnemyLevel, 1, 3",
            "text_bcd wAmountMoneyWon, 3 | LEADING_ZEROES | LEFT_ALIGN",
        }:
            variable = {
                "wExpAmountGained": "EXPERIENCE",
                "wCurEnemyLevel": "LEVEL",
                "wAmountMoneyWon": "MONEY",
            }[line.split()[1].rstrip(",")]
            result += f"<{variable}>"
        elif line not in {"", "text_start", "text_end", "done", "prompt"}:
            raise ParseError(f"unsupported battle text control {line}")
    return result
