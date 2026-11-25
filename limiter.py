"""Local subscription usage guard for Claude Code."""

import argparse
from contextlib import closing, contextmanager
from datetime import datetime
import json
import math
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import time


CLAUDE_WINDOWS = ("five_hour", "seven_day")
HOOKS = ("UserPromptSubmit", "PreToolUse", "PostToolBatch", "PreCompact")
DEFAULT_STORE = Path(__file__).resolve().parent / ".usage-limiter"
DEFAULT_CUTOFF = 90
MENU_TIMEOUT = 300


def percentage(value):
    if isinstance(value, bool):
        raise ValueError("Usage must be a percentage.")
    number = float(value)
    if not math.isfinite(number) or number < 0:
        raise ValueError("Usage must be a finite, non-negative percentage.")
    return number


def cutoff_value(value):
    cutoff = percentage(value)
    if not 0 < cutoff <= 100:
        raise ValueError("Choose a cutoff above 0 and at most 100.")
    return cutoff


@contextmanager
def open_database(root):
    root.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(root / "usage.db", timeout=3)) as db:
        db.execute(
            "CREATE TABLE IF NOT EXISTS config (id INTEGER PRIMARY KEY, cutoff REAL, windows TEXT,"
            " max_age INTEGER, enabled INTEGER NOT NULL DEFAULT 1)"
        )
        if "enabled" not in {column[1] for column in db.execute("PRAGMA table_info(config)")}:
            db.execute("BEGIN IMMEDIATE")
            with db:
                if "enabled" not in {column[1] for column in db.execute("PRAGMA table_info(config)")}:
                    db.execute("ALTER TABLE config ADD COLUMN enabled INTEGER NOT NULL DEFAULT 1")
        if db.execute("SELECT 1 FROM config WHERE id = 1").fetchone() is None:
            with db:
                db.execute(
                    "INSERT OR IGNORE INTO config (id, cutoff, windows, max_age) VALUES (1, ?, ?, 900)",
                    (DEFAULT_CUTOFF, json.dumps(CLAUDE_WINDOWS)),
                )
        db.execute(
            "CREATE TABLE IF NOT EXISTS readings (window TEXT, resets INTEGER, used REAL, seen INTEGER,"
            " PRIMARY KEY (window, resets))"
        )
        db.execute(
            "CREATE TABLE IF NOT EXISTS limiter_menu"
            " (session_id TEXT PRIMARY KEY, step INTEGER, expires INTEGER)"
        )
        yield db


def set_cutoff(db, value):
    cutoff = cutoff_value(value)
    with db:
        if db.execute("UPDATE config SET cutoff = ? WHERE id = 1", (cutoff,)).rowcount == 0:
            raise ValueError("Run configure before changing the cutoff.")


def reset_time(value):
    if value.isdecimal():
        return int(value)
    date = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if date.tzinfo is None:
        raise ValueError("Include a timezone offset or Z in the reset time.")
    return int(date.timestamp())


def shell_path(path):
    value = path.as_posix()
    if "'" in value:
        raise ValueError("Use paths without apostrophes for Claude's shell commands.")
    return "'" + value + "'"


def write_claude_settings(root):
    # On Windows a bare executable works in both Git Bash and PowerShell.
    python = "python" if os.name == "nt" else shell_path(Path(sys.executable))
    command = f"{python} -B {shell_path(Path(__file__).resolve())} --store {shell_path(root)}"
    settings = {
        "statusLine": {"type": "command", "command": command + " statusline"},
        "hooks": {
            event: [{"hooks": [{"type": "command", "command": command + " hook", "timeout": 10}]}]
            for event in HOOKS
        },
    }
    target = root / "claude-settings.json"
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=root, delete=False) as file:
        temp = Path(file.name)
        json.dump(settings, file, indent=2)
        file.write("\n")
    try:
        temp.replace(target)
    finally:
        temp.unlink(missing_ok=True)
    return target


def configure(db, root, args):
    if args.max_age < 1:
        raise ValueError("Choose a positive maximum age.")
    target = write_claude_settings(root)
    with db:
        db.execute(
            "UPDATE config SET cutoff = ?, windows = ?, max_age = ? WHERE id = 1",
            (args.percent, json.dumps(list(dict.fromkeys(args.windows))), args.max_age * 60),
        )
    print(target)


def save_readings(db, readings, *, manual=False):
    now = int(time.time())
    with db:
        db.execute("DELETE FROM readings WHERE resets <= ?", (now,))
        for window, used, resets in readings:
            if resets <= now:
                continue
            db.execute(
                """
                INSERT INTO readings VALUES (?, ?, ?, ?)
                ON CONFLICT(window, resets) DO UPDATE SET
                    seen = CASE WHEN ? OR excluded.used > readings.used
                                THEN MAX(readings.seen, excluded.seen) ELSE readings.seen END,
                    used = MAX(readings.used, excluded.used)
                """,
                (window, resets, used, now, manual),
            )


