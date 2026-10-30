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

# Direct script launches must resolve core.* imports in this process and
# in Top-watch worker subprocesses, regardless of the working directory.
if not getattr(sys, "frozen", False):
    _project_root = str(Path(__file__).resolve().parent.parent)
    if _project_root not in sys.path:
        sys.path.insert(0, _project_root)
    _python_paths = os.environ.get("PYTHONPATH", "").split(os.pathsep)
    if _project_root not in _python_paths:
        os.environ["PYTHONPATH"] = os.pathsep.join(
            [_project_root] + [p for p in _python_paths if p]
        )

if __package__:
    from .observation_profile import CAPTURE, PROFILE, FIXED
else:
    from observation_profile import CAPTURE, PROFILE, FIXED

# ------------------------------------------------------------------
# Fixed-observation profile exclusion (Phase 4, fail-closed).
#
# In FIXED mode this collector is the one writer of its profile, so
# THIS process acquires the cross-process profile lock (see
# core/fixed_lock.py) before doing anything else: whichever launcher
# started it (Pulse Pro, top_viewer.py, TopWatch children with their
# own app-data base, another Pulse instance), a second fixed
# collector for the same profile exits here instead of writing.
#
# FAIL-CLOSED: if the lock cannot be initialized, acquired, or
# verified, this process exits WITHOUT collecting. There is no
# fall-through path that collects unguarded. The OS releases the
# lock automatically if this process dies.
# ------------------------------------------------------------------
_FIXED_PROFILE_LOCK = None
if FIXED:
    try:
        try:
            from core.fixed_lock import (acquire_profile_lock_or_exit,
                                         target_id_from_url, write_status)
        except ImportError:
            from fixed_lock import (acquire_profile_lock_or_exit,
                                    target_id_from_url, write_status)
    except Exception as _import_error:
        print(f"固定観測コレクタ: 排他ロックモジュールを読み込めなかったため終了します: {_import_error!r}",
              flush=True)
        sys.exit(4)
    _lock_target = target_id_from_url(os.environ.get("LIVEMETRY_FIXED_URL", ""))
    _FIXED_PROFILE_LOCK = acquire_profile_lock_or_exit(_lock_target)

    def _release_fixed_lock():
        try:
            write_status("released", target_id=_lock_target)
        finally:
            if _FIXED_PROFILE_LOCK is not None:
                _FIXED_PROFILE_LOCK.release()

    import atexit as _atexit
    _atexit.register(_release_fixed_lock)

mode = "dark"

