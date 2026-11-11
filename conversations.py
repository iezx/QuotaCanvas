#!/usr/bin/env python3
"""
Local Conversation Reader & Scheduled Auto-Message Sender for:
- OpenAI Codex (~/.codex/state_5.sqlite & sessions/**/*.jsonl[.zst])
- Google Antigravity AGY (~/.gemini/antigravity-cli/conversation_summaries.db & brain/*)
- Anthropic Claude Code (~/.claude/projects/**/*.jsonl)
"""

from __future__ import annotations

from contextlib import closing
import datetime
import glob
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import subprocess
import threading
import time
import uuid
from typing import Any
from compressed_logs import iter_log_lines
from runtime_paths import get_data_dir
from remote_access import secure_write
import codex_commands

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = get_data_dir(BASE_DIR)
SCHEDULES_FILE = DATA_DIR / "schedules.json"
HISTORY_FILE = DATA_DIR / "send_history.json"

CODEX_HOME = Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex"))).expanduser()
AGY_HOME = Path(
    os.environ.get("AGY_HOME", str(Path.home() / ".gemini" / "antigravity-cli"))
).expanduser()
CLAUDE_HOME = Path(os.environ.get("CLAUDE_HOME", str(Path.home() / ".claude"))).expanduser()

_LOCK = threading.Lock()


def _parse_iso_to_epoch(ts_str: str | None) -> int:
    if not ts_str:
        return 0
    s = str(ts_str).strip()
    if not s or s.startswith("0001-01-01"):
        return 0
    try:
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        # Handle nanoseconds in Python <3.11 or extra precision
        if "." in s:
            plus_idx = max(s.find("+", 10), s.find("-", 10))
            if plus_idx != -1:
                frac = s[s.find(".") + 1 : plus_idx][:6]
                s = s[: s.find(".")] + "." + frac + s[plus_idx:]
            else:
                frac = s[s.find(".") + 1 :][:6]
                s = s[: s.find(".")] + "." + frac
        return int(datetime.datetime.fromisoformat(s).timestamp())
    except Exception:
        return 0


def list_codex_conversations(include_subthreads: bool = False, limit: int = 100) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    db_path = CODEX_HOME / "state_5.sqlite"
    if db_path.is_file():
        try:
            conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=5)
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
            where_clause = (
                ""
                if include_subthreads
                else "WHERE COALESCE(title,'') != 'Guardian review' AND COALESCE(model,'') != 'codex-auto-review' AND COALESCE(source,'') NOT LIKE '%subagent%'"
            )
            cur.execute(
                f"""
                SELECT id, rollout_path, created_at, updated_at, source, model_provider,
                       cwd, title, tokens_used, model, first_user_message, preview, name, archived
                FROM threads
                {where_clause}
                ORDER BY updated_at DESC
                LIMIT ?
                """,
                (limit * 2,),
            )
            for row in cur.fetchall():
                r = dict(row)
                title = (r.get("name") or r.get("title") or r.get("preview") or r.get("first_user_message") or "").strip()
                model = r.get("model") or ""
                src_raw = str(r.get("source") or "")
                is_sub = (
                    "subagent" in src_raw
                    or title == "Guardian review"
                    or model == "codex-auto-review"
                    or title.startswith(" You are reviewing ")
                )
                if is_sub and not include_subthreads:
                    continue
                if not title and "subagent" in src_raw:
                    try:
                        sp = (json.loads(src_raw).get("subagent") or {}).get("thread_spawn") or {}
                        title = f"[Subagent {sp.get('agent_nickname') or ''}] {sp.get('agent_path') or ''}".strip()
                    except Exception:
                        pass
                preview = (r.get("first_user_message") or r.get("preview") or title or "").strip()
                items.append(
                    {
                        "id": r["id"],
                        "source": "codex",
                        "source_name": "OpenAI Codex",
                        "title": (title[:120] if title else f"Codex Session {r['id'][:8]}"),
                        "preview": preview[:240],
                        "cwd": r.get("cwd") or str(BASE_DIR),
                        "model": model or "gpt-6.1-sol",
                        "created_at": int(r.get("created_at") or 0),
                        "updated_at": int(r.get("updated_at") or 0),
                        "tokens_used": int(r.get("tokens_used") or 0),
                        "rollout_path": r.get("rollout_path") or "",
                        "is_subthread": is_sub,
                        "status": "archived" if r.get("archived") else "idle",
                    }
                )
                if len(items) >= limit:
                    break
            conn.close()
        except Exception:
            pass
    return items


