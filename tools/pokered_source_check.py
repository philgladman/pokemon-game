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
    print(
        f"validated {len(world.maps)} maps and {len(story.starters)} starters "
        f"from pret/pokered {world.source_revision}"
    )


if __name__ == "__main__":
    main()
