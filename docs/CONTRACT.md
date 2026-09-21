# Claude export JSON contract

This document defines the input format expected by the vault builder (`scripts/build_obsidian_vault.py` and future `scripts/claude_to_obsidian.py`).

The contract matches JSON produced by [glebmish/claude-exporter](https://github.com/glebmish/claude-exporter) bulk export with **chats enabled** and **artifact extraction disabled** (conversations only, no separate artifact files).

## Conversation object (required fields)

Each `*.json` file in the export ZIP is one conversation object.

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `uuid` | string (UUID) | yes | Stable conversation id; used for dedup and note naming collisions |
| `name` | string | yes | Chat title; may be a UUID if untitled in UI |
| `summary` | string | no | Claude-generated conversation summary |
| `model` | string | no | e.g. `claude-sonnet-5` |
| `created_at` | string (ISO 8601) | yes | Conversation creation timestamp |
| `updated_at` | string (ISO 8601) | yes | Last update timestamp |
| `chat_messages` | array | yes | Ordered message list; builder skips files without this key |

### Additional fields (ignored by builder)

Exports may include `settings`, `platform`, `is_starred`, `is_archived`, `is_temporary`, `effective_thinking_mode`, `current_leaf_message_uuid`, and other metadata. The builder reads them but does not require them.

## Message object (`chat_messages[]`)

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `uuid` | string | no | Message id |
| `sender` | string | yes | `human` or `assistant` (other values rendered as-is) |
| `content` | array | yes | Ordered content blocks (see below) |
| `created_at` | string | no | Message timestamp |
| `updated_at` | string | no | Message timestamp |
| `index` | number | no | Message order hint |
| `files` | array | no | Attachment metadata |
| `attachments` | array | no | Attachment metadata |
| `text` | string | no | Legacy plain-text field; builder prefers `content` |

Messages with no renderable text, tools, or attachments are omitted from the output note.

## Content blocks (`chat_messages[].content[]`)

Each block is an object with a `type` field. The builder understands four block types.

### `text`

User or assistant prose.

```json
{
  "type": "text",
  "text": "How do I structure a referral email?"
}
```

### `tool_use`

Assistant tool invocation. The builder records tool **names** in a "Tools used" section but does not inline tool inputs or outputs.

```json
{
  "type": "tool_use",
  "id": "toolu_01TdNhQyT1eLSZTU9ecAr9e3",
  "name": "web_search",
  "input": { "query": "LinkedIn referral message" },
  "message": "Searching the web",
  "start_timestamp": "2026-07-19T21:40:40.851542Z",
  "stop_timestamp": "2026-07-19T21:40:40.880107Z"
}
```

### `thinking`

Extended thinking block. Present when the exporter includes thinking. The builder **skips** these blocks in the transcript (same as `tool_result`).

```json
{
  "type": "thinking",
  "thinking": "Let me consider the audience...",
  "summaries": [],
  "truncated": false,
  "start_timestamp": "2026-07-19T21:40:38.000000Z",
  "stop_timestamp": "2026-07-19T21:40:40.000000Z"
}
```

### `tool_result`

Tool output linked to a prior `tool_use` via `tool_use_id`. Skipped in transcript body.

```json
{
  "type": "tool_result",
  "tool_use_id": "toolu_01TdNhQyT1eLSZTU9ecAr9e3",
  "name": "web_search",
  "content": [{ "type": "knowledge", "title": "...", "text": "..." }],
  "is_error": false,
  "start_timestamp": "2026-07-19T21:40:42.180905Z",
  "stop_timestamp": "2026-07-19T21:40:42.180920Z"
}
```

## ZIP layout

The builder accepts any of these layouts and discovers all `*.json` files recursively. Non-JSON entries are ignored.

### Layout A — flat root (preferred)

Produced by claude-exporter bulk JSON export with artifacts off.

```text
claude-exports-20260922-001344.zip
├── Casual greeting.json
├── HPAIR Asia Conference 2026 application.json
├── be735ab0-3897-4374-b484-49e104ad4568.json
└── ...
```

### Layout B — `Chats/` folder

Some export tools nest conversations:

```text
export.zip
└── Chats/
    ├── My chat title.json
    └── Another chat.json
```

### Layout C — nested title folder

Occasionally a chat is wrapped in a folder named after the title:

```text
export.zip
└── My chat title/
    └── My chat title.json
```

### Artifacts (ignored)

When artifact extraction is enabled, exports may include binary or sidecar files:

```text
export.zip
├── Conversations/*.json
├── Artifacts/
│   ├── report.html
│   └── chart.png
└── ...
```

The vault builder **ignores** `Artifacts/` and any non-`.json` paths. MVP export settings should keep artifacts off so the ZIP contains only conversation JSON.

## Validation rules

A file is **importable** when:

1. It parses as JSON.
2. It contains a `chat_messages` array (may be empty).
3. Each message has `sender` and `content` (or legacy `text`).

A file is **skipped** when `chat_messages` is missing.

## Example minimal conversation

```json
{
  "uuid": "7be94ae8-50d0-48c3-ab6e-3a61c667f144",
  "name": "Casual greeting",
  "summary": "**Conversation Overview**\n\nBrief exchange about...",
  "model": "claude-sonnet-5",
  "created_at": "2026-09-16T16:49:42.309368Z",
  "updated_at": "2026-09-16T16:54:00.023455Z",
  "chat_messages": [
    {
      "uuid": "msg-001",
      "sender": "human",
      "content": [{ "type": "text", "text": "Hey" }],
      "created_at": "2026-09-16T16:49:42.309368Z"
    },
    {
      "uuid": "msg-002",
      "sender": "assistant",
      "content": [
        { "type": "text", "text": "Hello! How can I help?" }
      ],
      "created_at": "2026-09-16T16:49:45.000000Z"
    }
  ]
}
```

## Reference export

The repo includes a validated sample: `claude-exports-20260922-001344.zip` (272 conversations, flat root layout).