def list_agy_conversations(limit: int = 100) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    db_path = AGY_HOME / "conversation_summaries.db"
    if db_path.is_file():
        try:
            conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=5)
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
            cur.execute(
                """
                SELECT conversation_id, title, preview, step_count, last_modified_time,
                       workspace_uris, status, source, project_id, agent_name
                FROM conversation_summaries
                ORDER BY last_modified_time DESC
                LIMIT ?
                """,
                (limit,),
            )
            for row in cur.fetchall():
                r = dict(row)
                cid = r["conversation_id"]
                step_count = int(r.get("step_count") or 0)
                title = (r.get("title") or r.get("preview") or "").strip()
                upd = _parse_iso_to_epoch(r.get("last_modified_time"))
                t_path = AGY_HOME / "brain" / cid / ".system_generated" / "logs" / "transcript.jsonl"
                if upd <= 0 and t_path.is_file():
                    upd = int(t_path.stat().st_mtime)
                if step_count == 0 and not title and not t_path.is_file():
                    continue
                cwd = str(BASE_DIR)
                try:
                    uris = json.loads(r.get("workspace_uris") or "[]")
                    if uris and isinstance(uris, list) and str(uris[0]).startswith("file://"):
                        cwd = str(uris[0])[7:]
                except Exception:
                    pass
                seen_ids.add(cid)
                raw_status = str(r.get("status") or "")
                status = "running" if "RUNNING" in raw_status else "idle"
                items.append(
                    {
                        "id": cid,
                        "source": "agy",
                        "source_name": "Antigravity (AGY)",
                        "title": title or f"AGY 对话 {cid[:8]}",
                        "preview": (r.get("preview") or title or "")[:240],
                        "cwd": cwd,
                        "model": r.get("agent_name") or "gemini-3.8-flash-high",
                        "created_at": upd,
                        "updated_at": upd,
                        "step_count": step_count,
                        "tokens_used": 0,
                        "transcript_path": str(t_path) if t_path.is_file() else "",
                        "is_subthread": False,
                        "status": status,
                    }
                )
            conn.close()
        except Exception:
            pass

    # Also check brain/* directories in case any conversation is not in conversation_summaries.db
    for t_file in sorted(
        glob.glob(str(AGY_HOME / "brain" / "*" / ".system_generated" / "logs" / "transcript.jsonl"))
    ):
        tp = Path(t_file)
        cid = tp.parent.parent.parent.name
        if cid in seen_ids:
            continue
        st = tp.stat()
        first_msg = ""
        step_cnt = 0
        try:
            with open(tp, "r", encoding="utf-8", errors="ignore") as f:
                for line in f:
                    step_cnt += 1
                    if not first_msg and '"USER_INPUT"' in line:
                        obj = json.loads(line)
                        c = (obj.get("content") or "").strip()
                        if c and not c.startswith("User changed setting"):
                            first_msg = c[:120]
        except Exception:
            pass
        items.append(
            {
                "id": cid,
                "source": "agy",
                "source_name": "Antigravity (AGY)",
                "title": first_msg[:80] if first_msg else f"AGY 对话 {cid[:8]}",
                "preview": first_msg[:240],
                "cwd": str(BASE_DIR),
                "model": "gemini-3.8-flash-high",
                "created_at": int(st.st_mtime),
                "updated_at": int(st.st_mtime),
                "step_count": step_cnt,
                "tokens_used": 0,
                "transcript_path": str(tp),
                "is_subthread": False,
                "status": "idle",
            }
        )
    return items


def list_claude_conversations(limit: int = 100) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    proj_dir = CLAUDE_HOME / "projects"
    if not proj_dir.is_dir():
        return items
    jsonl_files = sorted(
        glob.glob(str(proj_dir / "**" / "*.jsonl"), recursive=True),
        key=lambda p: os.path.getmtime(p),
        reverse=True,
    )[:limit]
    for jp in jsonl_files:
        p = Path(jp)
        cid = p.stem
        st = p.stat()
        title = ""
        cwd = str(BASE_DIR)
        model = "claude-sonnet-4-5"
        tok_total = 0
        try:
            with open(p, "r", encoding="utf-8", errors="ignore") as f:
                for line in f:
                    if not line.strip():
                        continue
                    obj = json.loads(line)
                    if obj.get("cwd"):
                        cwd = obj["cwd"]
                    msg = obj.get("message") or {}
                    if isinstance(msg, dict):
                        if msg.get("model"):
                            model = msg["model"]
                        u = msg.get("usage") or {}
                        if isinstance(u, dict):
                            tok_total += int(u.get("input_tokens") or 0) + int(
                                u.get("cache_read_input_tokens") or 0
                            ) + int(u.get("output_tokens") or 0)
                        if not title and obj.get("type") == "user":
                            content = msg.get("content")
                            if isinstance(content, str) and content.strip():
                                title = content.strip()
                            elif isinstance(content, list):
                                for part in content:
                                    if isinstance(part, dict) and part.get("type") == "text":
                                        title = (part.get("text") or "").strip()
                                        if title:
                                            break
        except Exception:
            pass
        items.append(
            {
                "id": cid,
                "source": "cc",
                "source_name": "Claude Code",
                "title": (title[:100] if title else f"Claude Session {cid[:8]}"),
                "preview": title[:240],
                "cwd": cwd,
                "model": model,
                "created_at": int(st.st_mtime),
                "updated_at": int(st.st_mtime),
                "tokens_used": tok_total,
                "transcript_path": str(p),
                "is_subthread": False,
                "status": "idle",
            }
        )
    return items


def list_all_conversations(
    source_filter: str | None = None, include_subthreads: bool = False, limit: int = 100
) -> list[dict[str, Any]]:
    res: list[dict[str, Any]] = []
    if not source_filter or source_filter == "all" or source_filter == "codex":
        res.extend(list_codex_conversations(include_subthreads=include_subthreads, limit=limit))
    if not source_filter or source_filter == "all" or source_filter == "agy":
        res.extend(list_agy_conversations(limit=limit))
    if not source_filter or source_filter == "all" or source_filter == "cc":
        res.extend(list_claude_conversations(limit=limit))
    res.sort(key=lambda x: x.get("updated_at") or 0, reverse=True)
    return res[:limit]