def usage_state(db):
    cutoff, windows, max_age, enabled = db.execute(
        "SELECT cutoff, windows, max_age, enabled FROM config WHERE id = 1"
    ).fetchone()
    now = int(time.time())
    readings = {}
    for window in json.loads(windows):
        readings[window] = db.execute(
            "SELECT MAX(used), MAX(seen) FROM readings WHERE window = ? AND resets > ?",
            (window, now),
        ).fetchone()
    return cutoff, readings, now - max_age, bool(enabled)


def cutoff_reason(cutoff, readings):
    for window, (used, _) in readings.items():
        if used is not None and used >= cutoff:
            return f"{window} is at {used:g}% (coding cutoff {cutoff:g}%)."


def evaluate(db):
    return evaluate_state(*usage_state(db))


def evaluate_state(cutoff, readings, oldest, enabled):
    if not enabled:
        return None
    reason = cutoff_reason(cutoff, readings)
    if reason:
        return reason
    missing = [window for window, (_, seen) in readings.items() if seen is None or seen <= oldest]
    if missing:
        return f"Record current subscription usage for {', '.join(missing)}."
    return None


def active_cutoff_reason(db):
    cutoff, readings, _, enabled = usage_state(db)
    return cutoff_reason(cutoff, readings) if enabled else None


def monitor(child, db, initially_blocked=None, *, label="Claude Code session"):
    already_blocked = bool(active_cutoff_reason(db)) if initially_blocked is None else initially_blocked
    while True:
        try:
            return child.wait(timeout=0.2)
        except subprocess.TimeoutExpired:
            pass
        except KeyboardInterrupt:
            # Claude shares the console and handles Ctrl+C for its current turn.
            continue
        try:
            reason = active_cutoff_reason(db)
            if already_blocked:
                already_blocked = bool(reason)
                continue
        except (sqlite3.Error, ValueError, TypeError) as error:
            reason = f"Could not verify usage ({error})."
        if reason:
            print(f"\nCoding limiter: {reason} Stopping the {label}.", file=sys.stderr)
            child.terminate_tree()
            child.wait()
            return 2


def launch(db, root, arguments):
    if os.name != "nt":
        raise ValueError("The supervised launcher requires Windows.")
    from limiter_windows import start_job

    settings = root / "claude-settings.json"
    if not settings.is_file():
        settings = write_claude_settings(root)
    if arguments[:1] == ["--"]:
        arguments = arguments[1:]
    integration = Path(__file__).resolve().with_name("claude-integration")
    initially_blocked = bool(active_cutoff_reason(db))
    with start_job(["claude", "--settings", str(settings), "--add-dir", str(integration), *arguments]) as child:
        return monitor(child, db, initially_blocked)


def open_window(root):
    if os.name != "nt":
        raise ValueError("The settings window requires Windows.")
    script = Path(__file__).resolve()
    powershell = Path(os.environ["SystemRoot"]) / "System32/WindowsPowerShell/v1.0/powershell.exe"
    return subprocess.Popen(
        [str(powershell), "-NoProfile", "-STA", "-ExecutionPolicy", "RemoteSigned", "-File",
         str(script.with_name("limiter_window.ps1")), sys.executable, str(script), str(root)],
        creationflags=subprocess.CREATE_NO_WINDOW,
    )


def claude_readings(payload):
    if not isinstance(payload, dict):
        raise ValueError("Expected a Claude status-line JSON object.")
    limits = payload.get("rate_limits")
    if not isinstance(limits, dict):
        return
    for window in CLAUDE_WINDOWS:
        entry = limits.get(window)
        if not isinstance(entry, dict) or type(entry.get("resets_at")) is not int:
            continue
        used = entry.get("used_percentage")
        if type(used) in (int, float) and math.isfinite(used) and used >= 0:
            yield window, used, entry["resets_at"]


def block(message, event=None):
    message = f"Coding limiter: {message}"
    if event in ("PreToolUse", "PostToolBatch"):
        response = {"continue": False, "stopReason": message}
        if event == "PreToolUse":
            response["hookSpecificOutput"] = {
                "hookEventName": event,
                "permissionDecision": "deny",
                "permissionDecisionReason": message,
            }
        print(json.dumps(response))
        return 0
    print(message, file=sys.stderr)
    return 2


