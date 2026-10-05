"""
Livemetry Pulse internal TikTok Viewer / Collector.

This module is intentionally run in a separate Python process.
pywebview owns its GUI loop, while the main application uses CustomTkinter.
Keeping the loops in separate processes makes the app much more stable.
"""

import os
import sys
import json
import time
import base64
import threading
import re
from collections import deque
from datetime import datetime
from pathlib import Path

import webview

try:
    from core.battle_monitor import BattleMonitor
except ModuleNotFoundError:
    from battle_monitor import BattleMonitor


# Windowsでは子プロセスの標準出力がcp932になる場合があるため、
# TikTokコメント内の絵文字でCollectorスレッドが落ちないようUTF-8へ固定する。
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

WINDOW_TITLE = "Livemetry Pulse - Canvas Collector"
POLL_SECONDS = 5
COMMENT_BUFFER_SECONDS = 30

CAPTURE_DIR = (
    Path(
        os.environ.get(
            "LOCALAPPDATA",
            os.path.expanduser("~"),
        )
    )
    / "AI-TikTok-LIVE-Analyzer"
    / "capture"
)

CAPTURE_DIR.mkdir(
    parents=True,
    exist_ok=True,
)

FRAME_PATH = CAPTURE_DIR / "latest.jpg"
COMMENTS_PATH = CAPTURE_DIR / "latest_comments.json"
ANALYSIS_PAYLOAD_PATH = CAPTURE_DIR / "analysis_payload.json"

started = False
seen_comments = set()
comment_buffer = deque()
battle_monitor = BattleMonitor()


def capture_video_frame():
    js = """
    (() => {
        const videos = Array.from(document.querySelectorAll('video'))
            .map(v => {
                const r = v.getBoundingClientRect();
                const s = getComputedStyle(v);

                const visible =
                    r.width > 80 &&
                    r.height > 80 &&
                    r.right > 0 &&
                    r.bottom > 0 &&
                    r.left < window.innerWidth &&
                    r.top < window.innerHeight &&
                    s.display !== 'none' &&
                    s.visibility !== 'hidden' &&
                    Number(s.opacity || 1) > 0;

                return {
                    video: v,
                    area: r.width * r.height,
                    visible
                };
            })
            .filter(x => x.visible)
            .sort((a, b) => b.area - a.area);

        if (!videos.length) {
            return {
                ok: false,
                error: 'video要素が見つかりません'
            };
        }

        const video = videos[0].video;

        if (!video.videoWidth || !video.videoHeight) {
            return {
                ok: false,
                error: 'videoの実サイズを取得できません'
            };
        }

        try {
            const canvas = document.createElement('canvas');

            canvas.width = video.videoWidth;
            canvas.height = video.videoHeight;

            const ctx = canvas.getContext('2d');

            ctx.drawImage(
                video,
                0,
                0,
                canvas.width,
                canvas.height
            );

            return {
                ok: true,
                width: canvas.width,
                height: canvas.height,
                dataUrl: canvas.toDataURL('image/jpeg', 0.90)
            };

        } catch (e) {
            return {
                ok: false,
                error: String(e)
            };
        }
    })();
    """

    try:
        result = window.evaluate_js(js)
    except Exception as e:
        print("映像取得JSエラー:", e)
        return False

    if not result or not result.get("ok"):
        error = result.get("error") if result else "取得結果なし"
        print("映像フレーム取得失敗:", error)
        return False

    data_url = result["dataUrl"]
    prefix = "data:image/jpeg;base64,"

    if not data_url.startswith(prefix):
        print("想定外の映像データ形式です")
        return False

    raw = base64.b64decode(data_url[len(prefix):])

    temp_path = CAPTURE_DIR / "latest_temp.jpg"
    temp_path.write_bytes(raw)
    os.replace(temp_path, FRAME_PATH)

    return True


