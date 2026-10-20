from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .errors import OracleError


@dataclass(frozen=True)
class Symbol:
    bank: int
    address: int


class SymbolTable:
    def __init__(self, entries: dict[str, Symbol]) -> None:
        self._entries = dict(entries)

    @classmethod
    def read(cls, path: Path) -> SymbolTable:
        if not path.is_file():
            raise OracleError(f"missing debug symbols: {path}")
        entries: dict[str, Symbol] = {}
        for line_number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            line = raw_line.partition(";")[0].strip()
            if not line:
                continue
            fields = line.split(maxsplit=1)
            if len(fields) != 2:
                raise OracleError(f"malformed symbol at {path}:{line_number}")
            location, label = fields
            bank_text, colon, address_text = location.partition(":")
            if not colon and all(character in "0123456789abcdefABCDEF" for character in location):
                # rgblink also emits bank-only constant records, which cannot
                # identify a hook or memory address.
                continue
            if not colon or not label:
                raise OracleError(f"malformed symbol at {path}:{line_number}")
            try:
                symbol = Symbol(int(bank_text, 16), int(address_text, 16))
            except ValueError as error:
                raise OracleError(f"malformed symbol address at {path}:{line_number}") from error
            if label in entries:
                raise OracleError(f"duplicate symbol {label!r} at {path}:{line_number}")
            entries[label] = symbol
        return cls(entries)

    def require(self, labels: set[str]) -> None:
        missing = sorted(labels - self._entries.keys())
        if missing:
            raise OracleError(f"debug symbols are missing required labels: {missing}")

    def __getitem__(self, label: str) -> Symbol:
        try:
            return self._entries[label]
        except KeyError as error:
            raise OracleError(f"unknown debug symbol: {label}") from error

    def __contains__(self, label: str) -> bool:
        return label in self._entries
