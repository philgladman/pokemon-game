from __future__ import annotations

import argparse
from pathlib import Path

from backend.app.engine.repository import default_source_root
from backend.app.source.pokered import PokeredSource


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Parse the configured pret/pokered checkout and validate the Pallet runtime."
    )
    parser.add_argument("--source-root", type=Path, default=default_source_root())
    arguments = parser.parse_args()

    source = PokeredSource(arguments.source_root)
    world = source.build_world()
    story = source.build_story()
    battle = source.build_battle()
    print(
        f"validated {len(world.maps)} maps, {len(story.starters)} starters, "
        f"and {len(battle.moves)} first-battle moves "
        f"from pret/pokered {world.source_revision}"
    )


if __name__ == "__main__":
    main()
