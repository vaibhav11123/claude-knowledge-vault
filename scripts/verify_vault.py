#!/usr/bin/env python3
"""Verify an Obsidian vault: note counts, dangling wiki links, orphan rate."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

WIKI_LINK_RE = re.compile(r"(?<!\\)\[\[([^\]]+)\]\]")


def note_paths(vault: Path) -> dict[str, Path]:
    """Map Obsidian-style link targets (with and without .md) to files."""
    mapping: dict[str, Path] = {}
    for path in vault.rglob("*.md"):
        if ".obsidian" in path.parts:
            continue
        rel = path.relative_to(vault).as_posix()
        no_ext = rel[:-3] if rel.endswith(".md") else rel
        mapping[rel] = path
        mapping[no_ext] = path
        mapping[path.stem] = path
        # Also allow folder/stem
        mapping[f"{path.parent.relative_to(vault).as_posix()}/{path.stem}"] = path
    return mapping


def resolve_link(target: str, mapping: dict[str, Path], vault: Path) -> Path | None:
    # Strip alias: [[path|alias]]
    path_part = target.split("|", 1)[0].strip()
    # Strip heading/block refs
    path_part = path_part.split("#", 1)[0].strip()
    if not path_part:
        return None
    if path_part in mapping:
        return mapping[path_part]
    if f"{path_part}.md" in mapping:
        return mapping[f"{path_part}.md"]
    # Case-insensitive fallback
    lower = {k.lower(): v for k, v in mapping.items()}
    if path_part.lower() in lower:
        return lower[path_part.lower()]
    candidate = vault / f"{path_part}.md"
    if candidate.exists():
        return candidate
    return None


def has_linked_entities(text: str) -> bool:
    """True if conversation note has a Linked section with at least one wiki link."""
    m = re.search(r"^## Linked\s*$", text, re.M)
    if not m:
        return False
    rest = text[m.end() :]
    next_h = re.search(r"^## ", rest, re.M)
    section = rest[: next_h.start()] if next_h else rest
    return bool(WIKI_LINK_RE.search(section))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vault", type=Path, required=True, help="Path to Obsidian vault")
    args = parser.parse_args()
    vault = args.vault
    if not vault.is_dir():
        raise SystemExit(f"Vault not found: {vault}")

    md_files = [
        p for p in vault.rglob("*.md") if ".obsidian" not in p.parts
    ]
    conversations = list((vault / "Conversations").glob("*.md")) if (vault / "Conversations").is_dir() else []
    people = list((vault / "People").glob("*.md")) if (vault / "People").is_dir() else []
    projects = list((vault / "Projects").glob("*.md")) if (vault / "Projects").is_dir() else []
    topics = list((vault / "Topics").glob("*.md")) if (vault / "Topics").is_dir() else []

    mapping = note_paths(vault)
    dangling: list[tuple[Path, str]] = []

    for path in md_files:
        text = path.read_text(encoding="utf-8")
        for m in WIKI_LINK_RE.finditer(text):
            raw = m.group(1)
            if resolve_link(raw, mapping, vault) is None:
                dangling.append((path, raw))

    orphans = 0
    for path in conversations:
        text = path.read_text(encoding="utf-8")
        if not has_linked_entities(text):
            orphans += 1
    orphan_pct = (100.0 * orphans / len(conversations)) if conversations else 0.0

    print(f"Vault: {vault.resolve()}")
    print(f"  notes:         {len(md_files)}")
    print(f"  conversations: {len(conversations)}")
    print(f"  people:        {len(people)}")
    print(f"  projects:      {len(projects)}")
    print(f"  topics:        {len(topics)}")
    print(f"  orphan convs:  {orphans} ({orphan_pct:.1f}%)")
    print(f"  dangling:      {len(dangling)}")

    if dangling:
        print("\nDangling wiki links:")
        for path, raw in dangling[:50]:
            print(f"  {path.relative_to(vault)} → [[{raw}]]")
        if len(dangling) > 50:
            print(f"  … and {len(dangling) - 50} more")
        sys.exit(1)

    print("\nOK: 0 dangling links")
    sys.exit(0)


if __name__ == "__main__":
    main()
