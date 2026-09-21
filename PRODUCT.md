# Claude Knowledge Vault

Turn months of Claude conversations into a local, entity-linked Obsidian vault you can navigate in Graph View—without calling an LLM.

## Problem

Heavy Claude users accumulate high-value thinking that stays trapped in the chat UI: hard to search across threads, easy to re-explain the same context, and fragile if a session or account access changes. Official export helps ownership, but the default outcome is still a raw dump.

Existing tools split into two camps that leave a gap:

| Camp | What you get | What's still painful |
|------|--------------|----------------------|
| **Flat importers** | One Markdown note per chat, nice formatting | Graph is mostly orphan chat nodes; no People / Projects / Topics hubs |
| **LLM distillers** | Overnight wiki, insights, topic extraction | Hours to days, needs API or Claude Code, expensive, fragile pipelines |

Examples of flat importers: [Nexus AI Chat Importer](https://github.com/superkikim/nexus-ai-chat-importer), obsidian-chat-sync, glebmish/claude-exporter. Examples of distillers: ai-conversation-extractor, ai-second-brain, claude-brain-builder.

## Wedge

**Local, no-LLM conversion** of Claude JSON into an Obsidian vault with four linked layers:

- **Conversations** — one note per chat, with summary and transcript
- **People / Projects / Topics** — hub notes with backlinks and co-occurrence edges

Entity linking uses a configurable lexicon and title/summary matching—not generative summarization. Graph View is useful on day one.

## Architecture

```text
Claude.ai (logged in)
    → claude-exporter (JSON ZIP, session cookies)
    → scripts/claude_to_obsidian.py
    → build_obsidian_vault.py + lexicon.yaml
    → obsidian-vault/
    → Obsidian Graph View
```

**Happy-path export settings:** bulk JSON, chats on, artifacts off → flat root `*.json` inside `claude-exports-{datetime}.zip`.

**Differentiation in one sentence:** Faster than distillers, more navigable than flat importers—entity hubs without calling an LLM.

## Success metrics (MVP)

| North-star | Definition | MVP bar |
|------------|------------|---------|
| **Time-to-graph** | First useful Obsidian Graph from Claude history | **< 5 minutes** |
| **Coverage** | Chats present as notes | **100%** of JSON conversations |
| **Link integrity** | Resolvable `[[wiki links]]` | **100%** (0 dangling links) |
| **Navigability** | Answer "everything about X" via a hub note | Spot-check 3 hubs succeed |
| **Privacy** | Data leaves machine | **Never** (local only) |

## Differentiation

### vs Nexus AI Chat Importer (flat archive)

Nexus and similar importers produce well-formatted chat Markdown but treat each conversation as an isolated node. You get search and folders, not a knowledge graph of people, projects, and recurring topics. This product adds entity hub notes, wiki links from conversations to hubs, and co-occurrence edges between hubs—so Graph View surfaces structure, not a hairball of chat orphans.

### vs LLM distillers (overnight second brain)

Distillers re-read every conversation through an LLM to infer topics, summaries, and wiki structure. That can be rich, but it is slow, costs money, depends on API availability, and drifts when prompts or models change. This product is deterministic: same ZIP + same lexicon → same vault in seconds, fully offline after export, with secrets redacted by pattern rules.

## Non-goals (MVP)

- Multi-provider import (ChatGPT, Gemini)
- Live auto-sync with Claude
- LLM summarization or topic inference
- Cloud accounts or hosted vaults

## Repo map

```text
├── PRODUCT.md                 ← this file
├── lexicon.yaml               ← entity definitions (Phase 1)
├── claude-exporter/           ← browser extension to pull JSON ZIP
├── scripts/
│   ├── claude_to_obsidian.py  ← CLI entry (Phase 1)
│   ├── build_obsidian_vault.py
│   ├── baseline_metrics.py
│   └── verify_vault.py        ← link integrity checks (Phase 1)
└── obsidian-vault/            ← generated output
```
