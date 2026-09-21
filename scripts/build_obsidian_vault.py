#!/usr/bin/env python3
"""Build an Obsidian vault from a Claude conversation export ZIP or JSON directory."""

from __future__ import annotations

import argparse
import json
import re
import shutil
import zipfile
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

try:
    import yaml
except ImportError:  # pragma: no cover - fallback for minimal envs
    yaml = None  # type: ignore

# ---------------------------------------------------------------------------
# Paths / constants
# ---------------------------------------------------------------------------

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ZIP = ROOT / "claude-exports-20260922-001344.zip"
DEFAULT_OUT = ROOT / "obsidian-vault"
DEFAULT_LEXICON = ROOT / "lexicon.yaml"

UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.I,
)

SECRET_PATTERNS = [
    (re.compile(r"(?i)\b(sk-[a-zA-Z0-9]{20,})\b"), "[REDACTED_API_KEY]"),
    (re.compile(r"(?i)\b(sk-ant-[a-zA-Z0-9\-_]{20,})\b"), "[REDACTED_API_KEY]"),
    (re.compile(r"(?i)\b(xox[baprs]-[a-zA-Z0-9-]{10,})\b"), "[REDACTED_TOKEN]"),
    (re.compile(r"(?i)\b(ghp_[a-zA-Z0-9]{36,})\b"), "[REDACTED_TOKEN]"),
    (re.compile(r"(?i)\b(github_pat_[a-zA-Z0-9_]{20,})\b"), "[REDACTED_TOKEN]"),
    (
        re.compile(
            r"(?i)(-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----)"
            r".*?"
            r"(-----END (?:RSA |EC |OPENSSH )?PRIVATE KEY-----)",
            re.S,
        ),
        "[REDACTED_PRIVATE_KEY]",
    ),
    (
        re.compile(
            r"(?i)\b((?:mongodb(?:\+srv)?|postgres(?:ql)?|mysql|redis|amqp)://"
            r"[^\s\"']+:[^\s\"']+@[^\s\"']+)\b"
        ),
        "[REDACTED_CONNECTION_STRING]",
    ),
    (
        re.compile(
            r"(?i)\b([A-Za-z0-9_-]*(?:api[_-]?key|secret[_-]?key|access[_-]?token"
            r"|auth[_-]?token|password|passwd|client[_-]?secret)\s*[:=]\s*)(['\"]?)([^\s'\"]{8,})\2"
        ),
        r"\1\2[REDACTED]\2",
    ),
]

INVALID_FS = re.compile(r'[\\/:*?"<>|\x00-\x1f]')
WS_RE = re.compile(r"\s+")

# Capitalized multi-word phrases for lexicon suggestions (Phase 3)
CANDIDATE_RE = re.compile(
    r"\b([A-Z][a-zA-Z0-9]+(?:\s+[A-Z][a-zA-Z0-9]+){1,4})\b"
)

KIND_TYPE = {"people": "person", "projects": "project", "topics": "topic"}
KIND_FOLDER = {"people": "People", "projects": "Projects", "topics": "Topics"}


# ---------------------------------------------------------------------------
# Lexicon
# ---------------------------------------------------------------------------


@dataclass
class Lexicon:
    self_entities: set[str]
    co_occurrence_min: int
    max_entities_per_conversation: int
    # (canonical, kind, aliases)
    entities: list[tuple[str, str, list[str]]]
    org_topics: set[str]
    known_names: set[str]  # canonical + aliases, lowercased


