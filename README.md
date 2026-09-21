# Claude Knowledge Vault

Turn your Claude.ai conversation history into an **entity-linked Obsidian vault** (People / Projects / Topics) you can explore in Graph View — locally, with no LLM required.

## Why

Claude chats are high-value thinking trapped in a siloed UI. Flat importers give you one Markdown file per chat; overnight “second brain” distillers need Claude Code and hours. This project sits in between: **JSON export → linked knowledge graph in minutes**.

See [PRODUCT.md](PRODUCT.md) for the problem framing and success metrics.

## Quick start

```bash
# 1) Export JSON from Claude (Chrome extension → Export for Obsidian)
#    or use any claude-exports-*.zip of conversation JSON files

# 2) Build the vault
pip install -r requirements.txt
python scripts/claude_to_obsidian.py \
  --zip path/to/claude-exports.zip \
  --out obsidian-vault \
  --lexicon lexicon.yaml

# 3) Verify link integrity
python scripts/verify_vault.py --vault obsidian-vault

# 4) Open `obsidian-vault` as an Obsidian vault → Graph View
```

## Layout

```
├── PRODUCT.md                 # Problem, wedge, metrics
├── docs/CONTRACT.md           # JSON / ZIP contract
├── lexicon.yaml               # Your people / projects / topics
├── lexicon.example.yaml       # Starter lexicon
├── scripts/
│   ├── claude_to_obsidian.py  # CLI entry
│   ├── build_obsidian_vault.py
│   ├── verify_vault.py
│   └── baseline_metrics.py
├── claude-exporter/           # Browser extension (JSON bulk export)
└── obsidian-vault/            # Generated (gitignored)
```

## License

Exporter code under `claude-exporter/` retains its upstream MIT license. Product scripts in `scripts/` are MIT unless noted otherwise.
