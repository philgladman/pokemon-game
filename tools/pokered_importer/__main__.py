from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml

from .importer import ImporterError, import_pallet_town

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SOURCE = PROJECT_ROOT / "external" / "pokered"
DEFAULT_OUTPUT = PROJECT_ROOT / "data" / "yaml" / "imported" / "pallet_town.yaml"


def main() -> None:
    parser = argparse.ArgumentParser(description="Import supported map data from pret/pokered.")
    selection = parser.add_mutually_exclusive_group(required=True)
    selection.add_argument("--map", choices=("pallet_town",))
    selection.add_argument("--all", action="store_true", help="Reserved for a later project phase.")
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--check",
        action="store_true",
        help="Fail if checked-in imported data has drifted.",
    )
    arguments = parser.parse_args()

    if arguments.all:
        parser.error("--all is not implemented in Phase 1; use --map pallet_town")

    try:
        bundle = import_pallet_town(arguments.source)
    except ImporterError as error:
        parser.error(str(error))
    rendered = yaml.safe_dump(bundle.model_dump(mode="json"), sort_keys=False, allow_unicode=True)

    if arguments.check:
        try:
            existing = arguments.output.read_text(encoding="utf-8")
        except OSError as error:
            print(f"missing generated import: {arguments.output}", file=sys.stderr)
            raise SystemExit(1) from error
        if existing != rendered:
            print("imported source data is stale; rerun the importer", file=sys.stderr)
            raise SystemExit(1)
        print(f"import check passed: {arguments.output}")
        return

    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(rendered, encoding="utf-8")
    print(f"wrote {arguments.output}")


if __name__ == "__main__":
    main()