def _minimal_yaml_load(text: str) -> dict[str, Any]:
    """Minimal YAML subset parser for lexicon structure when PyYAML is missing."""
    data: dict[str, Any] = {
        "self_entities": [],
        "co_occurrence_min": 2,
        "max_entities_per_conversation": 10,
        "people": [],
        "projects": [],
        "topics": [],
    }
    section: str | None = None
    current: dict[str, Any] | None = None

    def parse_scalar(raw: str) -> Any:
        raw = raw.strip()
        if raw.lower() in ("true", "yes"):
            return True
        if raw.lower() in ("false", "no"):
            return False
        if re.fullmatch(r"-?\d+", raw):
            return int(raw)
        if raw.startswith("[") and raw.endswith("]"):
            inner = raw[1:-1].strip()
            if not inner:
                return []
            items: list[str] = []
            buf = ""
            in_q: str | None = None
            for ch in inner:
                if in_q:
                    buf += ch
                    if ch == in_q and not buf.endswith("\\" + in_q):
                        in_q = None
                    continue
                if ch in "\"'":
                    in_q = ch
                    buf += ch
                elif ch == ",":
                    items.append(buf.strip())
                    buf = ""
                else:
                    buf += ch
            if buf.strip():
                items.append(buf.strip())
            out: list[Any] = []
            for it in items:
                if (it.startswith('"') and it.endswith('"')) or (
                    it.startswith("'") and it.endswith("'")
                ):
                    out.append(it[1:-1])
                else:
                    out.append(it)
            return out
        if (raw.startswith('"') and raw.endswith('"')) or (
            raw.startswith("'") and raw.endswith("'")
        ):
            return raw[1:-1]
        return raw

    for line in text.splitlines():
        if not line.strip() or line.strip().startswith("#"):
            continue
        if re.match(r"^[a-z_]+:", line) and not line.startswith(" "):
            key, _, rest = line.partition(":")
            section = None
            current = None
            rest = rest.strip()
            if key in ("people", "projects", "topics"):
                section = key
                continue
            if rest:
                data[key] = parse_scalar(rest)
            continue
        if section and line.strip().startswith("- name:"):
            name = parse_scalar(line.split(":", 1)[1])
            current = {"name": name, "aliases": []}
            data[section].append(current)
            continue
        if section and current is not None:
            m = re.match(r"^\s+(aliases|organization):\s*(.*)$", line)
            if m:
                field_name, val = m.group(1), m.group(2).strip()
                current[field_name] = parse_scalar(val) if val else ([] if field_name == "aliases" else True)
    return data


def load_lexicon(path: Path) -> Lexicon:
    text = path.read_text(encoding="utf-8")
    if yaml is not None:
        raw = yaml.safe_load(text) or {}
    else:
        raw = _minimal_yaml_load(text)

    entities: list[tuple[str, str, list[str]]] = []
    org_topics: set[str] = set()
    known: set[str] = set()

    for kind in ("people", "projects", "topics"):
        for entry in raw.get(kind) or []:
            if not isinstance(entry, dict):
                continue
            name = (entry.get("name") or "").strip()
            if not name:
                continue
            aliases = [a.strip() for a in (entry.get("aliases") or []) if str(a).strip()]
            entities.append((name, kind, aliases))
            known.add(name.lower())
            for a in aliases:
                known.add(a.lower())
            if kind == "topics" and entry.get("organization"):
                org_topics.add(name)

    self_entities = {str(s).strip() for s in (raw.get("self_entities") or []) if str(s).strip()}
    for s in self_entities:
        known.add(s.lower())

    return Lexicon(
        self_entities=self_entities,
        co_occurrence_min=int(raw.get("co_occurrence_min") or 2),
        max_entities_per_conversation=int(raw.get("max_entities_per_conversation") or 10),
        entities=entities,
        org_topics=org_topics,
        known_names=known,
    )


def build_matchers(lexicon: Lexicon) -> list[tuple[str, str, re.Pattern[str], int]]:
    matchers: list[tuple[str, str, re.Pattern[str], int]] = []
    for canonical, kind, aliases in lexicon.entities:
        for name in [canonical, *aliases]:
            name = name.strip()
            if not name:
                continue
            escaped = re.escape(name)
            if re.fullmatch(r"[A-Za-z0-9]{1,4}", name):
                pat = re.compile(rf"(?<![A-Za-z0-9]){escaped}(?![A-Za-z0-9])", re.I)
            else:
                pat = re.compile(escaped, re.I)
            matchers.append((canonical, kind, pat, len(name)))
    matchers.sort(key=lambda x: -x[3])
    return matchers


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class Entity:
    name: str
    kind: str  # people | projects | topics
    conversations: set[str] = field(default_factory=set)  # note basenames
    related: set[str] = field(default_factory=set)  # other entity names
    tags: list[str] = field(default_factory=list)


@dataclass
class Conversation:
    uuid: str
    title: str
    note_basename: str  # filename without .md
    created_at: str
    updated_at: str
    model: str
    summary: str
    body_md: str
    entity_names: list[str] = field(default_factory=list)
    tool_names: list[str] = field(default_factory=list)
    attachment_names: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def clean_unicode(text: str) -> str:
    """Drop lone surrogates that appear in some export strings."""
    return text.encode("utf-8", errors="surrogatepass").decode("utf-8", errors="replace")


def redact(text: str) -> str:
    out = clean_unicode(text)
    for pat, repl in SECRET_PATTERNS:
        out = pat.sub(repl, out)
    return out


def sanitize_filename(name: str, max_len: int = 120) -> str:
    name = clean_unicode(name)
    name = INVALID_FS.sub("", name)
    name = WS_RE.sub(" ", name).strip(" .")
    name = name.replace("\n", " ").replace("\r", "")
    if not name:
        name = "Untitled"
    if len(name) > max_len:
        name = name[: max_len - 1].rstrip() + "…"
    return name