def create_conversation(payload):
    source = payload.get('source', 'codex')
    cwd, prompt = payload.get('cwd'), payload.get('prompt')
    model, effort = payload.get('model') or None, payload.get('effort') or None
    if source not in ('codex', 'agy', 'cc'):
        raise ValueError('Unsupported conversation source')
    if not isinstance(cwd, str) or not Path(cwd).is_absolute() or not Path(cwd).is_dir():
        raise ValueError('Choose an existing absolute project directory')
    if not isinstance(prompt, str) or not prompt.strip() or len(prompt) > 40000 or prompt.lstrip().startswith('/'):
        raise ValueError('Start the conversation with a message of 1–40000 characters')
    if model is not None and (not isinstance(model, str) or len(model) > 120):
        raise ValueError('Invalid model')
    if effort is not None and effort not in ('none', 'minimal', 'low', 'medium', 'high', 'xhigh', 'max', 'ultra'):
        raise ValueError('Invalid reasoning effort')
    if source == 'codex':
        result = codex_commands.create_conversation(cwd, prompt, model=model, effort=effort)
        thread = result.get('thread') or {}
        if not thread.get('id'):
            raise ValueError('Codex did not return a new conversation ID')
        return {'pending': False, 'conversation': {
            'id': thread['id'], 'source': source, 'title': thread.get('name') or prompt[:120],
            'cwd': cwd, 'model': model or result.get('model') or '', 'updated_at': int(time.time()),
        }}
    binary = 'agy' if source == 'agy' else 'claude'
    executable = shutil.which(binary) or str(Path.home() / '.local/bin' / binary)
    if not os.path.isfile(executable) or not os.access(executable, os.X_OK):
        raise ValueError(f'{binary} is not installed')
    job = send_message_async(source, '', prompt, conv_title=prompt[:80], cwd=cwd, model=model, effort=effort)
    return {'pending': True, 'job': job}


def _json_records(lines):
    for line in lines:
        try:
            record = json.loads(line)
        except (ValueError, TypeError):
            continue
        if isinstance(record, dict):
            yield record


def _message_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    return "\n".join(
        part["text"] for part in content
        if isinstance(part, dict) and part.get("type") in ("input_text", "output_text", "text")
        and isinstance(part.get("text"), str)
    )


def get_conversation_page(
    source: str, conv_id: str, limit: int = 50, before: int | None = None
) -> dict[str, Any]:
    if not 1 <= limit <= 200 or (before is not None and before < 0):
        raise ValueError("limit must be 1..200; before must be non-negative")
    messages = get_conversation_messages(source, conv_id, limit=None)
    end = len(messages) if before is None else min(before, len(messages))
    start = max(0, end - limit)
    return {"messages": messages[start:end], "total": len(messages),
            "has_more": start > 0, "next_before": start}


def get_conversation_messages(source: str, conv_id: str, limit: int | None = 25) -> list[dict[str, Any]]:
    if source not in ("codex", "agy", "cc") or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", conv_id):
        raise ValueError("invalid conversation source or id")
    messages: list[dict[str, Any]] = []
    if source == "agy":
        t_path = AGY_HOME / "brain" / conv_id / ".system_generated" / "logs" / "transcript.jsonl"
        if not t_path.is_file():
            return messages
        try:
            with open(t_path, "r", encoding="utf-8", errors="ignore") as f:
                for obj in _json_records(f):
                    t = obj.get("type")
                    content = obj.get("content") or ""
                    if not isinstance(content, str) or not content.strip():
                        continue
                    if t == "USER_INPUT":
                        if content.startswith("User changed setting"):
                            continue
                        # Strip <USER_REQUEST> wrapper if present
                        m_text = content
                        if "<USER_REQUEST>" in m_text and "</USER_REQUEST>" in m_text:
                            s_idx = m_text.find("<USER_REQUEST>") + len("<USER_REQUEST>")
                            e_idx = m_text.find("</USER_REQUEST>")
                            m_text = m_text[s_idx:e_idx].strip()
                        messages.append(
                            {
                                "role": "user",
                                "text": m_text,
                                "timestamp": obj.get("created_at") or "",
                            }
                        )
                    elif t == "PLANNER_RESPONSE":
                        messages.append(
                            {
                                "role": "assistant",
                                "text": content,
                                "timestamp": obj.get("created_at") or "",
                                "tokens": int(obj.get("input_tokens") or 0)
                                + int(obj.get("cache_read_tokens") or 0)
                                + int(obj.get("output_tokens") or 0),
                            }
                        )
        except Exception:
            pass
        return messages if limit is None else messages[-limit:]

    if source == "codex":
        rollout_path = ""
        db_path = CODEX_HOME / "state_5.sqlite"
        if db_path.is_file():
            try:
                conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=5)
                cur = conn.cursor()
                cur.execute("SELECT rollout_path FROM threads WHERE id = ?", (conv_id,))
                row = cur.fetchone()
                if row and row[0]:
                    rollout_path = row[0]
                conn.close()
            except Exception:
                pass
        if not rollout_path:
            matches = glob.glob(str(CODEX_HOME / "sessions" / "**" / f"*{conv_id}*.jsonl*"), recursive=True)
            if matches:
                rollout_path = sorted(matches)[0]
        if not rollout_path or not os.path.exists(rollout_path):
            if rollout_path and os.path.exists(rollout_path + ".zst"):
                rollout_path = rollout_path + ".zst"
            else:
                return messages

        try:
            with closing(iter_log_lines([rollout_path])) as lines_iter:
                previous_kind = None
                for obj in _json_records(lines_iter):
                    ts_str = obj.get("timestamp") or ""
                    t = obj.get("type")
                    pl = obj.get("payload") or {}
                    if not isinstance(pl, dict):
                        continue
                    if t == "event_msg" and pl.get("type") in ("task_started", "task_complete", "turn_aborted"):
                        previous_kind = None
                        continue
                    role, msg_txt = None, ""
                    if t == "event_msg" and pl.get("type") in ("user_message", "agent_message"):
                        role = "user" if pl["type"] == "user_message" else "assistant"
                        msg_txt = pl.get("message") or ""
                    elif t == "response_item" and pl.get("type") == "message":
                        role = pl.get("role")
                        if role not in ("user", "assistant") or pl.get("channel") == "analysis":
                            continue
                        msg_txt = _message_text(pl.get("content"))
                    if not role or not isinstance(msg_txt, str) or not msg_txt.strip():
                        continue
                    # Pair neighboring copies, keeping identical prompts from later turns.
                    if (messages and previous_kind and previous_kind != t
                            and messages[-1]["role"] == role and messages[-1]["text"] == msg_txt):
                        old_ts = _parse_iso_to_epoch(messages[-1]["timestamp"])
                        new_ts = _parse_iso_to_epoch(ts_str)
                        if (ts_str == messages[-1]["timestamp"]
                                or (old_ts and new_ts and abs(old_ts - new_ts) <= 1)):
                            previous_kind = None
                            continue
                    messages.append({"role": role, "text": msg_txt, "timestamp": ts_str})
                    previous_kind = t
        except Exception:
            pass
        return messages if limit is None else messages[-limit:]

    if source == "cc":
        matches = glob.glob(str(CLAUDE_HOME / "projects" / "**" / f"{conv_id}.jsonl"), recursive=True)
        if not matches:
            return messages
        try:
            with open(matches[0], "r", encoding="utf-8", errors="ignore") as f:
                for obj in _json_records(f):
                    role = obj.get("type")
                    if role not in ("user", "assistant"):
                        continue
                    msg = obj.get("message") or {}
                    content = msg.get("content") if isinstance(msg, dict) else ""
                    txt = _message_text(content)
                    if txt.strip():
                        messages.append(
                            {
                                "role": role,
                                "text": txt,
                                "timestamp": obj.get("timestamp") or "",
                            }
                        )
        except Exception:
            pass
        return messages if limit is None else messages[-limit:]

    return messages


