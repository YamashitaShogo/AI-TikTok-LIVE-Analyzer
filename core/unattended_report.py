"""Aggregation for the unattended observation report.

Reads the battle collection database strictly read-only (through
core.collection_store) and produces one JSON-serialisable report dict.

Honesty rules enforced here (from the spec):
- A known score of 0 and an unknown score are different things; unknown
  scores never enter medians, maxima or series as 0.
- Missing intervals are reported as gaps, never zero-filled.
- A battle first observed after its start is flagged ``partial`` and is
  never described as a complete match result.
- Observation records and unique battles are counted separately: the
  same battle_id observed from two streamers is 2 records, 1 unique
  battle.
- Several streamers are never merged into one person's results; the
  session-level score statistics are labelled as record-based and every
  headline figure carries its denominator in ``definitions``.
- Viewer counts and scores are observed values only; score increases
  are never presented as gift amounts or revenue.
"""
import os
from collections import defaultdict
from pathlib import Path
from statistics import median

try:
    from .collection_store import CollectionStore, STATUS_LABELS, safe_payload
    from .collection_analysis import host_score
    from .observation_sessions import format_jst
except ImportError:  # direct-script import style
    from collection_store import CollectionStore, STATUS_LABELS, safe_payload
    from collection_analysis import host_score
    from observation_sessions import format_jst

SCHEMA_VERSION = "livemetry_unattended_report_v1"
GAP_THRESHOLD_SEC = 60.0
PARTIAL_THRESHOLD_SEC = 15.0
MAX_SERIES_POINTS = 500
BATTLE_PAGE_SIZE = 500

BASE_DIR = Path(os.environ.get("LOCALAPPDATA", os.path.expanduser("~"))) / "AI-TikTok-LIVE-Analyzer"


def battle_db(capture_dir):
    return Path(capture_dir) / "battle_dataset" / "battles.sqlite3"


def available_sources(base=None):
    """Data sources the report can read, kept strictly separate.

    TopWatch child databases are included only when the folder layout
    verifies the mapping: ``top_watch/<streamer_id>/.../capture_fixed``
    means the child observed that streamer with the fixed profile.
    """
    base = Path(base) if base else BASE_DIR
    sources = []
    for key, label, folder in (
            ("capture", "通常観測", base / "capture"),
            ("capture_fixed", "固定観測", base / "capture_fixed")):
        sources.append({"key": key, "label": label, "profile": key,
                        "capture_dir": str(folder), "database": str(battle_db(folder)),
                        "streamer_hint": None})
    top_watch = base / "top_watch"
    if top_watch.is_dir():
        for child in sorted(top_watch.iterdir()):
            if not child.is_dir():
                continue
            # Actual layout written by TopWatch children:
            # top_watch/<streamer_id>/AI-TikTok-LIVE-Analyzer/capture_fixed
            # (the child app's own LOCALAPPDATA-style tree). The flatter
            # layouts are kept as fallbacks for older installs.
            for candidate in (child / "AI-TikTok-LIVE-Analyzer" / "capture_fixed",
                              child / "AI-TikTok-LIVE-Analyzer" / "capture",
                              child / "capture_fixed", child / "capture"):
                if battle_db(candidate).exists():
                    profile = "capture_fixed" if candidate.name == "capture_fixed" else "capture"
                    sources.append({
                        "key": f"topwatch:{child.name}:{profile}",
                        "label": f"TopWatch（{child.name}）",
                        "profile": profile,
                        "capture_dir": str(candidate),
                        "database": str(battle_db(candidate)),
                        "streamer_hint": child.name})
                    break
    return sources


def _downsample(points, cap=MAX_SERIES_POINTS):
    if len(points) <= cap:
        return points, False
    stride = (len(points) + cap - 1) // cap
    sampled = points[::stride]
    if sampled[-1] is not points[-1]:
        sampled.append(points[-1])
    return sampled, True