def yaml_escape(value: str) -> str:
    if value is None:
        return '""'
    if re.search(r'[:#\[\]{},&*?|!<>=%@`"\n]', value) or value.startswith(("'", '"')):
        return json.dumps(value, ensure_ascii=False)
    return value


def fmt_date(iso: str | None) -> str:
    if not iso:
        return ""
    try:
        return datetime.fromisoformat(iso.replace("Z", "+00:00")).strftime("%Y-%m-%d")
    except ValueError:
        return iso[:10]


def parse_iso(iso: str | None) -> datetime | None:
    if not iso:
        return None
    try:
        return datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except ValueError:
        return None


def first_human_snippet(data: dict[str, Any], limit: int = 60) -> str:
    for msg in data.get("chat_messages") or []:
        if msg.get("sender") != "human":
            continue
        for block in msg.get("content") or []:
            if isinstance(block, dict) and block.get("type") == "text":
                text = (block.get("text") or "").strip()
                if text:
                    text = WS_RE.sub(" ", text)
                    return text[:limit]
        files = msg.get("files") or []
        if files:
            fn = files[0].get("file_name") or files[0].get("name") or "attachment"
            return f"Attachment {fn}"[:limit]
    return ""


def resolve_title(data: dict[str, Any], zip_entry: str) -> str:
    name = (data.get("name") or "").strip()
    stem = Path(zip_entry).stem
    if name and not UUID_RE.match(name):
        return name
    if stem and not UUID_RE.match(stem) and stem.lower() != "untitled":
        if name:
            return name
        return stem
    snippet = first_human_snippet(data)
    date = fmt_date(data.get("created_at"))
    if snippet:
        return f"{snippet}" if not UUID_RE.match(stem) else f"{snippet} ({date})"
    return f"Untitled {date or (data.get('uuid') or 'chat')[:8]}"


def extract_message_text(msg: dict[str, Any]) -> tuple[str, list[str], list[str]]:
    """Return (text, tool_names, attachment_names) for one message."""
    texts: list[str] = []
    tools: list[str] = []
    attachments: list[str] = []

    for block in msg.get("content") or []:
        if not isinstance(block, dict):
            continue
        btype = block.get("type")
        if btype == "text":
            t = block.get("text") or ""
            if t.strip():
                texts.append(t)
        elif btype == "tool_use":
            tools.append(block.get("name") or "tool")

    for f in msg.get("files") or []:
        if isinstance(f, dict):
            attachments.append(f.get("file_name") or f.get("name") or "file")
        elif isinstance(f, str):
            attachments.append(f)
    for a in msg.get("attachments") or []:
        if isinstance(a, dict):
            attachments.append(a.get("file_name") or a.get("name") or "attachment")
        elif isinstance(a, str):
            attachments.append(a)

    return "\n".join(texts), tools, attachments


def conversation_body(data: dict[str, Any]) -> tuple[str, list[str], list[str]]:
    parts: list[str] = []
    all_tools: list[str] = []
    all_attachments: list[str] = []
    tool_seen: set[str] = set()

    for msg in data.get("chat_messages") or []:
        sender = msg.get("sender") or "unknown"
        label = "You" if sender == "human" else "Claude" if sender == "assistant" else sender
        text, tools, attachments = extract_message_text(msg)
        for t in tools:
            if t not in tool_seen:
                tool_seen.add(t)
                all_tools.append(t)
        all_attachments.extend(attachments)

        meta_bits: list[str] = []
        if attachments:
            meta_bits.append("attachments: " + ", ".join(attachments))
        if tools:
            uniq: list[str] = []
            seen: set[str] = set()
            for t in tools:
                if t not in seen:
                    seen.add(t)
                    uniq.append(t)
            meta_bits.append("tools: " + ", ".join(uniq))

        if not text.strip() and not meta_bits:
            continue

        parts.append(f"### {label}")
        if meta_bits:
            parts.append("*" + "; ".join(meta_bits) + "*")
            parts.append("")
        if text.strip():
            parts.append(escape_body_wikilinks(redact(text.rstrip())))
            parts.append("")

    return "\n".join(parts).rstrip() + "\n", all_tools, list(dict.fromkeys(all_attachments))


def match_entities(
    text: str,
    matchers: list[tuple[str, str, re.Pattern[str], int]],
    self_entities: set[str],
    max_entities: int = 10,
) -> list[str]:
    found: list[tuple[int, str]] = []
    occupied: list[tuple[int, int]] = []

    def overlaps(a: int, b: int) -> bool:
        for s, e in occupied:
            if a < e and b > s:
                return True
        return False

    for canonical, _kind, pat, _alen in matchers:
        for m in pat.finditer(text):
            if overlaps(m.start(), m.end()):
                continue
            found.append((m.start(), canonical))
            occupied.append((m.start(), m.end()))
            break

    ordered: list[str] = []
    seen: set[str] = set()
    for _, name in sorted(found, key=lambda x: x[0]):
        if name in seen:
            continue
        if name in self_entities:
            continue
        seen.add(name)
        ordered.append(name)
        if len(ordered) >= max_entities:
            break
    return ordered


