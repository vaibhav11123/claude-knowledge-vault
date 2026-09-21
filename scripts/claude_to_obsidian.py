#!/usr/bin/env python3
"""CLI: Claude conversation export → Obsidian knowledge vault."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))

from build_obsidian_vault import (  # noqa: E402
    DEFAULT_LEXICON,
    DEFAULT_OUT,
    build_vault,
    load_lexicon,
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Convert a Claude export ZIP (or JSON directory) into an Obsidian vault."
    )
    src = parser.add_mutually_exclusive_group(required=True)
    src.add_argument("--zip", type=Path, help="Path to claude-exports-*.zip")
    src.add_argument("--json-dir", type=Path, help="Directory of conversation JSON files")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help="Output vault folder")
    parser.add_argument(
        "--lexicon",
        type=Path,
        default=DEFAULT_LEXICON,
        help="Path to lexicon.yaml",
    )
    parser.add_argument(
        "--co-occurrence",
        type=int,
        default=None,
        help="Min shared conversations for entity related edges (default from lexicon)",
    )
    parser.add_argument(
        "--suggest-lexicon",
        type=Path,
        default=None,
        help="Write candidate entity suggestions (.yaml or .md)",
    )
    parser.add_argument(
        "--merge",
        action="store_true",
        help="Incremental upsert using vault-manifest.json (do not wipe vault)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="With --merge, fully overwrite entity notes",
    )
    args = parser.parse_args()

    if args.force and not args.merge:
        print("Warning: --force has no effect without --merge", file=sys.stderr)

    if args.zip and not args.zip.exists():
        raise SystemExit(f"ZIP not found: {args.zip}")
    if args.json_dir and not args.json_dir.is_dir():
        raise SystemExit(f"JSON dir not found: {args.json_dir}")
    if not args.lexicon.exists():
        raise SystemExit(
            f"Lexicon not found: {args.lexicon}\n"
            f"Copy lexicon.example.yaml to lexicon.yaml and customize it."
        )

    lexicon = load_lexicon(args.lexicon)
    stats = build_vault(
        args.out.resolve(),
        lexicon,
        zip_path=args.zip.resolve() if args.zip else None,
        json_dir=args.json_dir.resolve() if args.json_dir else None,
        co_occurrence_min=args.co_occurrence,
        merge=args.merge,
        force=args.force,
        suggest_lexicon_path=args.suggest_lexicon,
    )

    print(f"Wrote vault → {args.out}")
    print(f"  conversations: {stats['conversations']}")
    print(f"  people:        {stats['people']}")
    print(f"  projects:      {stats['projects']}")
    print(f"  topics:        {stats['topics']}")
    print(f"  linked:        {stats['linked_convs']}")
    print(f"  orphans:       {stats['orphan_convs']} ({stats['orphan_pct']}%)")
    if args.merge:
        print(f"  written:       {stats['written_convs']}")
        print(f"  skipped:       {stats['skipped_unchanged']} (unchanged)")
    if args.suggest_lexicon:
        print(f"  suggestions →  {args.suggest_lexicon}")
    print()
    print(f"Open this folder in Obsidian: {args.out.resolve()}")


if __name__ == "__main__":
    main()