try:
    settings_path = (
        Path(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")))
        / "AI-TikTok-LIVE-Analyzer"
        / "settings.json"
    )

    if settings_path.exists():
        data = json.loads(settings_path.read_text(encoding="utf-8-sig"))
        mode = str(data.get("appearance_mode", "dark")).lower()
except Exception:
    mode = "dark"

if mode == "dark":
    os.environ["WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS"] = "--force-dark-mode"
else:
    os.environ.pop("WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS", None)

import webview

try:
    from core.battle_monitor import BattleMonitor
except ModuleNotFoundError:
    from battle_monitor import BattleMonitor

try:
    from core.random_battle_dataset import RandomBattleDatasetRecorder
except ModuleNotFoundError:
    from random_battle_dataset import RandomBattleDatasetRecorder


try:
    from core.gift_restrictions import match_gift_restriction
except ModuleNotFoundError:
    from gift_restrictions import match_gift_restriction

try:
    from core.low_score_policy import exclusion_reason
except ModuleNotFoundError:
    from low_score_policy import exclusion_reason

try:
    from core.navigation_guard import NavigationGuard, NavigationPause
except ModuleNotFoundError:
    from navigation_guard import NavigationGuard, NavigationPause

navigation_guard = NavigationGuard()

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

SETTINGS_PATH = (
    Path(
        os.environ.get(
            "LOCALAPPDATA",
            os.path.expanduser("~"),
        )
    )
    / "AI-TikTok-LIVE-Analyzer"
    / "settings.json"
)


def get_app_appearance_mode():
    try:
        if SETTINGS_PATH.exists():
            data = json.loads(
                SETTINGS_PATH.read_text(encoding="utf-8-sig")
            )
            mode = str(
                data.get("appearance_mode", "dark")
            ).lower()

            if mode in ("light", "dark"):
                return mode
    except Exception as exc:
        print(
            "[Theme Read Error]",
            repr(exc),
            flush=True,
        )

    return "dark"

CAPTURE_DIR = CAPTURE

CAPTURE_DIR.mkdir(
    parents=True,
    exist_ok=True,
)

FRAME_PATH = CAPTURE_DIR / "latest.jpg"
COMMENTS_PATH = CAPTURE_DIR / "latest_comments.json"
ANALYSIS_PAYLOAD_PATH = CAPTURE_DIR / "analysis_payload.json"

started = False
seen_comments = {}
comment_buffer = deque()
battle_monitor = BattleMonitor()
top_watch = None
if FIXED and os.environ.get('LIVEMETRY_TOP_WATCH') == '1':
    from top_watch import TopWatch
    top_watch = TopWatch(CAPTURE_DIR.parent)


# ===== Battle Hunter =====
BATTLE_HUNTER_ENABLED = True
BATTLE_HUNTER_SCAN_SECONDS = 420
BATTLE_HUNTER_POST_BATTLE_SECONDS = 420
BATTLE_HUNTER_NAVIGATION_COOLDOWN = 7

# Optional configuration in the existing settings.json.
try:
    hunter_settings = json.loads(SETTINGS_PATH.read_text(encoding="utf-8-sig")).get("battle_hunter", {})
    BATTLE_HUNTER_ENABLED = bool(hunter_settings.get("enabled", True))
    BATTLE_HUNTER_SCAN_SECONDS = max(10, int(hunter_settings.get("scan_seconds", 420)))
    BATTLE_HUNTER_POST_BATTLE_SECONDS = max(0, int(hunter_settings.get("post_battle_seconds", 420)))
except (OSError, ValueError, TypeError, AttributeError) as exc:
    print(f"[Battle Hunter Settings] using 420s defaults: {type(exc).__name__}", flush=True)

if FIXED:
    BATTLE_HUNTER_ENABLED = False

random_dataset_recorder = RandomBattleDatasetRecorder(
    sample_probability=1.00,
)


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
    now = time.time()
    for key, last_seen in list(seen_comments.items()):
        if now - last_seen > 60:
            del seen_comments[key]

    for item in comments:
        username = (item.get("username") or "").strip()
        comment = (item.get("comment") or "").strip()

        if not comment:
            continue

        key = f"{username}::{comment}"

        if key not in seen_comments:
            seen_comments[key] = now

            new_comments.append({
                "username": username,
                "comment": comment,
                "timestamp": time.time()
            })

        seen_comments[key] = now

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


def theme_sync_loop():
    last_mode = None

    while True:
        try:
            mode = get_app_appearance_mode()

            # TikTok側の再描画でCSSが消されることがあるため
            # 定期的に再適用する
            apply_viewer_theme()

            if mode != last_mode:
                print(
                    f"[Theme Sync] {last_mode} -> {mode}",
                    flush=True
                )
                last_mode = mode

        except Exception as exc:
            print(
                "[Theme Sync Error]",
                repr(exc),
                flush=True
            )

        time.sleep(5)



def detect_collab_state():
    """
    TikTok LIVE???DOM??
    solo / collab / unknown ????????
    """

    js = r"""
    (() => {
        try {
            const visible = (el) => {
                if (!el) return false;
                const r = el.getBoundingClientRect();
                const s = getComputedStyle(el);

                return (
                    r.width > 80 &&
                    r.height > 80 &&
                    s.display !== 'none' &&
                    s.visibility !== 'hidden' &&
                    parseFloat(s.opacity || '1') > 0
                );
            };

            const videos = Array.from(
                document.querySelectorAll('video')
            ).filter(visible);

            const canvases = Array.from(
                document.querySelectorAll('canvas')
            ).filter(visible);

            const bodyText = (
                document.body?.innerText || ''
            ).toLowerCase();

            const collabWords = [
                'multi-guest',
                'multi guest',
                'co-host',
                'cohost',
                'guest',
                'コラボ',
                'マルチゲスト'
            ];

            const matchedWords = collabWords.filter(
                word => bodyText.includes(word)
            );

            let score = 0;

            // ??video?????????
            if (videos.length >= 2) {
                score += 2;
            }

            // canvas??????????
            if (canvases.length >= 2) {
                score += 1;
            }

            if (matchedWords.length > 0) {
                score += 1;
            }

            let state = 'unknown';

            if (score >= 2) {
                state = 'collab';
            }
            // One video may contain a composited collab. Absence of DOM
            // evidence is unknown, never proof that this room is solo.

            return {
                state,
                score,
                video_count: videos.length,
                canvas_count: canvases.length,
                matched_words: matchedWords
            };
        } catch (e) {
            return {
                state: 'unknown',
                error: String(e)
            };
        }
    })();
    """

    try:
        result = window.evaluate_js(js) or {}

        return {
            "state": str(
                result.get("state") or "unknown"
            ),
            "score": int(
                result.get("score") or 0
            ),
            "video_count": int(
                result.get("video_count") or 0
            ),
            "canvas_count": int(
                result.get("canvas_count") or 0
            ),
            "matched_words": (
                result.get("matched_words") or []
            ),
        }

    except Exception as exc:
        print(
            f"[Collab Detect Error] "
            f"{type(exc).__name__}: {exc}",
            flush=True,
        )

        return {
            "state": "unknown",
            "score": 0,
            "video_count": 0,
            "canvas_count": 0,
            "matched_words": [],
        }




def sync_tiktok_auth_cookies():
    """
    pywebview?TikTok Cookie??
    sessionid / tt-target-idc????????
    BattleMonitor?????????
    ??????????????
    """
    try:
        cookies = window.get_cookies() or []
    except Exception as exc:
        print(
            f"[TikTok Auth] cookie read error: "
            f"{type(exc).__name__}",
            flush=True,
        )
        return False

    if __package__:
        from .tiktok_auth_cookies import extract_auth_cookies
    else:
        from tiktok_auth_cookies import extract_auth_cookies
    session_id, tt_target_idc = extract_auth_cookies(cookies)
    print(
        f"[TikTok Auth] cookie parser v2: session_present={bool(session_id)} "
        f"idc_present={bool(tt_target_idc)}",
        flush=True,
    )

    battle_monitor.set_auth_cookies(
        session_id,
        tt_target_idc,
    )

    if session_id and tt_target_idc:
        print(
            "[TikTok Auth] Viewer login cookies synced",
            flush=True,
        )
        return True

    print(
        "[TikTok Auth] required cookies not found",
        flush=True,
    )
    return False



def get_current_battle_state(unique_id):
    try:
        battle_path = CAPTURE_DIR / "latest_battle.json"

        if not battle_path.exists():
            return None

        data = json.loads(
            battle_path.read_text(encoding="utf-8")
        )

        battle_unique_id = (
            str(data.get("unique_id") or "")
            .strip()
            .lstrip("@")
        )

        if battle_unique_id != unique_id:
            return None

        return data

    except Exception:
        return None


def battle_hunter_open_live():
    """
    TikTok LIVE?????????????????LIVE?1????
    """
    js = r"""
    (() => {
        const isVisible = (el) => {
            const r = el.getBoundingClientRect();
            const s = getComputedStyle(el);

            return (
                r.width > 60 &&
                r.height > 60 &&
                r.bottom > 0 &&
                r.right > 0 &&
                r.top < window.innerHeight &&
                r.left < window.innerWidth &&
                s.display !== 'none' &&
                s.visibility !== 'hidden'
            );
        };

        const links = Array.from(
            document.querySelectorAll('a[href]')
        ).filter(a => {
            const href = a.href || '';

            return (
                /tiktok\.com\/@[^/?]+\/live/.test(href) &&
                isVisible(a)
            );
        });

        if (!links.length) {
            return {
                ok: false,
                reason: 'live-link-not-found'
            };
        }

        links[0].click();

        return {
            ok: true,
            action: 'open-live',
            href: links[0].href
        };
    })();
    """

    try:
        return window.evaluate_js(js)
    except Exception as exc:
        print(
            f"[Battle Hunter] open LIVE error: "
            f"{type(exc).__name__}: {exc}",
            flush=True,
        )
        return None


def battle_hunter_next_live(track=True, probe_only=False):
    """
    ???LIVE????LIVE??????

    1. ??????
    2. ArrowDown
    3. ?????
    ??????
    """
    js = r"""
    (() => {
        const visible = (el) => {
            const r = el.getBoundingClientRect();
            const s = getComputedStyle(el);

            return (
                r.width > 0 &&
                r.height > 0 &&
                r.bottom > 0 &&
                r.right > 0 &&
                r.top < window.innerHeight &&
                r.left < window.innerWidth &&
                s.display !== 'none' &&
                s.visibility !== 'hidden'
            );
        };

        const candidates = Array.from(
            document.querySelectorAll(
                'button, [role="button"], a'
            )
        ).filter(visible);

        const words = ['次のlive', '次のライブ', '次へ', 'next live', 'next'];
        const nextButtons = candidates.filter(el => {
            const label = [el.innerText || '', el.getAttribute('aria-label') || '',
                el.getAttribute('title') || ''].join(' ').trim().toLowerCase();
            const marker = el.getAttribute('data-e2e') || '';
            return words.some(w => label.includes(w)) || /(?:live.*next|next.*live)/i.test(marker);
        });
        const disabled = el => el.disabled === true ||
            el.getAttribute('aria-disabled') === 'true' || el.hasAttribute('disabled');
        const enabled = nextButtons.find(el => !disabled(el));
        if (nextButtons.length && !enabled) {
            return {ok: false, reason: 'next-button-disabled'};
        }
        if (__PROBE_ONLY__) return {ok: false, reason: 'not-confirmed-disabled'};
        if (enabled) {
            enabled.click();
            return {ok: true, action: 'next-button'};
        }

        const keyOptions = {
            key: 'ArrowDown',
            code: 'ArrowDown',
            keyCode: 40,
            which: 40,
            bubbles: true,
            cancelable: true
        };

        document.dispatchEvent(
            new KeyboardEvent('keydown', keyOptions)
        );

        document.body.dispatchEvent(
            new KeyboardEvent('keydown', keyOptions)
        );

        document.dispatchEvent(
            new KeyboardEvent('keyup', keyOptions)
        );

        window.scrollBy({
            top: Math.max(
                window.innerHeight * 0.90,
                600
            ),
            behavior: 'smooth'
        });

        return {
            ok: true,
            action: 'arrow-down-scroll'
        };
    })();
    """

    js = js.replace("__PROBE_ONLY__", "true" if probe_only else "false")
    try:
        if track and not probe_only:
            navigation_guard.begin(window.get_current_url(), time.monotonic())
        result = window.evaluate_js(js)

        print(
            f"[Battle Hunter] next LIVE -> {result}",
            flush=True,
        )

        return result

    except Exception as exc:
        print(
            f"[Battle Hunter] navigation error: "
            f"{type(exc).__name__}: {exc}",
            flush=True,
        )

        return None



def detect_gift_restriction():
    try:
        texts = window.evaluate_js(r"""
        (() => Array.from(document.querySelectorAll(
            'div.w-full.break-words.align-middle, [data-e2e="live-room-title"], [data-e2e="live-title"]'
        )).filter(el => {
            const r = el.getBoundingClientRect();
            const s = getComputedStyle(el);
            return r.width > 0 && r.height > 0 && r.bottom > 0 &&
                r.top < innerHeight && s.display !== 'none' && s.visibility !== 'hidden';
        }).map(el => el.innerText || ''))();
        """) or []
        return match_gift_restriction(texts)
    except Exception as exc:
        print(f"[Gift Restriction Detect Error] {type(exc).__name__}: {exc}", flush=True)
        return None


def should_reopen_live_index(enabled, ended, protected, blocked, elapsed, same_url):
    """Called only after the navigation guard exhausts its three attempts."""
    return bool(enabled and not blocked and same_url and elapsed >= 180
                and (ended or not protected))


def detect_subscription_gate():
    """Recognize a playback paywall, never chat-only subscription prompts."""
    try:
        return bool(window.evaluate_js(r"""
        (() => {
            const gate = /^(サブスク登録して視聴を続け|Subscribe to continue watching)/i;
            return Array.from(document.querySelectorAll('div, p, span, h1, h2')).some(el => {
                const text = (el.innerText || '').replace(/\s+/g, ' ').trim();
                if (!gate.test(text) || text.length > 200) return false;
                if (el.closest('[data-e2e*="chat"], [data-e2e*="comment"], aside, nav')) return false;
                const r = el.getBoundingClientRect(), s = getComputedStyle(el);
                return r.width > 0 && r.height > 0 && s.visibility !== 'hidden'
                    && s.display !== 'none' && Number(s.opacity) !== 0
                    && r.left >= innerWidth * .1 && r.right <= innerWidth * .85
                    && r.top > 0 && r.bottom < innerHeight;
            });
        })();
        """)) and bool(window.get_current_url())
    except Exception:
        return False


def detect_live_unavailable():
    """Look for an exact, visible player error, not text inside the chat/sidebar."""
    try:
        return bool(window.evaluate_js(r"""
        (() => {
            const messages = new Set(['LIVEはありません', 'LIVEは終了しました',
                'このLIVEは終了しました', 'LIVE has ended', 'This LIVE has ended',
                'LIVE is unavailable', 'This LIVE is unavailable']);
            return Array.from(document.querySelectorAll('div, p, span, h1, h2')).some(el => {
                if (!messages.has((el.innerText || '').trim())) return false;
                if (el.closest('[data-e2e*="chat"], [data-e2e*="comment"], aside, nav')) return false;
                const r = el.getBoundingClientRect(), s = getComputedStyle(el);
                return r.width > 0 && r.height > 0 && s.visibility !== 'hidden'
                    && s.display !== 'none' && r.left > innerWidth * .2
                    && r.right < innerWidth * .8 && r.top > 0 && r.bottom < innerHeight;
            });
        })();
        """))
    except Exception:
        return False


def solo_skip_ready(state, solo_since, now, blocked):
    if state not in ("solo", "unknown") or blocked:
        return None, False
    if solo_since is None:
        return now, False
    return solo_since, now - solo_since >= 20


def recovery_log(message):
    print(f"[Battle Hunter] {message}", flush=True)
    try:
        with (CAPTURE_DIR / "navigation_recovery.log").open("a", encoding="utf-8") as file:
            file.write(f"{datetime.now().isoformat(timespec='seconds')} {message}\n")
    except OSError as exc:
        print(f"[Recovery Log Error] {type(exc).__name__}: {exc}", flush=True)


def collector_loop():
    time.sleep(3)

    last_url = None
    gift_rule_candidate = None
    gift_rule_hits = 0
    current_unique_id = None

    live_started_at = time.monotonic()
    live_started_epoch = time.time()

    battle_seen = False
    battle_lock = False
    locked_battle_id = None
    battle_finished_at = None
    skip_candidate_at = None

    last_navigation_at = 0.0
    last_collab_check_at = 0.0
    last_collab_state = None
    solo_since = None
    monitor_retry_at = 0.0
    navigation_paused = False
    navigation_pause = NavigationPause(seconds=60)
    rate_limit_reported = False
    last_index_reopen_at = float("-inf")
    unavailable_since = None
    unavailable_url = None

    from core.collection_health import heartbeat

    while True:
        try:
            heartbeat(CAPTURE_DIR, battle_monitor, navigation_paused)
            current_url = window.get_current_url()
            if top_watch is not None:
                try:
                    watch_state = json.loads((CAPTURE_DIR / 'latest_battle.json').read_text(encoding='utf-8'))
                except (OSError, ValueError):
                    watch_state = {}
                gate_visible = detect_subscription_gate()
                # Discard a detection if navigation changed the room during the DOM read.
                if window.get_current_url() != current_url:
                    continue
                watch_target = top_watch.tick(
                    current_url, watch_state, battle_monitor,
                    subscription_gate=gate_visible, log=recovery_log)
                if watch_target:
                    recovery_log('TOP WATCH: selected next target -> ' + watch_target)
                    window.load_url(watch_target)
                    time.sleep(1)
                    continue
            now_mono = time.monotonic()
            if navigation_pause.resume_if_due(
                now_mono, blocked=battle_monitor.is_connection_blocked()
            ):
                navigation_paused = False
                solo_since = None
                skip_candidate_at = None
                recovery_log("NAV RESUMED: retry cooldown elapsed; rechecking battle/collab before navigation")
            allow_scroll = (
                BATTLE_HUNTER_ENABLED
                and not navigation_paused
                and not battle_monitor.is_connection_blocked()
            )

            # Player error takes precedence over stale battle data from this room.
            if current_url != unavailable_url:
                unavailable_url = current_url
                unavailable_since = None
            unavailable = bool(not FIXED and current_unique_id and detect_live_unavailable())
            if unavailable:
                if unavailable_since is None:
                    unavailable_since = now_mono
            else:
                unavailable_since = None
            unavailable_ready = unavailable_since is not None and now_mono - unavailable_since >= 10

            navigation_action = navigation_guard.observe(current_url, now_mono)
            if navigation_action == "confirmed":
                recovery_log("NAV CONFIRMED: URL changed")
            elif navigation_action in ("retry", "fallback"):
                # Recheck the current battle even while navigation is pending.
                pending_state = get_current_battle_state(current_unique_id) if current_unique_id else None
                protected = bool(pending_state and pending_state.get("active")) and not unavailable_ready
                if protected or battle_monitor.is_connection_blocked():
                    navigation_guard.source = None
                    recovery_log("NAV CANCELLED: active battle or connection block")
                elif navigation_action == "retry":
                    recovery_log(f"NAV RETRY: attempt={navigation_guard.attempts}")
                    battle_hunter_next_live(track=False)
                    last_navigation_at = now_mono
                else:
                    # Three failed URL transitions are enough to recover an
                    # unprotected room; icon-only disabled buttons may have no label.
                    final_state = get_current_battle_state(current_unique_id) if current_unique_id else None
                    final_dom = detect_collab_state().get("state", "unknown")
                    protocol_collab = battle_monitor.collab_state(current_unique_id) == "collab"
                    protected_now = bool(final_state and final_state.get("active")) or final_dom == "collab" or protocol_collab
                    if should_reopen_live_index(
                        allow_scroll and not FIXED, unavailable_ready, protected_now,
                        battle_monitor.is_connection_blocked(),
                        now_mono - last_index_reopen_at,
                        window.get_current_url() == current_url,
                    ):
                        last_index_reopen_at = now_mono
                        last_navigation_at = now_mono
                        navigation_guard.begin(current_url, now_mono)
                        recovery_log("NAV REOPEN INDEX v2: three failed moves; ended or unprotected room")
                        window.load_url("https://www.tiktok.com/live")
                        time.sleep(POLL_SECONDS)
                        continue
                    navigation_paused = True
                    navigation_pause.pause(now_mono)
                    allow_scroll = False
                    recovery_log("NAV PAUSED: recovery cooldown, protected room, or URL changed; rechecking in 60s")

            if current_url != last_url:
                print(
                    f"[Viewer URL Changed] {current_url}",
                    flush=True,
                )

                last_url = current_url
                gift_rule_candidate = None
                gift_rule_hits = 0
                solo_since = None
                last_collab_state = None
                last_collab_check_at = 0.0

                match = re.search(
                    r"tiktok\.com/@([^/?]+)/live",
                    current_url or "",
                )

                if match:
                    unique_id = match.group(1)
                    current_unique_id = unique_id
                    seen_comments.clear()
                    comment_buffer.clear()

                    live_started_at = now_mono
                    live_started_epoch = time.time()

                    battle_seen = False
                    battle_lock = False
                    locked_battle_id = None
                    battle_finished_at = None
                    skip_candidate_at = None

                    random_dataset_recorder.set_current_stream(
                        unique_id
                    )

                    sync_tiktok_auth_cookies()
                    battle_monitor.start(unique_id)
                    monitor_retry_at = now_mono + 60

                    print(
                        f"[Battle Hunter] scanning "
                        f"@{unique_id} "
                        f"for {BATTLE_HUNTER_SCAN_SECONDS}s",
                        flush=True,
                    )

                else:
                    current_unique_id = None

                    random_dataset_recorder.set_current_stream(
                        None
                    )

                    battle_monitor.stop()

            if battle_monitor.is_connection_blocked():
                navigation_paused = True
                allow_scroll = False
                navigation_guard.source = None
                if not rate_limit_reported:
                    recovery_log("RATE LIMIT: signing service quota reached; automatic reconnection and navigation paused")
                    rate_limit_reported = True

            # A worker can end on a network/authentication failure while the URL stays unchanged.
            if current_unique_id and not battle_monitor.is_connection_blocked() and not battle_monitor.is_running() and now_mono >= monitor_retry_at:
                monitor_retry_at = now_mono + 60
                recovery_log(f"MONITOR RESTART @{current_unique_id}")
                sync_tiktok_auth_cookies()
                random_dataset_recorder.set_current_stream(current_unique_id)
                battle_monitor.start(current_unique_id)

            # Suppress further skip decisions while an earlier navigation is pending.
            if navigation_guard.source:
                time.sleep(POLL_SECONDS)
                continue

            if allow_scroll and unavailable_ready and current_unique_id and now_mono - last_navigation_at >= BATTLE_HUNTER_NAVIGATION_COOLDOWN:
                recovery_log(f"LIVE UNAVAILABLE 10s @{current_unique_id} -> SKIP")
                battle_lock = False
                battle_seen = False
                locked_battle_id = None
                battle_finished_at = None
                solo_since = None
                skip_candidate_at = None
                last_navigation_at = now_mono
                battle_hunter_next_live()
                time.sleep(POLL_SECONDS)
                continue

            # Explicit gift restrictions override the normal 7 minute wait.
            if allow_scroll and current_unique_id:
                notified_battle = get_current_battle_state(current_unique_id)
                specific_gift = bool(
                    notified_battle
                    and notified_battle.get("active")
                    and notified_battle.get("gameplay_option") == "MATCH_OPTION_SPECIFIC_GIFT"
                )
                rule = "MATCH_OPTION_SPECIFIC_GIFT" if specific_gift else detect_gift_restriction()
                if rule and rule == gift_rule_candidate:
                    gift_rule_hits += 1
                else:
                    gift_rule_candidate = rule
                    gift_rule_hits = 1 if rule else 0
                if (specific_gift or gift_rule_hits >= 2) and now_mono - last_navigation_at >= BATTLE_HUNTER_NAVIGATION_COOLDOWN:
                    recovery_log(f"GIFT RESTRICTED @{current_unique_id} rule={rule} -> SKIP")
                    # Keep monitoring until the URL actually changes.
                    battle_seen = False
                    battle_lock = False
                    locked_battle_id = None
                    battle_finished_at = None
                    skip_candidate_at = None
                    last_navigation_at = now_mono
                    live_started_at = now_mono
                    live_started_epoch = time.time()
                    battle_hunter_next_live()
                    time.sleep(POLL_SECONDS)
                    continue

            # --------------------------------------
            # Collab Detector
            # --------------------------------------
            if (
                current_unique_id
                and now_mono - last_collab_check_at >= 3
            ):
                last_collab_check_at = now_mono

                collab_result = detect_collab_state()
                collab_state = collab_result.get(
                    "state",
                    "unknown",
                )

                if collab_state != last_collab_state:
                    last_collab_state = collab_state

                    print(
                        "[Collab Detect] "
                        f"@{current_unique_id} "
                        f"state={collab_state} "
                        f"score={collab_result.get('score')} "
                        f"videos={collab_result.get('video_count')} "
                        f"canvas={collab_result.get('canvas_count')} "
                        f"words={collab_result.get('matched_words')}",
                        flush=True,
                    )

            # --------------------------------------
            # Battle Hunter
            # --------------------------------------
            # Collection state remains active even when automatic scrolling is paused.
            if current_unique_id:
                battle_state = get_current_battle_state(
                    current_unique_id
                )

                state_active = bool(
                    battle_state
                    and battle_state.get("active")
                )

                # Unknown rooms use the requested 20s fallback. Positive collab
                # evidence and active battles always block this fallback.
                dom_state = last_collab_state if now_mono - last_collab_check_at <= 6 else "unknown"
                protocol_state = battle_monitor.collab_state(current_unique_id)
                solo_state = ("collab" if "collab" in (dom_state, protocol_state)
                              else "solo" if "solo" in (dom_state, protocol_state)
                              else "unknown")
                solo_since, skip_solo = solo_skip_ready(
                    solo_state, solo_since, now_mono,
                    state_active or not allow_scroll or unavailable,
                )
                if allow_scroll and skip_solo and now_mono - last_navigation_at >= BATTLE_HUNTER_NAVIGATION_COOLDOWN:
                    final_state = get_current_battle_state(current_unique_id)
                    final_dom = detect_collab_state().get("state", "unknown")
                    if (not (final_state and final_state.get("active"))
                        and final_dom != "collab"
                        and battle_monitor.collab_state(current_unique_id) != "collab"
                        and not battle_monitor.is_connection_blocked()
                        and window.get_current_url() == current_url):
                        skip_kind = "SOLO" if solo_state == "solo" else "UNKNOWN"
                        recovery_log(f"{skip_kind} 20s @{current_unique_id} -> SKIP")
                        last_navigation_at = now_mono
                        live_started_at = now_mono
                        live_started_epoch = time.time()
                        solo_since = None
                        skip_candidate_at = None
                        battle_hunter_next_live()
                        time.sleep(POLL_SECONDS)
                        continue
                    solo_since = None

                state_battle_id = (
                    battle_state.get("battle_id")
                    if battle_state
                    else None
                )

                low_score_reason = exclusion_reason(battle_state)
                if allow_scroll and state_active and low_score_reason and now_mono - last_navigation_at >= BATTLE_HUNTER_NAVIGATION_COOLDOWN:
                    recovery_log(f"LOW SCORE @{current_unique_id} battle={state_battle_id} reason={low_score_reason} -> SKIP")
                    random_dataset_recorder.exclude_battle(current_unique_id, state_battle_id, low_score_reason)
                    # Keep monitoring until the URL actually changes.
                    battle_seen = False
                    battle_lock = False
                    locked_battle_id = None
                    battle_finished_at = None
                    skip_candidate_at = None
                    solo_since = None
                    last_navigation_at = now_mono
                    live_started_at = now_mono
                    live_started_epoch = time.time()
                    battle_hunter_next_live()
                    time.sleep(POLL_SECONDS)
                    continue

                if state_active:
                    if not battle_lock:
                        print(
                            f"[Battle Hunter] BATTLE LOCK ON "
                            f"@{current_unique_id} "
                            f"battle={state_battle_id}",
                            flush=True,
                        )

                    battle_seen = True
                    battle_lock = True
                    locked_battle_id = state_battle_id
                    battle_finished_at = None
                    skip_candidate_at = None

                elif battle_state and not state_active:
                    finished_epoch = int(
                        battle_state.get("finished_at") or 0
                    )

                    same_battle = (
                        locked_battle_id is None
                        or state_battle_id == locked_battle_id
                    )

                    recent_finish = (
                        finished_epoch > 0
                        and finished_epoch
                        >= int(live_started_epoch) - 2
                    )

                    if (
                        battle_lock
                        and same_battle
                    ) or (
                        battle_seen
                        and recent_finish
                    ):
                        battle_lock = True

                        if battle_finished_at is None:
                            battle_finished_at = now_mono

                            print(
                                f"[Battle Hunter] BATTLE FINISHED "
                                f"@{current_unique_id} "
                                f"battle={state_battle_id}",
                                flush=True,
                            )

                        elif (
                            now_mono - battle_finished_at
                            >= BATTLE_HUNTER_POST_BATTLE_SECONDS
                        ):
                            if (
                                allow_scroll
                                and now_mono - last_navigation_at
                                >= BATTLE_HUNTER_NAVIGATION_COOLDOWN
                            ):
                                recovery_log(f"BATTLE LOCK OFF @{current_unique_id} -> NEXT LIVE")

                                last_navigation_at = now_mono

                                battle_lock = False
                                battle_seen = False
                                locked_battle_id = None
                                battle_finished_at = None
                                skip_candidate_at = None

                                live_started_at = now_mono
                                live_started_epoch = time.time()

                                battle_hunter_next_live()

                if (
                    allow_scroll
                    and not battle_lock
                    and not battle_seen
                    and now_mono - live_started_at
                    >= BATTLE_HUNTER_SCAN_SECONDS
                ):
                    if skip_candidate_at is None:
                        skip_candidate_at = now_mono

                        print(
                            f"[Battle Hunter] no battle "
                            f"@{current_unique_id} "
                            "-> final check 2s",
                            flush=True,
                        )

                    elif (
                        now_mono - skip_candidate_at >= 2
                    ):
                        final_state = get_current_battle_state(
                            current_unique_id
                        )

                        final_active = bool(
                            final_state
                            and final_state.get("active")
                        )

                        if final_active:
                            battle_seen = True
                            battle_lock = True
                            locked_battle_id = (
                                final_state.get("battle_id")
                            )
                            battle_finished_at = None
                            skip_candidate_at = None

                            print(
                                f"[Battle Hunter] BATTLE LOCK ON "
                                f"@{current_unique_id} "
                                "-> AUTO SLIDE CANCELLED",
                                flush=True,
                            )

                        elif (
                            not battle_lock
                            and now_mono - last_navigation_at
                            >= BATTLE_HUNTER_NAVIGATION_COOLDOWN
                        ):
                            last_navigation_at = now_mono
                            live_started_at = now_mono
                            live_started_epoch = time.time()
                            skip_candidate_at = None

                            recovery_log(f"confirmed no battle @{current_unique_id} -> SKIP")

                            battle_hunter_next_live()

            # TikTok LIVE??????????
            elif (
                allow_scroll
                and not current_unique_id
                and now_mono - live_started_at >= 5
            ):
                if (
                    now_mono - last_navigation_at
                    >= BATTLE_HUNTER_NAVIGATION_COOLDOWN
                ):
                    last_navigation_at = now_mono
                    live_started_at = now_mono

                    print(
                        "[Battle Hunter] LIVE????"
                        "???????",
                        flush=True,
                    )

                    battle_hunter_open_live()

            # ==================================================
            # Battle Hunter ?????
            # ??????JPEG??????????????
            # ??????????Collector?????
            # ==================================================
            if battle_seen:
                try:
                    frame_ok = capture_video_frame()
                except Exception as exc:
                    frame_ok = False
                    print(f"[Frame Capture Error] {type(exc).__name__}: {exc}", flush=True)
                new_comments = get_new_comments()

                current_battle = get_current_battle_state(current_unique_id)
                if current_battle and current_battle.get("active"):
                    try:
                        random_dataset_recorder.record_battle(current_battle)
                        random_dataset_recorder.record_comments(
                            current_unique_id, current_battle.get("battle_id"), new_comments,
                        )
                    except Exception as exc:
                        print(f"[Dataset Save Error] {type(exc).__name__}: {exc}", flush=True)

                update_comment_buffer(new_comments)
                save_latest_comments(new_comments)
                save_analysis_payload(frame_ok)

                now = time.strftime("%H:%M:%S")

                print(
                    f"[{now}] BATTLE??? "
                    f"/ ??={'OK' if frame_ok else 'NG'} "
                    f"/ ??={len(new_comments)}? "
                    f"/ ??{COMMENT_BUFFER_SECONDS}?="
                    f"{len(comment_buffer)}?",
                    flush=True,
                )

                for item in new_comments:
                    username = (
                        item["username"]
                        or "(?????????)"
                    )

                    print(
                        f"  - {username}: "
                        f"{item['comment']}",
                        flush=True,
                    )

            else:
                print(
                    "[Battle Hunter] ????? "
                    "- ??/????????",
                    flush=True,
                )

        except Exception as e:
            print(
                f"[Collector Loop Error] "
                f"{type(e).__name__}: {e}",
                flush=True,
            )

        time.sleep(POLL_SECONDS)



def apply_viewer_theme():
    mode = get_app_appearance_mode()

    js = f"""
    (() => {{
        const id = 'livemetry-theme-style';

        let style = document.getElementById(id);

        if (!style) {{
            style = document.createElement('style');
            style.id = id;
            document.head.appendChild(style);
        }}

        if ('{mode}' === 'dark') {{
            style.textContent = `
                html, body {{
                    background: #0B1120 !important;
                    color: #F8FAFC !important;
                }}

                div {{
                    border-color: #243047 !important;
                }}
            `;
        }} else {{
            style.textContent = '';
        }}

        return '{mode}';
    }})();
    """

    try:
        result = window.evaluate_js(js)
        print(
            f"[Viewer Theme] {result}",
            flush=True
        )
    except Exception as exc:
        print(
            "[Viewer Theme Error]",
            repr(exc),
            flush=True
        )


def on_loaded():
    try:
        sync_tiktok_auth_cookies()
    except Exception as exc:
        print(
            f"[TikTok Auth] sync error: "
            f"{type(exc).__name__}: {exc}",
            flush=True,
        )
    global started

    if started:
        return

    started = True

    random_dataset_recorder.start()

    print("TikTok LIVEを読み込みました。")
    print("video要素から直接映像フレームを取得します。")
    print(f"{POLL_SECONDS}秒ごとに映像＋コメントを自動取得します。")
    print(f"保存先: {CAPTURE_DIR}")
    apply_viewer_theme()

    theme_thread = threading.Thread(
        target=theme_sync_loop,
        daemon=True
    )
    theme_thread.start()

    thread = threading.Thread(
        target=collector_loop,
        daemon=True
    )
    thread.start()


window = webview.create_window(
    "Livemetry Pulse - Top固定観測" if FIXED else WINDOW_TITLE,
    os.environ.get("LIVEMETRY_FIXED_URL", "https://www.tiktok.com/live") if FIXED else "https://www.tiktok.com/live",
    width=1400,
    height=900
)

window.events.loaded += on_loaded

webview.start(
    debug=False,
    private_mode=False,
    storage_path=str(PROFILE),
)

random_dataset_recorder.stop()
battle_monitor.stop()