def wiki_link(kind: str, name: str) -> str:
    folder = KIND_FOLDER[kind]
    path_name = sanitize_filename(name)
    if path_name == name:
        return f"[[{folder}/{name}|{name}]]"
    return f"[[{folder}/{path_name}|{name}]]"


def conv_link(basename: str) -> str:
    return f"[[Conversations/{basename}|{basename}]]"


def escape_body_wikilinks(text: str) -> str:
    """Prevent incidental [[...]] in transcripts from becoming Obsidian edges."""
    return text.replace("[[", r"\[\[")


def is_artifacts_path(path: str) -> bool:
    norm = path.replace("\\", "/")
    parts = norm.split("/")
    return any(p == "Artifacts" for p in parts)


# ---------------------------------------------------------------------------
# Ingest
# ---------------------------------------------------------------------------


def load_conversations_from_zip(zip_path: Path) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    with zipfile.ZipFile(zip_path) as zf:
        for name in zf.namelist():
            if not name.endswith(".json"):
                continue
            if is_artifacts_path(name):
                continue
            try:
                data = json.loads(zf.read(name))
            except (json.JSONDecodeError, UnicodeDecodeError):
                continue
            if not isinstance(data, dict) or "chat_messages" not in data:
                continue
            data["_zip_entry"] = name
            out.append(data)
    out.sort(key=lambda d: d.get("created_at") or "")
    return out


def load_conversations_from_dir(json_dir: Path) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for path in sorted(json_dir.rglob("*.json")):
        rel = str(path.relative_to(json_dir)).replace("\\", "/")
        if is_artifacts_path(rel):
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError, OSError):
            continue
        if not isinstance(data, dict) or "chat_messages" not in data:
            continue
        data["_zip_entry"] = rel
        out.append(data)
    out.sort(key=lambda d: d.get("created_at") or "")
    return out


def load_conversations(
    *,
    zip_path: Path | None = None,
    json_dir: Path | None = None,
) -> list[dict[str, Any]]:
    if zip_path and json_dir:
        raise ValueError("Provide either zip_path or json_dir, not both")
    if zip_path:
        return load_conversations_from_zip(zip_path)
    if json_dir:
        return load_conversations_from_dir(json_dir)
    raise ValueError("Provide zip_path or json_dir")


def unique_basenames(titles: list[str], uuids: list[str]) -> list[str]:
    counts: dict[str, int] = defaultdict(int)
    bases: list[str] = []
    for title, uid in zip(titles, uuids):
        base = sanitize_filename(title)
        counts[base.lower()] += 1
        bases.append(base)

    seen: dict[str, int] = defaultdict(int)
    result: list[str] = []
    for base, uid in zip(bases, uuids):
        key = base.lower()
        if counts[key] > 1:
            short = (uid or "xxxx")[:8]
            candidate = sanitize_filename(f"{base} ({short})")
            result.append(candidate)
        else:
            seen[key] += 1
            if seen[key] > 1:
                result.append(sanitize_filename(f"{base} ({uid[:8]})"))
            else:
                result.append(base)
    return result


# ---------------------------------------------------------------------------
# Suggestions (Phase 3)
# ---------------------------------------------------------------------------


# Boilerplate phrases that appear in Claude summaries but are not entities
SUGGESTION_STOP = {
    "conversation overview",
    "tool knowledge",
    "key decisions",
    "next steps",
    "action items",
    "main topics",
    "open questions",
}


def suggest_lexicon_candidates(
    conversations: Iterable[Conversation],
    lexicon: Lexicon,
    min_freq: int = 3,
) -> list[dict[str, Any]]:
    counts: Counter[str] = Counter()
    for conv in conversations:
        haystack = f"{conv.title}\n{conv.summary}"
        for m in CANDIDATE_RE.finditer(haystack):
            phrase = WS_RE.sub(" ", m.group(1)).strip()
            if phrase.lower() in lexicon.known_names:
                continue
            if phrase.lower() in SUGGESTION_STOP:
                continue
            if len(phrase) < 4:
                continue
            counts[phrase] += 1

    suggestions = [
        {"name": name, "frequency": freq, "suggested_kind": "topics", "aliases": []}
        for name, freq in counts.most_common()
        if freq >= min_freq
    ]
    return suggestions