def _load_json_file(path: Path, default: Any) -> Any:
    if not path.is_file():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _save_json_file(path: Path, data: Any) -> None:
    secure_write(path, json.dumps(data, ensure_ascii=False, indent=2))


def get_schedules() -> list[dict[str, Any]]:
    with _LOCK:
        return _load_json_file(SCHEDULES_FILE, [])


def get_send_history(limit: int = 50) -> list[dict[str, Any]]:
    with _LOCK:
        hist = _load_json_file(HISTORY_FILE, [])
        return hist[:limit]


def _record_history(entry: dict[str, Any]) -> None:
    with _LOCK:
        hist: list[dict[str, Any]] = _load_json_file(HISTORY_FILE, [])
        # Update existing by id if present
        for i, item in enumerate(hist):
            if item.get("id") == entry["id"]:
                hist[i] = entry
                _save_json_file(HISTORY_FILE, hist[:100])
                return
        hist.insert(0, entry)
        _save_json_file(HISTORY_FILE, hist[:100])


def build_cli_command(
    source: str,
    conv_id: str,
    prompt: str,
    model: str | None = None,
    effort: str | None = None,
) -> list[str]:
    model = (model or "").strip() or None
    effort = (effort or "").strip().lower() or None
    full_access = os.environ.get('QUOTACANVAS_FULL_ACCESS') == '1'

    if source == "codex":
        codex_bin = shutil.which("codex") or str(Path.home() / '.local/bin/codex')
        cmd = [
            codex_bin,
            "exec",
            "resume",
            "--skip-git-repo-check",
        ]
        if full_access:
            cmd.append('--dangerously-bypass-approvals-and-sandbox')
        if model:
            cmd.extend(["-m", model])
        if effort:
            cmd.extend(["-c", f'model_reasoning_effort="{effort}"'])
        cmd.extend([conv_id, prompt])
        return cmd

    if source == "agy":
        agy_bin = shutil.which("agy") or str(Path.home() / '.local/bin/agy')
        cmd = [agy_bin]
        if conv_id:
            cmd.extend(['--conversation', conv_id])
        else:
            cmd.extend(['--output-format', 'json'])
        if full_access:
            cmd.append('--dangerously-skip-permissions')
        eff_model = model
        if eff_model and effort in ("low", "medium", "high"):
            for prefix in (
                "gemini-4-argon",
                "gemini-3.8-flash",
                "claude-sonnet-5-5",
                "claude-opus-5-5",
            ):
                if eff_model == prefix or eff_model.startswith(prefix + "-"):
                    eff_model = f"{prefix}-{effort}"
                    break
        if eff_model:
            cmd.extend(["--model", eff_model])
        if effort:
            cmd.extend(["--effort", effort])
        cmd.extend(["-p", prompt])
        return cmd

    if source == "cc":
        claude_bin = shutil.which("claude") or str(Path.home() / '.local/bin/claude')
        cmd = [claude_bin]
        if conv_id:
            cmd.extend(['--resume', conv_id])
        else:
            cmd.extend(['--output-format', 'json'])
        if full_access:
            cmd.append('--dangerously-skip-permissions')
        if model:
            cmd.extend(["--model", model])
        if effort:
            cmd.extend(["--effort", effort])
        cmd.extend(["-p", prompt])
        return cmd

    raise ValueError(f"Unsupported source: {source}")