def _gaps(points, kind):
    """Intervals > GAP_THRESHOLD_SEC between consecutive samples."""
    gaps = []
    stamps = [p["t"] for p in points]
    for before, after in zip(stamps, stamps[1:]):
        if after - before > GAP_THRESHOLD_SEC:
            gaps.append({"kind": kind, "from": before, "to": after,
                         "seconds": round(after - before, 1)})
    return gaps


def _battle_record(db, tables, row, window_start, window_end=None):
    """One battle's record, aggregated from IN-WINDOW samples only.

    Samples outside [window_start, window_end] never enter the series,
    counts, gaps or increases. Battles that span the window are flagged
    (``window_clipped``) so the observed interval is never presented as
    the complete battle. The payload score of a battle whose end was
    not confirmed is NOT a final score: it is exposed separately as
    ``last_known_score`` (reference only).
    """
    payload = safe_payload(row["payload"])
    key = (row["unique_id"], row["battle_id"])
    mode = payload.get("mode") or "unknown"
    start_ms = payload.get("start_time_ms")
    battle_start = None
    try:
        battle_start = float(start_ms) / 1000 if start_ms else None
    except (TypeError, ValueError):
        battle_start = None
    if battle_start is not None and abs(battle_start - row["first_seen"]) > 86400:
        battle_start = None  # implausible payload value; do not trust it
    if battle_start is None:
        partial_state = "unknown"
    elif row["first_seen"] - battle_start > PARTIAL_THRESHOLD_SEC:
        partial_state = "partial"
    else:
        partial_state = "full"

    def _window_clause(column):
        clause, args = "", []
        if window_start is not None:
            clause += f" AND {column}>=?"
            args.append(float(window_start))
        if window_end is not None:
            clause += f" AND {column}<=?"
            args.append(float(window_end))
        return clause, args

    score_points = []
    if "snapshots" in tables:
        clause, args = _window_clause("received_at")
        for snap in db.execute(
                "SELECT received_at, payload FROM snapshots"
                " WHERE unique_id=? AND battle_id=?" + clause +
                " ORDER BY received_at", (*key, *args)):
            value = host_score(safe_payload(snap["payload"]))
            score_points.append({"t": snap["received_at"], "v": value})
    known_points = [p for p in score_points if p["v"] is not None]

    status = row["status"]
    finished_confirmed = status == "finished"
    payload_score = host_score(payload)
    # Only a battle with a confirmed end has a final score. Anything
    # else is the latest known value, kept visibly separate.
    final_score = payload_score if finished_confirmed else None
    last_known_score = payload_score
    if last_known_score is None and known_points:
        last_known_score = known_points[-1]["v"]

    starts_before_window = bool(
        window_start is not None and (
            (battle_start is not None and battle_start < window_start)
            or row["first_seen"] < window_start))
    ends_after_window = bool(
        window_end is not None and row["last_seen"] > window_end)

    viewer_points = []
    if "viewer_samples" in tables:
        clause, args = _window_clause("received_at")
        viewer_points = [{"t": r["received_at"], "v": r["viewer_count"]}
                         for r in db.execute(
                             "SELECT received_at, viewer_count FROM viewer_samples"
                             " WHERE unique_id=? AND battle_id=?" + clause +
                             " ORDER BY received_at", (*key, *args))]
    viewer_values = [p["v"] for p in viewer_points]

    largest = None
    for before, after in zip(known_points, known_points[1:]):
        increase = after["v"] - before["v"]
        if increase > 0 and (largest is None or increase > largest["increase"]):
            largest = {"increase": increase, "from_t": before["t"], "to_t": after["t"]}

    score_series, score_ds = _downsample(score_points)
    viewer_series, viewer_ds = _downsample(viewer_points)
    return {
        "unique_id": row["unique_id"],
        "battle_id": row["battle_id"],
        "nickname": str(payload.get("host_nickname") or row["unique_id"]),
        "mode": mode,
        "status": status,
        "status_label": STATUS_LABELS.get(status, status),
        "finished_confirmed": finished_confirmed,
        "first_seen": row["first_seen"],
        "last_seen": row["last_seen"],
        "first_seen_jst": format_jst(row["first_seen"]),
        "battle_start": battle_start,
        "partial_state": partial_state,
        "starts_before_window": starts_before_window,
        "ends_after_window": ends_after_window,
        "window_clipped": bool(starts_before_window or ends_after_window),
        "score_at_window_end": known_points[-1]["v"] if known_points else None,
        "final_score": final_score,
        "last_known_score": last_known_score,
        "score_known": final_score is not None,
        "score_sample_count": len(known_points),
        "snapshot_count": len(score_points),
        "viewer_sample_count": len(viewer_points),
        "viewer_median": median(viewer_values) if viewer_values else None,
        "viewer_peak": max(viewer_values) if viewer_values else None,
        "score_series": score_series,
        "viewer_series": viewer_series,
        "series_downsampled": bool(score_ds or viewer_ds),
        "gaps": _gaps(known_points, "score") + _gaps(viewer_points, "viewer"),
        "largest_increase": largest,
    }