def handle_settings_prompt(db, payload):
    prompt = payload.get("prompt", "").strip().lower()
    parts = prompt.split(maxsplit=1)
    session_id = payload.get("session_id")
    if not session_id or not parts or parts[0] != "/limiter":
        return None
    choice = parts[1] if len(parts) == 2 else ""
    now = int(time.time())
    if not choice:
        cutoff, enabled = db.execute("SELECT cutoff, enabled FROM config WHERE id = 1").fetchone()
        with db:
            db.execute("DELETE FROM limiter_menu WHERE expires <= ?", (now,))
            db.execute("INSERT OR REPLACE INTO limiter_menu VALUES (?, 1, ?)", (session_id, now + MENU_TIMEOUT))
        current = f"enabled at {cutoff:g}%" if enabled else "disabled"
        return f"Limiter is {current}. Step 1 of 2: enter /limiter enable or /limiter disable."
    row = db.execute(
        "SELECT step FROM limiter_menu WHERE session_id = ? AND expires > ?", (session_id, now)
    ).fetchone()
    if row is None:
        return "Enter /limiter to open the settings."
    step = row[0]
    if choice == "cancel":
        with db:
            db.execute("DELETE FROM limiter_menu WHERE session_id = ?", (session_id,))
        return "Limiter settings closed."
    if step == 1 and choice == "enable":
        with db:
            db.execute("UPDATE limiter_menu SET step = 2, expires = ? WHERE session_id = ?",
                       (now + MENU_TIMEOUT, session_id))
        return "Step 2 of 2: enter a cutoff above 0 and up to 100, for example /limiter 90."
    if step == 1 and choice != "disable":
        return "Step 1 of 2: enter /limiter enable or /limiter disable."
    if step == 2:
        try:
            cutoff = cutoff_value(choice.removesuffix("%"))
        except ValueError:
            return "Step 2 of 2: enter a valid cutoff, for example /limiter 90."
    with db:
        if step == 1:
            db.execute("UPDATE config SET enabled = 0 WHERE id = 1")
        else:
            db.execute("UPDATE config SET enabled = 1, cutoff = ? WHERE id = 1", (cutoff,))
        db.execute("DELETE FROM limiter_menu WHERE session_id = ?", (session_id,))
    return "Limiter disabled." if step == 1 else f"Limiter enabled at {cutoff:g}%."


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--store", type=Path, default=os.environ.get("CODING_LIMITER_HOME", DEFAULT_STORE))
    commands = parser.add_subparsers(dest="command", required=True)
    setup = commands.add_parser("configure", help="Set the cutoff and generate Claude settings")
    setup.add_argument("percent", nargs="?", type=cutoff_value, default=DEFAULT_CUTOFF)
    setup.add_argument("--windows", nargs="+", default=CLAUDE_WINDOWS)
    setup.add_argument("--max-age", type=int, default=15, metavar="MINUTES")
    record = commands.add_parser("record", help="Record a subscription usage reading")
    record.add_argument("window")
    record.add_argument("percent", type=percentage)
    record.add_argument("reset", type=reset_time, help="Unix seconds or ISO 8601 with timezone")
    commands.add_parser("check", help="Exit 0 if coding is allowed or 2 if blocked")
    change = commands.add_parser("set-cutoff", help="Change the cutoff for running sessions")
    change.add_argument("percent", type=cutoff_value)
    commands.add_parser("window", help="Open the cutoff and usage settings window")
    commands.add_parser("state", help="Print the current usage and cutoff as JSON")
    launcher = commands.add_parser("launch", help="Start supervised Claude Code on Windows")
    launcher.add_argument("claude_args", nargs=argparse.REMAINDER)
    commands.add_parser("statusline")
    commands.add_parser("hook")
    commands.add_parser("demo", help="Demonstrate the Windows cutoff without making a Claude request")
    return parser.parse_args()


def main():
    args = parse_args()
    event = None
    try:
        if args.command == "demo":
            if os.name != "nt":
                raise ValueError("The offline process demo requires Windows.")
            from limiter_demo import run_demo
            return run_demo()
        if args.command == "hook":
            payload = json.load(sys.stdin)
            event = payload["hook_event_name"]
        root = args.store.resolve()
        with open_database(root) as db:
            if args.command == "configure":
                configure(db, root, args)
                return 0
            if args.command == "record":
                save_readings(db, [(args.window, args.percent, args.reset)], manual=True)
                return 0
            if args.command == "set-cutoff":
                set_cutoff(db, args.percent)
                return 0
            if args.command == "window":
                return open_window(root).wait()
            if args.command == "state":
                cutoff, readings, oldest, enabled = usage_state(db)
                print(json.dumps({
                    "cutoff": cutoff,
                    "enabled": enabled,
                    "reason": evaluate_state(cutoff, readings, oldest, enabled),
                    "windows": [
                        {"name": name, "used": used, "stale": seen is None or seen <= oldest}
                        for name, (used, seen) in readings.items()
                    ],
                }))
                return 0
            if args.command == "launch":
                return launch(db, root, args.claude_args)
            if args.command == "statusline":
                save_readings(db, claude_readings(json.load(sys.stdin)))
                cutoff, readings, oldest, enabled = usage_state(db)
                reason = evaluate_state(cutoff, readings, oldest, enabled)
                print(f"Coding limiter | {reason or ('coding allowed' if enabled else 'disabled')}")
                return 0
            if event == "UserPromptSubmit":
                menu = handle_settings_prompt(db, payload)
                if menu:
                    print(json.dumps({
                        "decision": "block",
                        "reason": menu,
                        "hookSpecificOutput": {
                            "hookEventName": event,
                            "suppressOriginalPrompt": True,
                        },
                    }))
                    return 0
            reason = evaluate(db)
        return block(reason, event) if reason else 0
    except (OSError, sqlite3.Error, ValueError, TypeError, KeyError, OverflowError, RuntimeError) as error:
        return block(f"Could not verify usage ({error}).", event)


if __name__ == "__main__":
    sys.exit(main())