def validate_native_command(source, prompt):
    """Validate only commands that the non-interactive native clients can handle."""
    parts = prompt.strip().split(None, 1)
    command, argument = (parts[0] if parts else ''), (parts[1] if len(parts) > 1 else '')
    allowed = {'agy': {'/goal', '/plan', '/grill-me', '/usage', '/context'}, 'cc': {'/goal'}}
    if command not in allowed.get(source, set()):
        raise ValueError('This slash command is not supported by this dashboard')
    argument = argument.strip()
    if source == 'agy' and command == '/goal' and (not argument or argument in ('pause', 'resume', 'clear')):
        raise ValueError('AGY supports /goal <objective>. To cancel, send a normal message asking it to stop the current goal.')
    if command in ('/plan', '/grill-me') and not argument:
        raise ValueError('Add a task after this command')
    if command in ('/usage', '/context') and argument:
        raise ValueError('This command does not accept arguments')
    if source == 'cc' and command == '/goal' and argument in ('pause', 'resume'):
        raise ValueError('Claude supports /goal, /goal <objective> and /goal clear; pause/resume are Codex controls')
    if not (shutil.which('agy' if source == 'agy' else 'claude') or
            os.access(Path.home() / '.local/bin' / ('agy' if source == 'agy' else 'claude'), os.X_OK)):
        raise ValueError('Agent CLI not installed; install and sign in first')
    return prompt.strip()


def _send_codex_via_app_server(
    conv_id: str,
    prompt: str,
    cwd: str | None = None,
    model: str | None = None,
    effort: str | None = None,
    entry: dict[str, Any] | None = None,
) -> tuple[bool, str]:
    """
    Send a message to a Codex conversation via the shared local codex app-server
    control socket (~/.codex/app-server-control/app-server-control.sock).
    Avoids 'thread already has an active writer (code -32600)' when the thread
    is already open in Codex Desktop / VSCode / local app-server daemon.
    Returns (success, output_text).
    """
    import base64
    import socket
    import struct

    sock_path = CODEX_HOME / "app-server-control" / "app-server-control.sock"
    if not sock_path.exists():
        return False, "app-server-control.sock not found"

    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.settimeout(30)
    try:
        s.connect(str(sock_path))
        key = base64.b64encode(os.urandom(16)).decode()
        hs = (
            "GET / HTTP/1.1\r\n"
            "Host: localhost\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\n"
            "Sec-WebSocket-Version: 13\r\n\r\n"
        )
        s.sendall(hs.encode("utf-8"))
        resp = s.recv(4096).decode(errors="ignore")
        if "101" not in resp:
            s.close()
            return False, f"WebSocket handshake failed: {resp[:120]}"

        def ws_send(obj: dict[str, Any]) -> None:
            data = json.dumps(obj, ensure_ascii=False).encode("utf-8")
            mask = os.urandom(4)
            header = bytearray([0x81])
            n = len(data)
            if n < 126:
                header.append(0x80 | n)
            elif n < 65536:
                header.append(0x80 | 126)
                header.extend(struct.pack("!H", n))
            else:
                header.append(0x80 | 127)
                header.extend(struct.pack("!Q", n))
            header.extend(mask)
            masked = bytes(b ^ mask[i % 4] for i, b in enumerate(data))
            s.sendall(bytes(header) + masked)

        def ws_recv() -> dict[str, Any] | None:
            while True:
                hdr = s.recv(2)
                if len(hdr) < 2:
                    return None
                b1, b2 = hdr[0], hdr[1]
                opcode = b1 & 0x0F
                length = b2 & 0x7F
                if length == 126:
                    ext = b""
                    while len(ext) < 2:
                        chunk = s.recv(2 - len(ext))
                        if not chunk:
                            return None
                        ext += chunk
                    length = struct.unpack("!H", ext)[0]
                elif length == 127:
                    ext = b""
                    while len(ext) < 8:
                        chunk = s.recv(8 - len(ext))
                        if not chunk:
                            return None
                        ext += chunk
                    length = struct.unpack("!Q", ext)[0]
                buf = b""
                while len(buf) < length:
                    chunk = s.recv(length - len(buf))
                    if not chunk:
                        return None
                    buf += chunk
                if opcode == 0x8:  # close
                    return None
                if opcode == 0x9:  # ping -> pong
                    mask = os.urandom(4)
                    pong = bytearray([0x8A, 0x80 | len(buf)]) + mask + bytes(b ^ mask[i % 4] for i, b in enumerate(buf))
                    s.sendall(bytes(pong))
                    continue
                if opcode in (0x1, 0x2):
                    return json.loads(buf.decode("utf-8", errors="replace"))

        ws_send({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"clientInfo": {"name": "ai-dashboard", "version": "1.0"}}})
        while True:
            m = ws_recv()
            if m is None:
                return False, "EOF waiting for initialize"
            if m.get("id") == 1:
                break
        ws_send({"jsonrpc": "2.0", "method": "initialized"})

        # Resume / rejoin thread in app-server
        resume_params: dict[str, Any] = {"threadId": conv_id}
        if os.environ.get('QUOTACANVAS_FULL_ACCESS') == '1':
            resume_params['approvalPolicy'] = 'never'
        if model:
            resume_params["model"] = model
        ws_send({"jsonrpc": "2.0", "id": 2, "method": "thread/resume", "params": resume_params})
        while True:
            m = ws_recv()
            if m is None:
                return False, "EOF waiting for thread/resume"
            if m.get("id") == 2:
                break

        # Start turn on thread
        turn_params: dict[str, Any] = {
            "threadId": conv_id,
            "input": [{"type": "text", "text": prompt, "text_elements": []}],
        }
        if os.environ.get('QUOTACANVAS_FULL_ACCESS') == '1':
            turn_params.update(approvalPolicy='never', sandboxPolicy={'type': 'dangerFullAccess'})
        if cwd and os.path.isdir(cwd):
            turn_params["cwd"] = cwd
        if model:
            turn_params["model"] = model
        if effort:
            turn_params["effort"] = effort

        ws_send({"jsonrpc": "2.0", "id": 3, "method": "turn/start", "params": turn_params})
        turn_id = None
        while True:
            m = ws_recv()
            if m is None:
                return False, "EOF waiting for turn/start"
            if m.get("id") == 3:
                if "error" in m:
                    # If a turn is already actively running on this thread, queue the message instead
                    q_id = str(uuid.uuid4())
                    ws_send({
                        "jsonrpc": "2.0",
                        "id": 4,
                        "method": "thread/queue/add",
                        "params": {
                            "threadId": conv_id,
                            "clientUserMessageId": q_id,
                            "input": [{"type": "text", "text": prompt, "text_elements": []}],
                        },
                    })
                    while True:
                        qm = ws_recv()
                        if qm is None or qm.get("id") == 4:
                            if qm and "result" in qm:
                                return True, f"(该对话当前正在运行中，已通过 app-server 将消息加入队列: {prompt[:40]})"
                            return False, f"turn/start error: {m['error']}"
                turn_id = ((m.get("result") or {}).get("turn") or {}).get("id")
                break

        if entry is not None:
            entry["output"] = f"已通过 app-server 启动对话轮次 (turn={turn_id or 'active'})，正在生成回复..."
            _record_history(entry)

        # Wait up to 600s for turn/completed while collecting agentMessage deltas
        s.settimeout(600)
        deltas: list[str] = []
        deadline = time.time() + 600
        while time.time() < deadline:
            m = ws_recv()
            if m is None:
                break
            method = m.get("method")
            params = m.get("params") or {}
            if method == "item/agentMessage/delta" and params.get("threadId") == conv_id:
                delta = params.get("delta") or ""
                if delta:
                    deltas.append(delta)
            elif method == "turn/completed" and params.get("threadId") == conv_id:
                turn_obj = params.get("turn") or {}
                st = (turn_obj.get("status") or "")
                err = turn_obj.get("error")
                txt = "".join(deltas).strip()
                if err:
                    return False, f"{txt}\n[Turn Error]: {err}".strip()
                return True, txt or f"(app-server 执行完成，turn={turn_id}，status={st})"
        txt = "".join(deltas).strip()
        return True, txt or f"(已投递至 app-server 后台继续执行，turn={turn_id})"
    except Exception as e:
        return False, f"app-server RPC error: {e}"
    finally:
        try:
            s.close()
        except Exception:
            pass