def build_report(database, scope, session=None, profile="capture", now=None,
                 generation_trigger="manual"):
    """Build one report dict.

    scope: {"kind": "session"|"period"|"streamer"|"all",
            "start": epoch|None, "end": epoch|None,
            "streamers": [unique_id, ...] (optional filter)}
    session: a session dict from core.observation_sessions, required
    for kind="session" (window and targets come from the session).
    """
    import time
    now = time.time() if now is None else float(now)
    store = CollectionStore(database)
    report = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now,
        "generated_jst": format_jst(now),
        "profile": profile,
        "database": str(store.database),
        "scope": dict(scope),
        "generation": {"trigger": generation_trigger,
                       "note": "セッション終了時はJSONレポートを自動生成します。"
                               "画面での集計・PDF出力・AI分析は手動操作です。"},
        "session": None,
        "summary": None,
        "per_streamer": [],
        "battles": [],
        "target_switches": [],
        "comparison": None,
        "evidence_links": [],
        "definitions": {
            "観測時間": "セッション開始から終了（未終了・中断時は最後のheartbeat）までの秒数。配信時間ではない。",
            "記録バトル数": "観測レコード件数（配信者×バトルの行数）。同一バトルを複数配信者から観測すると複数件になる。",
            "ユニークバトル数": "battle_id の distinct 件数。記録バトル数とは別に数える。",
            "正常終了が確認できたバトル数": "記録側ステータスが finished（終了通知あり）のレコード件数。",
            "スコア中央値・最大確認スコア": "終了が確認でき（終了通知あり）、本人スコアが score_known=True で確定したレコードの最終スコアのみが対象。未取得は0として数えない。終了未確認バトルのスコアは最終スコアではなく「最新の確認スコア（参考）」として別に数える。",
            "期間をまたぐバトル": "対象期間の開始前から続いていた／終了が期間の終了後になったバトルは window_clipped として区別する。集計には期間内のサンプルだけを使う。期間をまたいで終了したバトルの最終スコアは、そのバトルの行に参考として保持し、期間の集計（中央値・最大・取得済み件数）には含めない。",
            "視聴者数の中央値": "バトルごとの視聴者数中央値を求め、その中央値。サンプルのないバトルは対象外。",
            "最大確認視聴者数": "記録された視聴者サンプルの最大値。",
            "スコアの記録回数": "本人スコアが確定できたスナップショットの総数。",
            "途中から観測": "バトル開始時刻より15秒を超えて遅く最初の記録が残ったバトル。完全な1試合の成績としては扱わない。",
        },
        "data_notes": [
            "記録のない区間は0で補完していません（gaps に未取得区間を明示）。",
            "スコアの増加をギフト金額や売上としては表示していません。",
            "観測時間と配信時間は別です。配信の開始・終了はこのデータからは断定できません。",
        ],
    }
    if session is not None:
        report["session"] = {
            "session_id": session["session_id"], "mode": session["mode"],
            "profile": session["profile"], "targets": session.get("targets", []),
            "started_at": session["started_at"], "ended_at": session["ended_at"],
            "end_kind": session["end_kind"],
            "started_jst": session.get("started_jst"), "ended_jst": session.get("ended_jst"),
            "monitored_seconds": session["monitored_seconds"],
            "disconnected_seconds": session["disconnected_seconds"],
            "gap_seconds": session["gap_seconds"],
            "last_data_at": session["last_data_at"],
            "report_state": session["report_state"],
        }
        report["target_switches"] = [
            {"at": e["at"], "at_jst": format_jst(e["at"]),
             "target": (e.get("detail") or {}).get("target")}
            for e in session.get("events", []) if e["kind"] == "target_switch"]

    kind = scope.get("kind") or "all"
    start = scope.get("start")
    end = scope.get("end")
    if kind == "session" and session is not None:
        start = session["started_at"]
        end = session["ended_at"] or session["last_heartbeat_at"] or now
    streamers = [str(s).strip().lstrip("@") for s in (scope.get("streamers") or []) if str(s).strip()]
    if kind == "session" and session is not None and not streamers:
        streamers = list(session.get("targets") or [])

    battles = []
    error_count = None
    if session is not None:
        kinds = [e["kind"] for e in session.get("events", [])]
        error_count = sum(1 for k in kinds if k in ("disconnect_start", "error"))
    excluded_in_window = None
    if store.database.exists():
        with store._connect() as db:
            tables = store._tables(db)
            if "battles" in tables:
                where, args = [], []
                if start is not None:
                    where.append("last_seen>=?")
                    args.append(float(start))
                if end is not None:
                    where.append("first_seen<=?")
                    args.append(float(end))
                if streamers:
                    where.append("unique_id IN (%s)" % ",".join("?" * len(streamers)))
                    args.extend(streamers)
                clause = (" WHERE " + " AND ".join(where)) if where else ""
                total = db.execute("SELECT count(*) FROM battles" + clause, args).fetchone()[0]
                offset = 0
                while offset < total:
                    rows = db.execute(
                        "SELECT * FROM battles" + clause +
                        " ORDER BY first_seen, battle_id LIMIT ? OFFSET ?",
                        (*args, BATTLE_PAGE_SIZE, offset)).fetchall()
                    for row in rows:
                        battles.append(_battle_record(db, tables, row, start, end))
                    offset += BATTLE_PAGE_SIZE
                if "excluded_battles" in tables:
                    if start is not None and end is not None:
                        excluded_in_window = db.execute(
                            "SELECT count(*) FROM excluded_battles"
                            " WHERE excluded_at>=? AND excluded_at<=?",
                            (float(start), float(end))).fetchone()[0]
                    else:
                        excluded_in_window = db.execute(
                            "SELECT count(*) FROM excluded_battles").fetchone()[0]

    finished = [b for b in battles if b["finished_confirmed"]]
    # Final scores that belong to this window: confirmed end, known
    # score, and the battle did not end after the window closed.
    known_finals = [b["final_score"] for b in battles
                    if b["score_known"] and not b["ends_after_window"]]
    clipped_finals = [b for b in battles
                      if b["score_known"] and b["ends_after_window"]]
    last_known_only = [b for b in battles
                       if not b["finished_confirmed"] and b["last_known_score"] is not None]
    viewer_medians = [b["viewer_median"] for b in battles if b["viewer_median"] is not None]
    viewer_peaks = [b["viewer_peak"] for b in battles if b["viewer_peak"] is not None]
    if session is not None:
        observed_seconds = session["elapsed_seconds"]
        monitored = session["monitored_seconds"]
        disconnected = session["disconnected_seconds"]
    elif start is not None and end is not None:
        observed_seconds = max(0.0, float(end) - float(start))
        monitored = disconnected = None
    elif battles:
        observed_seconds = max(b["last_seen"] for b in battles) - min(b["first_seen"] for b in battles)
        monitored = disconnected = None
    else:
        observed_seconds = 0.0
        monitored = disconnected = None

    grouped = defaultdict(list)
    for battle in battles:
        grouped[battle["unique_id"]].append(battle)
    per_streamer = []
    for unique_id in sorted(grouped):
        rows = grouped[unique_id]
        scores = [b["final_score"] for b in rows
                  if b["score_known"] and not b["ends_after_window"]]
        vmed = [b["viewer_median"] for b in rows if b["viewer_median"] is not None]
        per_streamer.append({
            "unique_id": unique_id,
            "nickname": rows[0]["nickname"],
            "records": len(rows),
            "finished": sum(1 for b in rows if b["finished_confirmed"]),
            "score_known": len(scores),
            "last_known_records": sum(
                1 for b in rows if not b["finished_confirmed"]
                and b["last_known_score"] is not None),
            "score_median": median(scores) if scores else None,
            "score_max": max(scores) if scores else None,
            "viewer_median": median(vmed) if vmed else None,
            "viewer_peak": max((b["viewer_peak"] for b in rows
                                if b["viewer_peak"] is not None), default=None),
            "partial_records": sum(1 for b in rows if b["partial_state"] == "partial"),
        })

    report["battles"] = battles
    report["per_streamer"] = per_streamer
    report["summary"] = {
        "observed_seconds": observed_seconds,
        "monitored_seconds": monitored,
        "disconnected_seconds": disconnected,
        "streamer_count": len(grouped),
        "record_count": len(battles),
        "unique_battle_count": len({b["battle_id"] for b in battles}),
        "finished_confirmed": len(finished),
        "unfinished": len(battles) - len(finished),
        "score_known_battles": len(known_finals),
        "score_unknown_battles": len(battles) - len(known_finals),
        "clipped_final_score_battles": len(clipped_finals),
        "last_known_score_battles": len(last_known_only),
        "window_clipped_battles": sum(1 for b in battles if b["window_clipped"]),
        "final_score_median": median(known_finals) if known_finals else None,
        "final_score_max": max(known_finals) if known_finals else None,
        "viewer_median": median(viewer_medians) if viewer_medians else None,
        "viewer_peak_max": max(viewer_peaks) if viewer_peaks else None,
        "score_sample_total": sum(b["score_sample_count"] for b in battles),
        "viewer_sample_total": sum(b["viewer_sample_count"] for b in battles),
        "partial_battles": sum(1 for b in battles if b["partial_state"] == "partial"),
        "partial_unknown_battles": sum(1 for b in battles if b["partial_state"] == "unknown"),
        "gap_count": sum(len(b["gaps"]) for b in battles),
        "error_count": error_count,
        "excluded_battles": excluded_in_window,
        "window_start": start,
        "window_end": end,
        "window_start_jst": format_jst(start) if start is not None else "指定なし",
        "window_end_jst": format_jst(end) if end is not None else "指定なし",
    }
    return report


def compare_reports(current, previous):
    """Delta block for the metrics both reports actually have.

    Returns None-filled entries with ``comparable: False`` instead of
    inventing a difference when either side lacks the value.
    """
    metrics = [
        ("record_count", "記録バトル数"),
        ("finished_confirmed", "正常終了が確認できたバトル数"),
        ("final_score_median", "スコア中央値"),
        ("final_score_max", "最大確認スコア"),
        ("viewer_median", "視聴者数の中央値"),
        ("viewer_peak_max", "最大確認視聴者数"),
        ("score_sample_total", "スコアの記録回数"),
        ("viewer_sample_total", "視聴者数の記録回数"),
    ]
    rows = []
    for key, label in metrics:
        cur = (current.get("summary") or {}).get(key)
        prev = (previous.get("summary") or {}).get(key)
        comparable = cur is not None and prev is not None
        rows.append({"key": key, "label": label, "current": cur, "previous": prev,
                     "delta": (cur - prev) if comparable else None,
                     "comparable": comparable})
    return {"previous_generated_jst": previous.get("generated_jst"),
            "previous_scope": previous.get("scope"), "rows": rows}