def get_new_comments():
    js = """
    (() => {
        const commentTexts = document.querySelectorAll(
            'div.w-full.break-words.align-middle'
        );

        const results = [];

        commentTexts.forEach(el => {
            const container = el.closest(
                'div.flex.flex-col.justify-start.items-start.overflow-hidden.flex-1.break-words'
            );

            if (!container) return;

            const userEl = container.querySelector(
                '[data-e2e="message-owner-name"]'
            );

            const username = userEl ? userEl.innerText.trim() : "";
            const comment = el.innerText.trim();

            if (comment) {
                results.push({
                    username,
                    comment
                });
            }
        });

        return results;
    })();
    """

    try:
        comments = window.evaluate_js(js) or []
    except Exception as e:
        print("コメント取得エラー:", e)
        return []

    new_comments = []

    for item in comments:
        username = (item.get("username") or "").strip()
        comment = (item.get("comment") or "").strip()

        if not comment:
            continue

        key = f"{username}::{comment}"

        if key not in seen_comments:
            seen_comments.add(key)

            new_comments.append({
                "username": username,
                "comment": comment,
                "timestamp": time.time()
            })

    return new_comments


def update_comment_buffer(new_comments):
    now = time.time()

    for item in new_comments:
        comment_buffer.append(item)

    cutoff = now - COMMENT_BUFFER_SECONDS

    while comment_buffer and comment_buffer[0]["timestamp"] < cutoff:
        comment_buffer.popleft()


def save_latest_comments(new_comments):
    payload = {
        "captured_at": datetime.now().isoformat(timespec="seconds"),
        "comments": [
            {
                "username": item["username"],
                "comment": item["comment"]
            }
            for item in new_comments
        ]
    }

    temp_path = COMMENTS_PATH.with_name("latest_comments_temp.json")

    with open(temp_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    os.replace(temp_path, COMMENTS_PATH)


def save_analysis_payload(frame_ok):
    now_ts = time.time()
    frame_file = str(FRAME_PATH)

    comments = [
        {
            "username": item["username"],
            "comment": item["comment"],
            "age_seconds": round(now_ts - item["timestamp"], 1)
        }
        for item in comment_buffer
    ]

    payload = {
        "captured_at": datetime.now().isoformat(timespec="seconds"),
        "frame": {
            "path": frame_file,
            "available": frame_ok
        },
        "comment_window_seconds": COMMENT_BUFFER_SECONDS,
        "comment_count": len(comments),
        "comments": comments
    }

    temp_path = ANALYSIS_PAYLOAD_PATH.with_name(
        "analysis_payload_temp.json"
    )

    with open(temp_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    os.replace(temp_path, ANALYSIS_PAYLOAD_PATH)


def collector_loop():
    time.sleep(3)
    last_url = None

    while True:
        try:
            current_url = window.get_current_url()
            if current_url != last_url:
                last_url = current_url
                match = re.search(r"tiktok\.com/@([^/?]+)/live", current_url or "")
                if match:
                    unique_id = match.group(1)
                    battle_monitor.start(unique_id)
                else:
                    battle_monitor.stop()
            frame_ok = capture_video_frame()
            new_comments = get_new_comments()

            update_comment_buffer(new_comments)
            save_latest_comments(new_comments)
            save_analysis_payload(frame_ok)

            now = time.strftime("%H:%M:%S")

            print(
                f"[{now}] 映像={'OK' if frame_ok else 'NG'} "
                f"/ 新着={len(new_comments)}件 "
                f"/ 直近{COMMENT_BUFFER_SECONDS}秒={len(comment_buffer)}件",
                flush=True,
            )

            for item in new_comments:
                username = item["username"] or "(ユーザー名取得不可)"
                print(
                    f"  - {username}: {item['comment']}",
                    flush=True,
                )

        except Exception as e:
            # 1件のコメントや一時的なWebViewエラーで
            # Collector全体が停止しないよう、次の周期へ進む。
            print(
                f"[Collector Loop Error] {type(e).__name__}: {e}",
                flush=True,
            )

        time.sleep(POLL_SECONDS)


def on_loaded():
    global started

    if started:
        return

    started = True

    print("TikTok LIVEを読み込みました。")
    print("video要素から直接映像フレームを取得します。")
    print(f"{POLL_SECONDS}秒ごとに映像＋コメントを自動取得します。")
    print(f"保存先: {CAPTURE_DIR}")

    thread = threading.Thread(
        target=collector_loop,
        daemon=True
    )
    thread.start()


window = webview.create_window(
    WINDOW_TITLE,
    "https://www.tiktok.com/live",
    width=1400,
    height=900
)

window.events.loaded += on_loaded

webview.start(debug=False)