def send_message_async(
    source: str,
    conv_id: str,
    prompt: str,
    conv_title: str = "",
    cwd: str | None = None,
    model: str | None = None,
    effort: str | None = None,
    schedule_id: str | None = None,
    trigger_reason: str = "manual",
) -> dict[str, Any]:
    send_id = str(uuid.uuid4())[:12]
    now_ts = int(time.time())
    cmd = build_cli_command(source, conv_id, prompt, model=model, effort=effort)
    work_dir = cwd if (cwd and os.path.isdir(cwd)) else str(BASE_DIR)

    entry: dict[str, Any] = {
        "id": send_id,
        "source": source,
        "conv_id": conv_id,
        "conv_title": conv_title or conv_id[:12],
        "prompt": prompt,
        "model": model or "",
        "effort": effort or "",
        "cwd": work_dir,
        "command": " ".join(cmd[:-1]) + f' "{prompt[:30]}"',
        "schedule_id": schedule_id,
        "trigger_reason": trigger_reason,
        "status": "running",
        "started_at": now_ts,
        "finished_at": None,
        "exit_code": None,
        "output": "正在后台执行发送任务...",
    }
    _record_history(entry)

    def _worker() -> None:
        try:
            if source == "codex" and (CODEX_HOME / "app-server-control" / "app-server-control.sock").exists():
                ok, out_msg = _send_codex_via_app_server(
                    conv_id=conv_id,
                    prompt=prompt,
                    cwd=work_dir,
                    model=model,
                    effort=effort,
                    entry=entry,
                )
                if ok:
                    entry["status"] = "completed"
                    entry["exit_code"] = 0
                    entry["finished_at"] = int(time.time())
                    entry["output"] = out_msg[-2000:]
                    _record_history(entry)
                    return

            proc = subprocess.run(
                cmd,
                cwd=work_dir,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding='utf-8',
                errors="replace",
                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0),
                timeout=None if source in ('agy', 'cc') and prompt.strip().startswith('/goal ') else 600,
            )
            out_txt = (proc.stdout or "").strip()
            if not conv_id:
                try:
                    created = json.loads(out_txt)
                    entry['conv_id'] = next((created[key] for key in ('session_id', 'conversation_id', 'sessionId', 'conversationId') if created.get(key)), '')
                except (ValueError, TypeError):
                    pass
            # Strip spinner control sequences if any
            out_lines = [
                ln.split("\r")[-1]
                for ln in out_txt.splitlines()
                if ln.strip()
            ]
            clean_out = "\n".join(out_lines)[-2000:]
            entry["status"] = "completed" if proc.returncode == 0 else "failed"
            entry["exit_code"] = proc.returncode
            entry["finished_at"] = int(time.time())
            entry["output"] = clean_out or "(执行完成，无标准输出)"
        except subprocess.TimeoutExpired:
            entry["status"] = "timeout"
            entry["exit_code"] = -1
            entry["finished_at"] = int(time.time())
            entry["output"] = "执行超时 (>600s)"
        except Exception as e:
            entry["status"] = "failed"
            entry["exit_code"] = -1
            entry["finished_at"] = int(time.time())
            entry["output"] = f"执行异常: {e}"
        _record_history(entry)

    t = threading.Thread(target=_worker, daemon=True)
    t.start()
    return entry


