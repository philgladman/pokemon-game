from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Direction(StrEnum):
    NORTH = "north"
    SOUTH = "south"
    WEST = "west"
    EAST = "east"


class Position(StrictModel):
    x: int
    y: int

    def moved(self, direction: Direction) -> Position:
        dx, dy = {
            Direction.NORTH: (0, -1),
            Direction.SOUTH: (0, 1),
            Direction.WEST: (-1, 0),
            Direction.EAST: (1, 0),
        }[direction]
        return Position(x=self.x + dx, y=self.y + dy)