def write_suggestions(path: Path, suggestions: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.suffix.lower() in {".md", ".markdown"}:
        lines = [
            "# Lexicon suggestions",
            "",
            "Candidates from titles/summaries (capitalized multi-word, freq ≥ 3).",
            "Review and copy into `lexicon.yaml` — nothing is auto-added.",
            "",
        ]
        if not suggestions:
            lines.append("_No candidates found._")
        else:
            for s in suggestions:
                lines.append(
                    f"- **{s['name']}** — frequency {s['frequency']} "
                    f"(suggested: {s['suggested_kind']})"
                )
            lines.append("")
        path.write_text("\n".join(lines), encoding="utf-8")
        return

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "note": "Review candidates; copy into lexicon.yaml — nothing is auto-added.",
        "candidates": suggestions,
    }
    if yaml is not None:
        path.write_text(
            yaml.safe_dump(payload, sort_keys=False, allow_unicode=True),
            encoding="utf-8",
        )
    else:
        path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


# ---------------------------------------------------------------------------
# Manifest / merge helpers
# ---------------------------------------------------------------------------


def load_manifest(out_dir: Path) -> dict[str, Any]:
    path = out_dir / ".obsidian" / "vault-manifest.json"
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def conversation_is_newer(new_updated: str, old_updated: str | None) -> bool:
    if not old_updated:
        return True
    new_dt = parse_iso(new_updated)
    old_dt = parse_iso(old_updated)
    if new_dt and old_dt:
        return new_dt > old_dt
    return (new_updated or "") > (old_updated or "")


def soft_update_entity_note(
    path: Path,
    ent: Entity,
    entities: dict[str, Entity],
) -> None:
    """Refresh Conversations / related sections; preserve other user content."""
    existing = path.read_text(encoding="utf-8")
    # Drop previous machine sections we manage, then append regenerated ones.
    body = existing
    for heading in (
        "## Related People",
        "## Related Projects",
        "## Related Topics",
        "## Connected projects",
        "## People",
        "## Topics / research",
        "## Conversations",
    ):
        idx = body.find(f"\n{heading}\n")
        if idx == -1 and body.startswith(heading + "\n"):
            idx = 0
        if idx != -1:
            # Find next ## heading after this one
            rest = body[idx + 1 :]
            next_h = re.search(r"\n## ", rest)
            if next_h:
                end = idx + 1 + next_h.start()
                body = body[:idx] + body[end:]
            else:
                body = body[:idx].rstrip() + "\n"

    body = body.rstrip() + "\n\n"
    body += format_entity_sections(ent, entities)
    path.write_text(body, encoding="utf-8")


def format_entity_sections(ent: Entity, entities: dict[str, Entity]) -> str:
    kind_heading = {"people": "People", "projects": "Projects", "topics": "Topics"}
    related_by_kind: dict[str, list[str]] = defaultdict(list)
    for rel in sorted(ent.related):
        if rel in entities:
            related_by_kind[entities[rel].kind].append(rel)

    lines: list[str] = []
    for kind, label in (
        ("projects", "Connected projects"),
        ("people", "People"),
        ("topics", "Topics / research"),
    ):
        if kind == ent.kind:
            peers = related_by_kind.get(kind) or []
            if peers:
                lines.append(f"## Related {kind_heading[kind]}")
                lines.append("")
                for n in peers:
                    lines.append(f"- {wiki_link(kind, n)}")
                lines.append("")
        else:
            items = related_by_kind.get(kind) or []
            if items:
                lines.append(f"## {label}")
                lines.append("")
                for n in items:
                    lines.append(f"- {wiki_link(kind, n)}")
                lines.append("")

    convs = sorted(ent.conversations)
    lines.append("## Conversations")
    lines.append("")
    for b in convs:
        lines.append(f"- {conv_link(b)}")
    lines.append("")
    return "\n".join(lines)


def format_entity_note(ent: Entity, entities: dict[str, Entity]) -> str:
    lines = [
        "---",
        f"type: {KIND_TYPE[ent.kind]}",
        f"kind: {ent.kind}",
        f"name: {yaml_escape(ent.name)}",
    ]
    if ent.tags:
        lines.append(f"tags: [{', '.join(ent.tags)}]")
    lines.extend(["---", "", f"# {ent.name}", ""])
    lines.append(format_entity_sections(ent, entities).rstrip())
    lines.append("")
    return "\n".join(lines)