def compute_next_run_at(sched: dict[str, Any], now_ts: int | None = None) -> int | None:
    if now_ts is None:
        now_ts = int(time.time())
    if not sched.get("enabled", True):
        return None
    stype = sched.get("schedule_type") or "once"
    if stype == "once":
        run_at_str = sched.get("run_at") or ""
        if isinstance(run_at_str, (int, float)):
            return int(run_at_str)
        try:
            dt = datetime.datetime.fromisoformat(str(run_at_str))
            return int(dt.timestamp())
        except Exception:
            return None
    elif stype == "interval":
        mins = max(1, int(sched.get("interval_minutes") or 60))
        last_run = int(sched.get("last_run_at") or sched.get("created_at") or now_ts)
        return last_run + mins * 60
    elif stype == "daily":
        hm = str(sched.get("daily_time") or "09:00").strip()
        try:
            hh, mm = map(int, hm.split(":")[:2])
            now_dt = datetime.datetime.fromtimestamp(now_ts)
            target_dt = now_dt.replace(hour=hh, minute=mm, second=0, microsecond=0)
            if int(target_dt.timestamp()) <= max(now_ts, int(sched.get("last_run_at") or 0)):
                target_dt += datetime.timedelta(days=1)
            return int(target_dt.timestamp())
        except Exception:
            return None
    elif stype == "on_quota_reset":
        # Will be dynamically triggered when quota reset time is reached
        return sched.get("target_reset_at")
    return None


def detect_exhausted_reset_at(
    source: str,
    model: str | None,
    quotas: dict[str, Any] | None,
    now_ts: int | None = None,
) -> tuple[str, int | None, str]:
    """
    Inspect live/cached quotas for `source` (and optional `model`) to determine if
    quota is exhausted and when it resets.
    Returns (state, reset_ts_or_none, status_text) where state is 'exhausted' or 'monitoring'.
    """
    if now_ts is None:
        now_ts = int(time.time())
    if not quotas:
        return ("monitoring", None, "循环监控额度中（等待额度数据）")

    m_low = (model or "").lower()

    if source == "codex":
        qc = quotas.get("codex") or {}
        prim = qc.get("primary") or {}
        sec = qc.get("secondary") or {}
        limit_reached = bool(qc.get("limit_reached"))
        p_used = float(prim.get("used_percent") or 0.0)
        s_used = float(sec.get("used_percent") or 0.0)
        p_reset = int(prim.get("resets_at") or 0)
        s_reset = int(sec.get("resets_at") or 0)

        if s_used >= 99.0 and s_reset > now_ts:
            return ("exhausted", s_reset + 5, f"周度额度已耗尽 ({s_used:.1f}%) · 等待重置发送")
        if (limit_reached or p_used >= 95.0) and p_reset > now_ts:
            return ("exhausted", p_reset + 5, f"5h额度已达上限 ({p_used:.1f}%) · 等待重置发送")
        return ("monitoring", None, f"循环监控中（当前 5h 已用 {p_used:.1f}% · 耗尽后自动锁定重置时间）")

    if source == "agy":
        qa = quotas.get("agy") or {}
        live = qa.get("live") or {}
        groups = live.get("groups") or qa.get("groups") or []
        if groups:
            matched_buckets = []
            for g in groups:
                gname = (g.get("name") or "").lower()
                if m_low:
                    if "argon" in m_low and "argon" not in gname:
                        continue
                    if ("claude" in m_low or "gpt" in m_low) and "claude" not in gname and "gpt" not in gname:
                        continue
                    if "flash" in m_low and "argon" in gname:
                        continue
                for b in g.get("buckets") or []:
                    matched_buckets.append(b)
            if not matched_buckets:
                matched_buckets = [b for g in groups for b in (g.get("buckets") or [])]

            for b in matched_buckets:
                if b.get("window") == "weekly" and float(b.get("used_percent") or 0) >= 99.0:
                    r_at = int(b.get("resets_at") or 0)
                    if r_at > now_ts:
                        return ("exhausted", r_at + 5, f"{b.get('name','周度')} 已耗尽 ({b.get('used_percent')}%) · 等待重置发送")
            for b in matched_buckets:
                if float(b.get("used_percent") or 0) >= 95.0:
                    r_at = int(b.get("resets_at") or 0)
                    if r_at > now_ts:
                        return ("exhausted", r_at + 5, f"{b.get('name','5h')} 已达上限 ({b.get('used_percent')}%) · 等待重置发送")
            max_used = max((float(b.get("used_percent") or 0.0) for b in matched_buckets), default=0.0)
            return ("monitoring", None, f"循环监控中（当前已用 {max_used:.1f}% · 耗尽后自动锁定重置时间）")

        for mb in qa.get("models") or []:
            if mb.get("status") == "exhausted" and int(mb.get("resets_at") or 0) > now_ts:
                return ("exhausted", int(mb["resets_at"]) + 5, "额度冷却中 · 等待重置发送")
        return ("monitoring", None, "循环监控中（耗尽后自动锁定重置时间）")

    if source == "cc":
        qcc = quotas.get("cc") or {}
        for b in qcc.get("buckets") or []:
            if float(b.get("used_percent") or 0) >= 95.0 and int(b.get("resets_at") or 0) > now_ts:
                return ("exhausted", int(b["resets_at"]) + 5, f"{b.get('name','Claude')} 已耗尽 · 等待重置发送")
        return ("monitoring", None, "循环监控中（耗尽后自动锁定重置时间）")

    return ("monitoring", None, "循环监控中")


