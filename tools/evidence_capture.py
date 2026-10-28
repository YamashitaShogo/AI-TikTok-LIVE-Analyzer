"""Inspect and manage Phase D screen-evidence sessions.

Subcommands:
    list                          sessions with sizes and verdicts
    show <session>                metadata + correspondence summary
    verdict <session> <candidate|screen_confirmed> --note "..."
                                  record a HUMAN verdict (the only way a
                                  verdict can leave "unknown")
    purge                         apply retention days + total-size cap

Sessions live under <capture base>/evidence/. By default both the normal
(capture) and fixed-observation (capture_fixed) bases are scanned.
Recording itself happens in the app (core/evidence_capture.py) and only
when the user enabled evidence_capture_enabled in settings.json.

Stdlib only. Nothing here uploads or transmits anything.
"""

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.evidence_capture import (  # noqa: E402
    EvidenceRecorder,
    delete_session,
    jst_iso,
    load_config,
    read_session,
    set_human_verdict,
)

APP_NAME = "AI-TikTok-LIVE-Analyzer"


def default_bases():
    base = Path(os.environ.get("LOCALAPPDATA",
                               os.path.expanduser("~"))) / APP_NAME
    return [base / "capture", base / "capture_fixed"]


def find_sessions(bases):
    found = []
    for base in bases:
        root = Path(base) / "evidence"
        if not root.exists():
            continue
        for child in sorted(root.iterdir()):
            if child.is_dir():
                found.append(child)
    return found


def resolve_session(bases, name):
    for session_dir in find_sessions(bases):
        if session_dir.name == name or str(session_dir) == name:
            return session_dir
    return None


def load_settings_for(base):
    try:
        path = Path(base).parent / "settings.json"
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8-sig"))
            if isinstance(data, dict):
                return data
    except Exception:
        pass
    return {}


def cmd_list(args):
    sessions = find_sessions(args.bases)
    if not sessions:
        print("no evidence sessions found")
        return 0
    for session_dir in sessions:
        info = read_session(session_dir)
        metadata = info["metadata"]
        verdict = metadata.get("verdict", "unknown")
        if info["human_verdict"]:
            verdict = info["human_verdict"].get("verdict", verdict)
        counts = metadata.get("counts", {})
        print(f"{session_dir.name}")
        print(f"  battle={metadata.get('battle_id', '?')} "
              f"started={metadata.get('started_at_jst', '?')} "
              f"frames={counts.get('frames_saved', '?')} "
              f"events={counts.get('events', '?')} "
              f"size={info['size_bytes'] / 1024:.0f} KiB "
              f"verdict={verdict}")
    return 0


def cmd_show(args):
    session_dir = resolve_session(args.bases, args.session)
    if session_dir is None:
        print(f"session not found: {args.session}")
        return 1
    info = read_session(session_dir)
    metadata = info["metadata"]
    print(json.dumps({
        "session": session_dir.name,
        "battle_id": metadata.get("battle_id"),
        "observation_id": metadata.get("observation_id"),
        "context": metadata.get("context"),
        "started_at_jst": metadata.get("started_at_jst"),
        "ended_at_jst": metadata.get("ended_at_jst"),
        "end_reason": metadata.get("end_reason"),
        "counts": metadata.get("counts"),
        "sync": metadata.get("sync"),
        "verdict": metadata.get("verdict", "unknown"),
        "human_verdict": info["human_verdict"],
    }, ensure_ascii=False, indent=2))
    csv_path = session_dir / "correspondence.csv"
    if csv_path.exists():
        print("\ncorrespondence (event -> nearest frames):")
        print(csv_path.read_text(encoding="utf-8"))
    return 0


def cmd_verdict(args):
    session_dir = resolve_session(args.bases, args.session)
    if session_dir is None:
        print(f"session not found: {args.session}")
        return 1
    try:
        record = set_human_verdict(session_dir, args.verdict,
                                    note=args.note or "")
    except (ValueError, FileNotFoundError) as exc:
        print(f"error: {exc}")
        return 1
    print(f"recorded human verdict for {session_dir.name}: "
          f"{record['verdict']} at {record['recorded_at_jst']}")
    print("note: this records the screen observation only; it does not "
          "determine the meaning of any notification event.")
    return 0


def cmd_purge(args):
    removed_total = []
    for base in args.bases:
        config = load_config(load_settings_for(base))
        recorder = EvidenceRecorder(base, config)
        removed = recorder.purge_old_evidence()
        for session_dir in removed:
            removed_total.append(session_dir)
            print(f"purged {session_dir}")
    print(f"purge complete: {len(removed_total)} session(s) removed")
    return 0


def cmd_delete(args):
    session_dir = resolve_session(args.bases, args.session)
    if session_dir is None:
        print(f"session not found: {args.session}")
        return 1
    if delete_session(session_dir):
        print(f"deleted {session_dir.name}")
        return 0
    print(f"failed to delete {session_dir.name}")
    return 1


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Phase D screen-evidence session manager")
    parser.add_argument(
        "--base", action="append", default=None,
        help="capture base dir (repeatable); default: capture and "
             "capture_fixed under %%LOCALAPPDATA%%\\" + APP_NAME)
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("list", help="list sessions")
    show = sub.add_parser("show", help="show one session")
    show.add_argument("session")
    verdict = sub.add_parser("verdict", help="record a human verdict")
    verdict.add_argument("session")
    verdict.add_argument("verdict",
                         choices=["candidate", "screen_confirmed"])
    verdict.add_argument("--note", default="")
    sub.add_parser("purge", help="apply retention + size caps")
    delete = sub.add_parser("delete", help="delete one session")
    delete.add_argument("session")

    args = parser.parse_args(argv)
    args.bases = ([Path(b) for b in args.base]
                  if args.base else default_bases())
    handler = {"list": cmd_list, "show": cmd_show, "verdict": cmd_verdict,
               "purge": cmd_purge, "delete": cmd_delete}[args.command]
    return handler(args)


if __name__ == "__main__":
    raise SystemExit(main())
