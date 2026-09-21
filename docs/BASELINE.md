# Baseline metrics (Phase 0)

Snapshot of the vault built from `claude-exports-20260922-001344.zip` on the reference machine. Re-measure after each phase with:

```bash
python scripts/baseline_metrics.py
```

## Measured (2026-09-22)

| Metric | Value |
|--------|-------|
| Source ZIP | `claude-exports-20260922-001344.zip` (~70 MB) |
| Conversations | **272** |
| People hubs | **7** |
| Project hubs | **16** |
| Topic hubs | **69** |
| Linked conversations | **261 / 272 (96.0%)** |
| Dangling wiki links | **0** |
| Vault size | **11.29 MB** |

Raw JSON from `baseline_metrics.py`:

```json
{
  "vault_path": "/Users/vaibhavsingh/Downloads/takehomeassignmentnextsteps/obsidian-vault",
  "conversation_count": 272,
  "people": 7,
  "projects": 16,
  "topics": 69,
  "linked_conversations": 261,
  "linked_pct": 96.0,
  "dangling_links": 0,
  "vault_size_mb": 11.29
}
```

## Build performance (reference)

| Metric | Value |
|--------|-------|
| ZIP → vault wall time | **< 10 s** (~70 MB ZIP, 272 chats) |
| End-to-end time-to-graph | Target **< 5 min** (export + build + open Obsidian) |

## Pass/fail vs MVP bars

| North-star | MVP bar | Baseline |
|------------|---------|----------|
| Coverage | 100% of JSON conversations | **272 / 272** ✓ |
| Link integrity | 0 dangling links | **0** ✓ |
| Linked conversations | — | **~96%** (261/272) |
| Vault size | text-only, tools omitted | **~12 MB** ✓ |
| Privacy | local only | ✓ (no network in build) |

## Notes

- **Unlinked conversations (11):** chats whose title + summary did not match any lexicon entity; expected until lexicon expansion (Phase 3).
- **Linked % definition:** conversation note has a non-empty `entities:` frontmatter list.
- **Dangling links:** every `[[wiki link]]` in the vault resolves to an existing `.md` note.

## Regenerating the vault

```bash
python scripts/build_obsidian_vault.py \
  --zip claude-exports-20260922-001344.zip \
  --out obsidian-vault
```

Then re-run baseline metrics.