def upsert_schedule(payload: dict[str, Any], quotas: dict[str, Any] | None = None) -> dict[str, Any]:
    now_ts = int(time.time())
    with _LOCK:
        schedules: list[dict[str, Any]] = _load_json_file(SCHEDULES_FILE, [])
        sid = payload.get("id") or str(uuid.uuid4())[:10]
        existing = next((s for s in schedules if s.get("id") == sid), None)

        stype = payload.get("schedule_type") or (existing or {}).get("schedule_type") or "once"
        source = payload.get("source") or (existing or {}).get("source") or "codex"
        model_val = payload.get("model") if "model" in payload else (existing or {}).get("model", "")
        target_reset_at = None
        quota_status = (existing or {}).get("quota_status") or ""

        if stype == "on_quota_reset":
            state, r_at, q_txt = detect_exhausted_reset_at(source, model_val, quotas, now_ts)
            quota_status = q_txt
            if state == "exhausted" and r_at and r_at > now_ts:
                target_reset_at = r_at
            else:
                old_r = (existing or {}).get("target_reset_at")
                if old_r and int(old_r) > now_ts and state == "exhausted":
                    target_reset_at = int(old_r)

        sched: dict[str, Any] = {
            "id": sid,
            "source": source,
            "conv_id": payload.get("conv_id") or (existing or {}).get("conv_id") or "",
            "conv_title": payload.get("conv_title") or (existing or {}).get("conv_title") or "",
            "cwd": payload.get("cwd") or (existing or {}).get("cwd") or str(BASE_DIR),
            "model": model_val,
            "effort": payload.get("effort") if "effort" in payload else (existing or {}).get("effort", ""),
            "prompt": payload.get("prompt") or (existing or {}).get("prompt") or "请继续",
            "schedule_type": stype,  # once | daily | interval | on_quota_reset
            "run_at": payload.get("run_at") if "run_at" in payload else (existing or {}).get("run_at"),
            "daily_time": payload.get("daily_time") if "daily_time" in payload else (existing or {}).get("daily_time", "09:00"),
            "interval_minutes": int(payload.get("interval_minutes") or (existing or {}).get("interval_minutes") or 60),
            "target_reset_at": target_reset_at,
            "quota_status": quota_status,
            "last_triggered_reset_at": (existing or {}).get("last_triggered_reset_at"),
            "enabled": bool(payload["enabled"]) if "enabled" in payload else bool((existing or {}).get("enabled", True)),
            "created_at": (existing or {}).get("created_at") or now_ts,
            "last_run_at": (existing or {}).get("last_run_at"),
            "run_count": int((existing or {}).get("run_count") or 0),
        }
        sched["next_run_at"] = compute_next_run_at(sched, now_ts)

        if existing:
            for i, s in enumerate(schedules):
                if s.get("id") == sid:
                    schedules[i] = sched
                    break
        else:
            schedules.insert(0, sched)
        _save_json_file(SCHEDULES_FILE, schedules)
        return sched


def delete_schedule(schedule_id: str) -> bool:
    with _LOCK:
        schedules: list[dict[str, Any]] = _load_json_file(SCHEDULES_FILE, [])
        new_list = [s for s in schedules if s.get("id") != schedule_id]
        if len(new_list) == len(schedules):
            return False
        _save_json_file(SCHEDULES_FILE, new_list)
        return True


def check_and_run_schedules(quotas: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    now_ts = int(time.time())
    triggered: list[dict[str, Any]] = []
    with _LOCK:
        schedules: list[dict[str, Any]] = _load_json_file(SCHEDULES_FILE, [])
        changed = False
        for sched in schedules:
            if not sched.get("enabled", True):
                continue
            stype = sched.get("schedule_type") or "once"
            next_run = sched.get("next_run_at")

            if stype == "on_quota_reset":
                if next_run and now_ts >= int(next_run):
                    sched["last_run_at"] = now_ts
                    sched["last_triggered_reset_at"] = int(next_run)
                    sched["run_count"] = int(sched.get("run_count") or 0) + 1
                    # Keep enabled=True! Recurring loop continues monitoring for next exhaustion.
                    sched["target_reset_at"] = None
                    sched["next_run_at"] = None
                    sched["quota_status"] = "已触发重置发送 · 继续循环监控下一轮额度"
                    changed = True
                    triggered.append(dict(sched))
                    continue

                state, r_at, q_txt = detect_exhausted_reset_at(
                    sched.get("source", "codex"),
                    sched.get("model"),
                    quotas,
                    now_ts,
                )
                if sched.get("quota_status") != q_txt:
                    sched["quota_status"] = q_txt
                    changed = True
                if state == "exhausted" and r_at and r_at > now_ts:
                    last_trig = int(sched.get("last_triggered_reset_at") or 0)
                    if abs(r_at - last_trig) > 120 and sched.get("next_run_at") != r_at:
                        sched["target_reset_at"] = r_at
                        sched["next_run_at"] = r_at
                        changed = True
                continue

            if next_run and now_ts >= int(next_run):
                sched["last_run_at"] = now_ts
                sched["run_count"] = int(sched.get("run_count") or 0) + 1
                if stype == "once":
                    sched["enabled"] = False
                    sched["next_run_at"] = None
                    sched["target_reset_at"] = None
                else:
                    sched["next_run_at"] = compute_next_run_at(sched, now_ts)
                changed = True
                triggered.append(dict(sched))

        if changed:
            _save_json_file(SCHEDULES_FILE, schedules)

    results = []
    for sched in triggered:
        res = send_message_async(
            source=sched["source"],
            conv_id=sched["conv_id"],
            prompt=sched["prompt"],
            conv_title=sched.get("conv_title") or "",
            cwd=sched.get("cwd"),
            model=sched.get("model") or None,
            effort=sched.get("effort") or None,
            schedule_id=sched["id"],
            trigger_reason=f"schedule:{sched.get('schedule_type')}",
        )
        results.append(res)
    return results