def format_conversation_note(conv: Conversation, entities: dict[str, Entity]) -> str:
    linked_lines = []
    by_kind: dict[str, list[str]] = defaultdict(list)
    for name in conv.entity_names:
        if name in entities:
            by_kind[entities[name].kind].append(name)
    for kind, label in (
        ("people", "People"),
        ("projects", "Projects"),
        ("topics", "Topics"),
    ):
        if by_kind[kind]:
            linked_lines.append(
                f"**{label}:** " + ", ".join(wiki_link(kind, n) for n in by_kind[kind])
            )

    front = [
        "---",
        "type: conversation",
        f"uuid: {conv.uuid}",
        f"title: {yaml_escape(conv.title)}",
        f"created: {fmt_date(conv.created_at)}",
        f"updated: {fmt_date(conv.updated_at)}",
        f"model: {yaml_escape(conv.model)}",
        f"entities: [{', '.join(yaml_escape(n) for n in conv.entity_names)}]",
        "---",
        "",
        f"# {conv.title}",
        "",
    ]
    if conv.summary:
        front.extend(["## Summary", "", conv.summary, ""])
    if linked_lines:
        front.extend(["## Linked", ""] + linked_lines + [""])
    if conv.tool_names:
        front.extend(
            [
                "## Tools used",
                "",
                ", ".join(f"`{t}`" for t in conv.tool_names),
                "",
            ]
        )
    if conv.attachment_names:
        front.extend(
            [
                "## Attachments",
                "",
                *[f"- {a}" for a in conv.attachment_names],
                "",
            ]
        )
    front.extend(["## Conversation", "", conv.body_md])
    return "\n".join(front)


