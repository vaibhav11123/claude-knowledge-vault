#!/usr/bin/env python3
"""Print baseline metrics for an existing Obsidian vault as JSON."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_VAULT = ROOT / "obsidian-vault"
VERIFY_SCRIPT = ROOT / "scripts" / "verify_vault.py"

WIKI_LINK_RE = re.compile(r"(?<!!)\[\[([^\]|#]+)(?:\|[^\]]+)?\]\]")
ENTITIES_RE = re.compile(r"^entities:\s*\[(.*)\]", re.M)


def vault_size_mb(vault: Path) -> float:
    total = sum(p.stat().st_size for p in vault.rglob("*") if p.is_file())
    return round(total / (1024 * 1024), 2)


def note_index(vault: Path) -> set[str]:
    paths: set[str] = set()
    for note in vault.rglob("*.md"):
        rel = note.relative_to(vault).with_suffix("")
        paths.add(str(rel).replace("\\", "/"))
        paths.add(note.stem)
    return paths


def count_dangling_links(vault: Path) -> int:
    known = note_index(vault)
    dangling = 0
    for note in vault.rglob("*.md"):
        text = note.read_text(encoding="utf-8", errors="replace")
        for match in WIKI_LINK_RE.finditer(text):
            target = match.group(1).strip()
            if target in known:
                continue
            if (vault / f"{target}.md").exists():
                continue
            dangling += 1
    return dangling


def linked_conversation_stats(vault: Path) -> tuple[int, int, float]:
    conv_dir = vault / "Conversations"
    if not conv_dir.is_dir():
        return 0, 0, 0.0
    total = 0
    linked = 0
    for note in conv_dir.glob("*.md"):
        total += 1
        text = note.read_text(encoding="utf-8", errors="replace")
        match = ENTITIES_RE.search(text)
        if match and match.group(1).strip():
            linked += 1
    pct = round(100.0 * linked / total, 1) if total else 0.0
    return total, linked, pct


def entity_counts(vault: Path) -> tuple[int, int, int]:
    manifest = vault / ".obsidian" / "vault-manifest.json"
    if manifest.is_file():
        data = json.loads(manifest.read_text(encoding="utf-8"))
        return (
            len(data.get("people") or []),
            len(data.get("projects") or []),
            len(data.get("topics") or []),
        )
    people = len(list((vault / "People").glob("*.md"))) if (vault / "People").is_dir() else 0
    projects = len(list((vault / "Projects").glob("*.md"))) if (vault / "Projects").is_dir() else 0
    topics = len(list((vault / "Topics").glob("*.md"))) if (vault / "Topics").is_dir() else 0
    return people, projects, topics


def run_verify(vault: Path) -> dict[str, object] | None:
    if not VERIFY_SCRIPT.is_file():
        return None
    proc = subprocess.run(
        [sys.executable, str(VERIFY_SCRIPT), str(vault)],
        capture_output=True,
        text=True,
        check=False,
    )
    return {
        "ran": True,
        "exit_code": proc.returncode,
        "stdout": proc.stdout.strip(),
        "stderr": proc.stderr.strip(),
    }


def collect_metrics(vault: Path, *, run_verify_check: bool) -> dict[str, object]:
    conversation_count, linked_count, linked_pct = linked_conversation_stats(vault)
    people, projects, topics = entity_counts(vault)
    metrics: dict[str, object] = {
        "vault_path": str(vault),
        "conversation_count": conversation_count,
        "people": people,
        "projects": projects,
        "topics": topics,
        "linked_conversations": linked_count,
        "linked_pct": linked_pct,
        "dangling_links": count_dangling_links(vault),
        "vault_size_mb": vault_size_mb(vault),
    }
    if run_verify_check:
        verify = run_verify(vault)
        if verify is not None:
            metrics["verify"] = verify
    return metrics


def print_missing_instructions(vault: Path) -> None:
    print(
        f"No vault found at {vault}.\n\n"
        "To generate baseline metrics:\n"
        "  1. Export Claude chats as JSON ZIP (claude-exporter, bulk JSON, artifacts off).\n"
        "  2. Build the vault:\n"
        "       python scripts/build_obsidian_vault.py --zip claude-exports-*.zip --out obsidian-vault\n"
        "  3. Re-run:\n"
        "       python scripts/baseline_metrics.py\n",
        file=sys.stderr,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--vault",
        type=Path,
        default=DEFAULT_VAULT,
        help=f"Path to Obsidian vault (default: {DEFAULT_VAULT})",
    )
    parser.add_argument(
        "--verify",
        action="store_true",
        help="Run scripts/verify_vault.py when available and include its result",
    )
    args = parser.parse_args()
    vault = args.vault.resolve()

    if not vault.is_dir() or not (vault / "Conversations").is_dir():
        print_missing_instructions(vault)
        raise SystemExit(1)

    print(json.dumps(collect_metrics(vault, run_verify_check=args.verify), indent=2))


if __name__ == "__main__":
    main()