def write_obsidian_config(out_dir: Path) -> None:
    (out_dir / ".obsidian").mkdir(parents=True, exist_ok=True)
    app_json = {
        "promptDelete": False,
        "alwaysUpdateLinks": True,
        "newFileLocation": "folder",
        "newFileFolderPath": "Conversations",
        "attachmentFolderPath": "Attachments",
    }
    graph_json = {
        "collapse-filter": False,
        "search": "",
        "showTags": False,
        "showAttachments": False,
        "hideUnresolved": True,
        "showOrphans": True,
        "collapse-color-groups": False,
        "colorGroups": [
            {"query": "path:Conversations", "color": {"a": 1, "rgb": 5419488}},
            {"query": "path:People", "color": {"a": 1, "rgb": 14701138}},
            {"query": "path:Projects", "color": {"a": 1, "rgb": 5431378}},
            {"query": "path:Topics", "color": {"a": 1, "rgb": 16750899}},
            {"query": "file:Index", "color": {"a": 1, "rgb": 16777215}},
        ],
        "collapse-display": False,
        "showArrow": False,
        "textFadeMultiplier": 0,
        "nodeSizeMultiplier": 1,
        "lineSizeMultiplier": 1,
        "collapse-forces": False,
        "centerStrength": 0.5,
        "repelStrength": 10,
        "linkStrength": 1,
        "linkDistance": 250,
        "scale": 1,
    }
    appearance = {"accentColor": "", "cssTheme": "", "theme": "system"}
    (out_dir / ".obsidian" / "app.json").write_text(
        json.dumps(app_json, indent=2), encoding="utf-8"
    )
    (out_dir / ".obsidian" / "graph.json").write_text(
        json.dumps(graph_json, indent=2), encoding="utf-8"
    )
    (out_dir / ".obsidian" / "appearance.json").write_text(
        json.dumps(appearance, indent=2), encoding="utf-8"
    )
    (out_dir / ".obsidian" / "core-plugins.json").write_text(
        json.dumps(
            {
                "file-explorer": True,
                "global-search": True,
                "switcher": True,
                "graph": True,
                "backlink": True,
                "outgoing-link": True,
                "tag-pane": True,
                "page-preview": True,
                "daily-notes": False,
                "templates": False,
                "note-composer": True,
                "command-palette": True,
                "editor-status": True,
                "bookmarks": True,
                "outline": True,
                "word-count": True,
            },
            indent=2,
        ),
        encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# Build
# ---------------------------------------------------------------------------


def build_vault(
    out_dir: Path,
    lexicon: Lexicon,
    *,
    zip_path: Path | None = None,
    json_dir: Path | None = None,
    co_occurrence_min: int | None = None,
    merge: bool = False,
    force: bool = False,
    suggest_lexicon_path: Path | None = None,
    source_label: str | None = None,
) -> dict[str, Any]:
    raw = load_conversations(zip_path=zip_path, json_dir=json_dir)
    matchers = build_matchers(lexicon)
    co_min = co_occurrence_min if co_occurrence_min is not None else lexicon.co_occurrence_min
    max_ents = lexicon.max_entities_per_conversation

    if source_label is None:
        if zip_path:
            source_label = zip_path.name
        elif json_dir:
            source_label = json_dir.name
        else:
            source_label = "unknown"

    titles = [resolve_title(d, d["_zip_entry"]) for d in raw]
    uuids = [d.get("uuid") or Path(d["_zip_entry"]).stem for d in raw]
    basenames = unique_basenames(titles, uuids)

    entities: dict[str, Entity] = {}
    for canonical, kind, _aliases in lexicon.entities:
        tags = ["organization"] if canonical in lexicon.org_topics else []
        entities[canonical] = Entity(name=canonical, kind=kind, tags=tags)

    conversations: list[Conversation] = []
    for data, title, basename in zip(raw, titles, basenames):
        body, tools, attachments = conversation_body(data)
        summary = redact((data.get("summary") or "").strip())
        haystack = f"{title}\n{summary}"
        ent_names = match_entities(haystack, matchers, lexicon.self_entities, max_ents)

        conv = Conversation(
            uuid=data.get("uuid") or "",
            title=title,
            note_basename=basename,
            created_at=data.get("created_at") or "",
            updated_at=data.get("updated_at") or "",
            model=data.get("model") or "",
            summary=summary,
            body_md=body,
            entity_names=ent_names,
            tool_names=tools,
            attachment_names=attachments,
        )
        conversations.append(conv)

    if suggest_lexicon_path:
        suggestions = suggest_lexicon_candidates(conversations, lexicon, min_freq=3)
        write_suggestions(suggest_lexicon_path, suggestions)

    manifest_old = load_manifest(out_dir) if merge else {}
    old_by_uuid: dict[str, Any] = {}
    if merge:
        # Support both new and legacy manifest shapes
        old_convs = manifest_old.get("conversations") or {}
        if isinstance(old_convs, dict):
            old_by_uuid = old_convs
        # Legacy: assignments by basename only — no uuid index

    # Decide which conversations to write
    to_write: list[Conversation] = []
    skipped_unchanged = 0
    if merge and out_dir.exists():
        for conv in conversations:
            prev = old_by_uuid.get(conv.uuid) if conv.uuid else None
            if prev and not conversation_is_newer(conv.updated_at, prev.get("updated_at")):
                # Keep previous basename for entity graph consistency if present
                if prev.get("note_basename"):
                    conv.note_basename = prev["note_basename"]
                if prev.get("entity_names") is not None and not force:
                    # Prefer fresh entity match from this import; still use basename
                    pass
                skipped_unchanged += 1
                # Still include in graph via entity_names from this run
                continue
            to_write.append(conv)
    else:
        to_write = list(conversations)

    for conv in conversations:
        for name in conv.entity_names:
            if name in entities:
                entities[name].conversations.add(conv.note_basename)

    # Co-occurrence edges
    name_list = [e.name for e in entities.values() if e.conversations]
    for i, a in enumerate(name_list):
        set_a = entities[a].conversations
        for b in name_list[i + 1 :]:
            shared = set_a & entities[b].conversations
            if len(shared) >= co_min:
                entities[a].related.add(b)
                entities[b].related.add(a)

    if not merge:
        if out_dir.exists():
            shutil.rmtree(out_dir)
        for sub in ("Conversations", "People", "Projects", "Topics", ".obsidian"):
            (out_dir / sub).mkdir(parents=True, exist_ok=True)
    else:
        for sub in ("Conversations", "People", "Projects", "Topics", ".obsidian"):
            (out_dir / sub).mkdir(parents=True, exist_ok=True)

    # Conversation notes
    for conv in to_write:
        path = out_dir / "Conversations" / f"{conv.note_basename}.md"
        # On merge, remove stale file if basename changed for same uuid
        if merge and conv.uuid:
            prev = old_by_uuid.get(conv.uuid) or {}
            old_base = prev.get("note_basename")
            if old_base and old_base != conv.note_basename:
                old_path = out_dir / "Conversations" / f"{old_base}.md"
                if old_path.exists():
                    old_path.unlink()
        path.write_text(format_conversation_note(conv, entities), encoding="utf-8")

    # Entity notes
    for ent in entities.values():
        if not ent.conversations:
            continue
        path = out_dir / KIND_FOLDER[ent.kind] / f"{sanitize_filename(ent.name)}.md"
        if merge and path.exists() and not force:
            soft_update_entity_note(path, ent, entities)
        else:
            path.write_text(format_entity_note(ent, entities), encoding="utf-8")

    # Index / MOC with stats (Phase 3)
    people = sorted(e.name for e in entities.values() if e.kind == "people" and e.conversations)
    projects = sorted(
        e.name for e in entities.values() if e.kind == "projects" and e.conversations
    )
    topics = sorted(e.name for e in entities.values() if e.kind == "topics" and e.conversations)
    convs_sorted = sorted(conversations, key=lambda c: c.created_at or "", reverse=True)
    linked_convs = sum(1 for c in conversations if c.entity_names)
    orphan_convs = len(conversations) - linked_convs
    orphan_pct = (100.0 * orphan_convs / len(conversations)) if conversations else 0.0
    built_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    index = [
        "---",
        "type: index",
        "---",
        "",
        "# Claude Knowledge Vault",
        "",
        "## Build stats",
        "",
        f"- **Built at:** {built_at}",
        f"- **Source:** `{source_label}`",
        f"- **Conversations:** {len(conversations)}",
        f"- **People:** {len(people)}",
        f"- **Projects:** {len(projects)}",
        f"- **Topics:** {len(topics)}",
        f"- **Orphan conversations:** {orphan_convs} ({orphan_pct:.1f}%)",
        "",
        f"Built from `{source_label}` — **{len(conversations)}** conversations, "
        f"**{len(people)}** people, **{len(projects)}** projects, **{len(topics)}** topics.",
        "",
        "Open this folder as an Obsidian vault and use **Graph View** to navigate.",
        "",
        "## Maps of content",
        "",
        "### People",
        "",
    ]
    index.extend(f"- {wiki_link('people', n)}" for n in people)
    if not people:
        index.append("- _(none)_")
    index.extend(["", "### Projects", ""])
    index.extend(f"- {wiki_link('projects', n)}" for n in projects)
    if not projects:
        index.append("- _(none)_")
    index.extend(["", "### Topics", ""])
    index.extend(f"- {wiki_link('topics', n)}" for n in topics)
    if not topics:
        index.append("- _(none)_")
    index.extend(["", "## Conversations (newest first)", ""])
    index.extend(
        f"- {conv_link(c.note_basename)} — `{fmt_date(c.created_at)}`"
        for c in convs_sorted
    )
    index.append("")
    (out_dir / "Index.md").write_text("\n".join(index), encoding="utf-8")

    write_obsidian_config(out_dir)

    manifest = {
        "source_zip": str(zip_path) if zip_path else None,
        "source_json_dir": str(json_dir) if json_dir else None,
        "source_label": source_label,
        "built_at": built_at,
        "conversation_count": len(conversations),
        "people": people,
        "projects": projects,
        "topics": topics,
        "orphan_count": orphan_convs,
        "orphan_pct": round(orphan_pct, 2),
        "conversations": {
            c.uuid: {
                "note_basename": c.note_basename,
                "updated_at": c.updated_at,
                "created_at": c.created_at,
                "entity_names": c.entity_names,
            }
            for c in conversations
            if c.uuid
        },
        "assignments": {
            c.note_basename: c.entity_names for c in conversations if c.entity_names
        },
    }
    if merge and old_by_uuid:
        # Preserve uuid entries not present in this import
        merged_convs = dict(old_by_uuid)
        merged_convs.update(manifest["conversations"])
        manifest["conversations"] = merged_convs

    (out_dir / ".obsidian" / "vault-manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    return {
        "conversations": len(conversations),
        "people": len(people),
        "projects": len(projects),
        "topics": len(topics),
        "linked_convs": linked_convs,
        "orphan_convs": orphan_convs,
        "orphan_pct": round(orphan_pct, 1),
        "written_convs": len(to_write),
        "skipped_unchanged": skipped_unchanged,
        "merge": merge,
        "source": source_label,
        "built_at": built_at,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--zip", type=Path, default=None)
    parser.add_argument("--json-dir", type=Path, default=None)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--lexicon", type=Path, default=DEFAULT_LEXICON)
    parser.add_argument("--co-occurrence", type=int, default=None)
    parser.add_argument("--suggest-lexicon", type=Path, default=None)
    parser.add_argument("--merge", action="store_true")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    zip_path = args.zip
    json_dir = args.json_dir
    if zip_path is None and json_dir is None:
        zip_path = DEFAULT_ZIP

    if zip_path and not zip_path.exists():
        raise SystemExit(f"ZIP not found: {zip_path}")
    if json_dir and not json_dir.is_dir():
        raise SystemExit(f"JSON dir not found: {json_dir}")
    if not args.lexicon.exists():
        raise SystemExit(f"Lexicon not found: {args.lexicon}")

    lexicon = load_lexicon(args.lexicon)
    stats = build_vault(
        args.out,
        lexicon,
        zip_path=zip_path,
        json_dir=json_dir,
        co_occurrence_min=args.co_occurrence,
        merge=args.merge,
        force=args.force,
        suggest_lexicon_path=args.suggest_lexicon,
    )
    print(f"Wrote vault → {args.out}")
    for k, v in stats.items():
        print(f"  {k}: {v}")


if __name__ == "__main__":
    main()
