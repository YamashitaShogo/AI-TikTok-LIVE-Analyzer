from core.battle_effect_capture import BattleEffectCapture
import asyncio
import json
import os
import threading
import time
import tempfile
from pathlib import Path

if __package__:
    from .observation_profile import CAPTURE, PROFILE, FIXED
else:
    from observation_profile import CAPTURE, PROFILE, FIXED
from typing import Optional

from TikTokLive import TikTokLiveClient
from TikTokLive.client.web.web_settings import WebDefaults
from TikTokLive import events as live_events
if __package__:
    from .battle_timeline import record as record_timeline
else:
    from battle_timeline import record as record_timeline
from TikTokLive.events import ConnectEvent, RoomUserSeqEvent, LinkMicArmiesEvent, LinkMicBattleEvent, LinkMicBattleItemCardEvent, LinkMicMethodEvent, LinkEvent, LinkLayerEvent
if __package__:
    from .collab_lifecycle import lifecycle_state, redact_link_event
    from .monitor_connection import listen, drain_loop
    from .proto_type_compat import prepare_proto_types
else:
    from collab_lifecycle import lifecycle_state, redact_link_event
    from monitor_connection import listen, drain_loop
    from proto_type_compat import prepare_proto_types
from TikTokLiveProto.v3.webcast.im import LinkMicBattleBattleAction

_prepared_proto_types = prepare_proto_types()
print(f"[Proto Compat] ready; rebuilt={_prepared_proto_types}", flush=True)

APP_NAME = "AI-TikTok-LIVE-Analyzer"

CAPTURE_DIR = CAPTURE

CAPTURE_DIR.mkdir(parents=True, exist_ok=True)

BATTLE_PATH = CAPTURE_DIR / "latest_battle.json"
BATTLE_ITEMS_PATH = CAPTURE_DIR / "battle_items.json"


def configure_sign_api_key() -> bool:
    """Use a locally configured key without writing it to source or logs."""
    key = os.environ.get("LIVEMETRY_EULER_API_KEY", "").strip()
    WebDefaults.tiktok_sign_api_key = key or None
    print(
        "[Battle Monitor] Euler API key configured"
        if key else "[Battle Monitor] Euler API key not configured (anonymous limits)",
        flush=True,
    )
    return bool(key)


class BattleMonitor:
    def __init__(self) -> None:
        self._thread: Optional[threading.Thread] = None
        self._client: Optional[TikTokLiveClient] = None
        self._loop = None
        self._lock = threading.RLock()

        self._unique_id: Optional[str] = None
        self._battle_id: Optional[int] = None
        self._last_update_time = 0
        self._finished_battle_ids: set[int] = set()
        self._generation = 0
        self._connection_blocked = False
        self._offline_unique_id = None
        self._connected = False
        self._collab_seen = False
        self._collab_state_known = False
        self._last_link_event_time = 0
        self._timeout_battle_ids: set[int] = set()
        self._battle_timing = (0, 0)
        self._battle_gameplay_option = ""

        # Viewer authentication cookies are kept only in memory.
        self._session_id: Optional[str] = None
        self._tt_target_idc: Optional[str] = None

    def set_auth_cookies(
        self,
        session_id: Optional[str],
        tt_target_idc: Optional[str],
    ) -> None:
        with self._lock:
            self._session_id = (
                str(session_id).strip()
                if session_id
                else None
            )
            self._tt_target_idc = (
                str(tt_target_idc).strip()
                if tt_target_idc
                else None
            )

        if self._session_id and self._tt_target_idc:
            print(
                "[Battle Monitor] authenticated session ready",
                flush=True,
            )
        else:
            print(
                "[Battle Monitor] authenticated session unavailable",
                flush=True,
            )


    def is_running(self) -> bool:
        return (
            self._thread is not None
            and self._thread.is_alive()
        )

    def is_connection_blocked(self) -> bool:
        with self._lock:
            return self._connection_blocked

    def offline_unique_id(self):
        """Only a confirmed offline response; authentication/network errors are unknown."""
        with self._lock:
            return self._offline_unique_id

    def collab_state(self, unique_id: str) -> str:
        """Protocol evidence for the current room; a connection alone proves nothing."""
        with self._lock:
            if self._unique_id != unique_id or not self._connected:
                return "unknown"
            if self._collab_seen:
                return "collab"
            return "solo" if self._collab_state_known else "unknown"

    def can_skip_solo(self, unique_id: str) -> bool:
        with self._lock:
            return bool(
                self._connected
                and self._collab_state_known
                and not self._collab_seen
                and not self._connection_blocked
                and self._unique_id == unique_id
            )

    def start(self, unique_id: str) -> bool:
        if self.is_connection_blocked():
            return False
        unique_id = unique_id.strip().lstrip("@")

        if not unique_id:
            return False

        if self.is_running() and self._unique_id == unique_id:
            return False

        self.stop()

        with self._lock:
            self._generation += 1
            generation = self._generation
            self._unique_id = unique_id
            self._offline_unique_id = None
            self._battle_id = None
            self._last_update_time = 0
            self._finished_battle_ids.clear()
            self._timeout_battle_ids.clear()
            self._battle_timing = (0, 0)
            self._battle_gameplay_option = ""

        self._thread = threading.Thread(
            target=self._worker,
            args=(unique_id, generation),
            daemon=True,
            name="BattleMonitor",
        )
        self._thread.start()

        return True

    def stop(self) -> None:
        with self._lock:
            self._generation += 1
            client = self._client
            loop = self._loop

            self._connected = False
            self._collab_seen = False
            self._collab_state_known = False
            self._last_link_event_time = 0
            self._client = None
            self._loop = None
            self._thread = None
            self._unique_id = None
            self._offline_unique_id = None
            self._battle_id = None
            self._last_update_time = 0
            self._finished_battle_ids.clear()
            self._timeout_battle_ids.clear()
            self._battle_timing = (0, 0)
            self._battle_gameplay_option = ""
            self._write_payload({"active": False, "unique_id": "", "battle_id": 0, "reason": "stopped", "update_time": 0})
            (CAPTURE_DIR / "latest_room_info.json").unlink(missing_ok=True)

        if client is not None and loop is not None and loop.is_running():
            try:
                asyncio.run_coroutine_threadsafe(
                    client.disconnect(close_client=False),
                    loop,
                )
            except Exception as exc:
                print(
                    f"[Battle Monitor Stop Error] "
                    f"{type(exc).__name__}: {exc}",
                    flush=True,
                )

    def _worker(self, unique_id: str, generation: int) -> None:
        configure_sign_api_key()
        client = TikTokLiveClient(
            unique_id=f"@{unique_id}",
            ws_kwargs={"close_timeout": 1},
        )

        with self._lock:
            session_id = self._session_id
            tt_target_idc = self._tt_target_idc

        if session_id and tt_target_idc:
            # Configure the authenticated session signing host.
            os.environ[
                "WHITELIST_AUTHENTICATED_SESSION_ID_HOST"
            ] = "api.eulerstream.com"

            client.web.set_session(
                session_id,
                tt_target_idc,
            )

            print(
                "[Battle Monitor] using authenticated TikTok session",
                flush=True,
            )

        async def on_connect(event: ConnectEvent):
            with self._lock:
                if generation != self._generation:
                    return
                self._connected = True
                if isinstance(client.room_info, dict):
                    (CAPTURE_DIR / "latest_room_info.json").write_text(
                        json.dumps(
                            client.room_info,
                            ensure_ascii=False,
                            indent=2,
                        ),
                        encoding="utf-8",
                    )
        async def on_linkmic(event: LinkMicMethodEvent):
            with self._lock:
                if generation != self._generation:
                    return
                event_data = event.to_dict()
                state, reason = lifecycle_state(event_data)
                try:
                    event_time = int((event_data.get("common") or {}).get("createTime") or 0)
                except (TypeError, ValueError):
                    event_time = 0
                if state and event_time >= self._last_link_event_time:
                    self._last_link_event_time = event_time
                    self._collab_seen = state == "collab"
                    self._collab_state_known = True
                    print(f"[Collab Lifecycle] @{unique_id} state={state} reason={reason}", flush=True)
                event_data = redact_link_event(event_data)

                (CAPTURE_DIR / "latest_linkmic_event_debug.json").write_text(
                    json.dumps(
                        event_data,
                        ensure_ascii=False,
                        indent=2,
                    ),
                    encoding="utf-8",
                )

                history_path = (
                    CAPTURE_DIR
                    / "linkmic_event_history.json"
                )

                try:
                    if history_path.exists():
                        history = json.loads(
                            history_path.read_text(
                                encoding="utf-8"
                            )
                        )
                    else:
                        history = []
                except Exception:
                    history = []

                if not isinstance(history, list):
                    history = []

                history.append({
                    "saved_at": int(time.time()),
                    "event": event_data,
                })

                history = history[-300:]

                history_path.write_text(
                    json.dumps(
                        history,
                        ensure_ascii=False,
                        indent=2,
                    ),
                    encoding="utf-8",
                )
        async def on_battle(event: LinkMicArmiesEvent):
            self._handle_battle(
                event=event,
                unique_id=unique_id,
                generation=generation,
            )

        async def on_battle_state(event: LinkMicBattleEvent):
            self._handle_battle_state(
                event=event,
                unique_id=unique_id,
                generation=generation,
            )

        async def on_battle_item(event: LinkMicBattleItemCardEvent):
            self._handle_battle_item(
                event=event,
                unique_id=unique_id,
                generation=generation,
            )

        async def on_viewer_count(event: RoomUserSeqEvent):
            with self._lock:
                if generation != self._generation or not self._battle_id:
                    return
                # RoomUserSeq total is the current audience count; cumulative
                # room totals must not be substituted for this metric.
                count = getattr(event, "total", None)
                if count is None:
                    print("[Viewer Count] no total field in RoomUserSeqEvent", flush=True)
                    return
                try:
                    try:
                        from core.random_battle_dataset import record_viewer_count
                    except ModuleNotFoundError:
                        from random_battle_dataset import record_viewer_count
                    record_viewer_count(unique_id, self._battle_id, count, time.time())
                except Exception as exc:
                    print(f"[Viewer Count Save Error] {type(exc).__name__}: {exc}", flush=True)

        client.add_listener(ConnectEvent, on_connect)
        client.add_listener(RoomUserSeqEvent, on_viewer_count)
        client.add_listener(LinkMicMethodEvent, on_linkmic)
        client.add_listener(LinkEvent, on_linkmic)
        client.add_listener(LinkLayerEvent, on_linkmic)
        client.add_listener(LinkMicArmiesEvent, on_battle)
        client.add_listener(LinkMicBattleEvent, on_battle_state)
        client.add_listener(LinkMicBattleItemCardEvent, on_battle_item)
        async def on_battle_task(event):
            self._record_timeline(event, unique_id, generation, 'challenge')
        task_event = getattr(live_events, 'LinkmicBattleTaskEvent', None)
        if task_event is not None:
            client.add_listener(task_event, on_battle_task)
        else:
            print('[Battle Timeline] challenge event unavailable in installed TikTokLive', flush=True)

        # Raw message diagnostics preserve fields missing from the SDK schema.
        # This does not alter battle locks, scores, or navigation policy.
        probe = None
        # Optional reader: writes structured challenge metadata only.
        # No interference with the existing scores, Hunter, Viewer or probe.
        challenge_tracker = None
        try:
            from core.challenge_tracker import ChallengeTracker
            challenge_tracker = ChallengeTracker(CAPTURE_DIR, unique_id)
            print('[Challenge Tracker] structured events enabled', flush=True)
        except Exception as exc:
            print(f'[Challenge Tracker Init Error] {type(exc).__name__}: {exc}', flush=True)

        response_event = getattr(live_events, 'WebsocketResponseEvent', None)
        try:
            from core.challenge_probe import ChallengeProbe
            if response_event is not None:
                probe = ChallengeProbe(CAPTURE_DIR, unique_id)
                async def on_raw_notification(event):
                    with self._lock:
                        if generation != self._generation:
                            return
                        bid = self._battle_id
                    try:
                        probe.capture(event, bid)
                    except Exception as exc:
                        print(f'[Challenge Probe Error] {type(exc).__name__}: {exc}', flush=True)
                    if challenge_tracker is not None:
                        try:
                            challenge_tracker.capture(event)
                        except Exception as exc:
                            print(f'[Challenge Tracker Error] {type(exc).__name__}: {exc}', flush=True)
                client.add_listener(response_event, on_raw_notification)
                print('[Challenge Probe] raw notification capture enabled', flush=True)
            else:
                print('[Challenge Probe] WebsocketResponseEvent unavailable', flush=True)
        except Exception as exc:
            print(f'[Challenge Probe Error] {type(exc).__name__}: {exc}', flush=True)

        loop = asyncio.new_event_loop()

        with self._lock:
            if generation != self._generation:
                loop.close()
                if probe is not None:
                    probe.close()
                if challenge_tracker is not None:
                    challenge_tracker.close()
                return

            self._client = client
            self._loop = loop

        print(
            f"[Battle Monitor] watching @{unique_id}",
            flush=True,
        )


        try:
            loop.run_until_complete(listen(client))
        except Exception as exc:
            if type(exc).__name__ == "UserOfflineError":
                with self._lock:
                    if generation == self._generation:
                        self._offline_unique_id = unique_id
            if type(exc).__name__ == "SignatureRateLimitError":
                with self._lock:
                    if generation == self._generation:
                        self._connection_blocked = True
                print("[Battle Monitor] signature rate limit reached; automatic reconnection disabled for this Viewer session", flush=True)
            print(
                f"[Battle Monitor Error] "
                f"{type(exc).__name__}: {exc}",
                flush=True,
            )
        finally:
            try:
                drain_loop(loop)
            finally:
                if probe is not None:
                    probe.close()
                if challenge_tracker is not None:
                    challenge_tracker.close()
                with self._lock:
                    if generation == self._generation:
                        self._connected = False
                        self._client = None
                        self._loop = None


    def _record_timeline(self, event, unique_id, generation, kind):
        with self._lock:
            if generation != self._generation:
                return
            try:
                payload = event.to_dict()
                bid = int(payload.get('battleId') or 0)
                record_timeline(CAPTURE_DIR / 'battle_dataset' / 'battles.sqlite3',
                                unique_id, bid, kind, payload, time.time())
            except Exception as exc:
                print(f'[Battle Timeline Error] {type(exc).__name__}: {exc}', flush=True)

    def _handle_battle_item(
        self,
        event: LinkMicBattleItemCardEvent,
        unique_id: str,
        generation: int,
    ) -> None:
        with self._lock:
            if generation != self._generation:
                return
            with self._lock:
                if generation != self._generation:
                    return

            self._record_timeline(event, unique_id, generation, "item")
            item = event.to_dict()

            payload = {
                "unique_id": unique_id,
                "battle_id": int(event.battle_id or 0),
                "msg_type": str(event.msg_type),
                "received_at": int(time.time()),
                "event": item,
            }

            history = []

            if BATTLE_ITEMS_PATH.exists():
                try:
                    history = json.loads(
                        BATTLE_ITEMS_PATH.read_text(
                            encoding="utf-8",
                        )
                    )
                except Exception:
                    history = []

            if not isinstance(history, list):
                history = []

            history.append(payload)
            history = history[-200:]

            BATTLE_ITEMS_PATH.write_text(
                json.dumps(
                    history,
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
    def _battle_timeout_worker(
        self,
        unique_id: str,
        battle_id: int,
        generation: int,
        start_time_ms: int,
        duration_seconds: int,
    ) -> None:
        """
        TikTok??FINISH?????????????????
        battleSettings????? + duration + ????????????
        """
        grace_seconds = 8

        end_epoch = (
            (start_time_ms / 1000.0)
            + duration_seconds
            + grace_seconds
        )

        delay = max(0.0, end_epoch - time.time())

        print(
            f"[Battle Monitor] timeout fallback scheduled "
            f"battle={battle_id} "
            f"in {delay:.1f}s",
            flush=True,
        )

        time.sleep(delay)

        with self._lock:
            with self._lock:
                if generation != self._generation:
                    return

                if self._battle_id != battle_id:
                    return

                if battle_id in self._finished_battle_ids:
                    return

                self._finished_battle_ids.add(battle_id)
                self._battle_id = None
                self._last_update_time = 0

            result_payload = {
                "active": False,
                "unique_id": unique_id,
                "battle_id": battle_id,
                "update_time": 0,
                "reason": "timeout_fallback",
                "finished_at": int(time.time()),
                "result_display_seconds": 120,
            }

            try:
                if BATTLE_PATH.exists():
                    previous = json.loads(
                        BATTLE_PATH.read_text(
                            encoding="utf-8"
                        )
                    )

                    if int(
                        previous.get("battle_id") or 0
                    ) == battle_id:
                        for key in (
                            "mode",
                            "participants",
                            "teams",
                            "host_user_id",
                            "host_nickname",
                        ):
                            if key in previous:
                                result_payload[key] = previous[key]

            except Exception as exc:
                print(
                    f"[Battle Monitor] timeout payload read error: "
                    f"{type(exc).__name__}: {exc}",
                    flush=True,
                )

            self._write_payload(result_payload)

            print(
                f"[Battle Monitor] battle timeout finished "
                f"battle={battle_id}",
                flush=True,
            )


    def _handle_battle_state(
        self,
        event: LinkMicBattleEvent,
        unique_id: str,
        generation: int,
    ) -> None:
        with self._lock:
            if generation != self._generation:
                return
            # Keep START/update payloads too: introductory bonuses may be here.
            self._record_timeline(event, unique_id, generation, 'battle_state')
            if event.action not in (
                LinkMicBattleBattleAction.FINISH,
                LinkMicBattleBattleAction.LINK_MIC_BATTLE_BATTLE_ACTION_CUT_SHORT,
            ):
                return

            debug_event = event.to_dict()
            (CAPTURE_DIR / "latest_battle_state_debug.json").write_text(
                json.dumps(debug_event, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

            battle_id = int(event.battle_id or 0)

            with self._lock:
                if generation != self._generation:
                    return

                if (
                    self._battle_id is not None
                    and battle_id
                    and battle_id != self._battle_id
                ):
                    return

                if battle_id:
                    self._finished_battle_ids.add(battle_id)

                self._battle_id = None
                self._last_update_time = 0

            reason = (
                "finished"
                if event.action == LinkMicBattleBattleAction.FINISH
                else "cut_short"
            )

            result_payload = {
                "active": False,
                "unique_id": unique_id,
                "battle_id": battle_id,
                "update_time": 0,
                "reason": reason,
                "finished_at": int(time.time()),
                "result_display_seconds": 120,
            }

            try:
                if BATTLE_PATH.exists():
                    previous = json.loads(
                        BATTLE_PATH.read_text(encoding="utf-8")
                    )

                    if int(previous.get("battle_id") or 0) == battle_id:
                        for key in ("mode", "participants", "teams", "host_user_id", "host_nickname"):
                            if key in previous:
                                result_payload[key] = previous[key]
            except Exception:
                pass

            self._write_payload(result_payload)

    def _handle_battle(
        self,
        event: LinkMicArmiesEvent,
        unique_id: str,
        generation: int,
    ) -> None:
        with self._lock:
            if generation != self._generation:
                return
            debug_event = event.to_dict()
            try:
                if not hasattr(self, '_effect_capture'):
                    self._effect_capture = BattleEffectCapture()
                self._effect_capture.capture(
                    CAPTURE_DIR / 'battle_dataset' / 'battles.sqlite3',
                    unique_id, debug_event, time.time())
            except Exception as exc:
                print(f'[Battle Effect Capture Error] {type(exc).__name__}: {exc}', flush=True)
            (CAPTURE_DIR / "latest_battle_state_debug.json").write_text(
                json.dumps(debug_event, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

            battle_id = int(event.battle_id or 0)
            update_time = int(event.update_battle_score_time or 0)

            battle_settings = (
                debug_event.get("battleSettings")
                or {}
            )

            try:
                start_time_ms = int(
                    battle_settings.get("startTimeMs")
                    or 0
                )
            except Exception:
                start_time_ms = 0

            try:
                duration_seconds = int(
                    battle_settings.get("duration")
                    or 0
                )
            except Exception:
                duration_seconds = 0

            # A room can replay its previous battle on connection. Do not
            # treat a clearly expired, newly encountered battle as live collab.
            if (battle_id and battle_id != self._battle_id
                    and battle_id not in self._finished_battle_ids
                    and 946684800000 <= start_time_ms <= 4102444800000
                    and 0 < duration_seconds <= 3600
                    and start_time_ms / 1000.0 + duration_seconds + 8 <= time.time()):
                self._finished_battle_ids.add(battle_id)
                print(f'[Battle Monitor] STALE BATTLE ignored battle={battle_id}; collab state unchanged', flush=True)
                return

            schedule_timeout = False

            with self._lock:
                if generation != self._generation:
                    return

                if (
                    battle_id
                    and battle_id in self._finished_battle_ids
                ):
                    return

                if battle_id != self._battle_id:
                    self._battle_id = battle_id
                    self._last_update_time = 0
                    self._battle_timing = (0, 0)
                    self._battle_gameplay_option = ""


                if (
                    update_time
                    and update_time < self._last_update_time
                ):
                    return

                if update_time:
                    self._last_update_time = update_time

                if battle_id:
                    self._collab_seen = True
                    self._collab_state_known = True

            gameplay_option = battle_settings.get("gameplayOption")
            if gameplay_option:
                self._battle_gameplay_option = str(gameplay_option)

            old_start, old_duration = self._battle_timing
            start_time_ms = start_time_ms or old_start
            duration_seconds = duration_seconds or old_duration
            self._battle_timing = (start_time_ms, duration_seconds)
            if (battle_id and start_time_ms > 0 and duration_seconds > 0
                    and battle_id not in self._timeout_battle_ids):
                self._timeout_battle_ids.add(battle_id)
                schedule_timeout = True

            room_owner = {}
            try:
                room_info = json.loads(
                    (CAPTURE_DIR / "latest_room_info.json").read_text(
                        encoding="utf-8",
                    )
                )
                room_owner = room_info.get("owner") or {}
            except Exception:
                pass

            payload = {
                "active": True,
                "host_user_id": str(room_owner.get("id_str") or room_owner.get("id") or ""),
                "host_nickname": str(room_owner.get("nickname") or ""),
                "unique_id": unique_id,
                "battle_id": battle_id,
                "update_time": update_time,
                "start_time_ms": start_time_ms,
                "duration_seconds": duration_seconds,
                "gameplay_option": self._battle_gameplay_option,
            }

            if event.team_armies:
                teams = []

                for team in event.team_armies:
                    users = []

                    for user in team.team_user:
                        users.append(
                            {
                                "user_id": (
                                    user.user_id_str
                                    or str(user.user_id)
                                ),
                                "score": int(user.score or 0),
                            }
                        )

                    teams.append(
                        {
                            "team_id": str(team.team_id),
                            "score": int(
                                team.team_total_score or 0
                            ),
                            "users": users,
                        }
                    )

                payload["mode"] = "team"
                payload["teams"] = teams

            else:
                participants = []

                for key, army in event.armies.items():
                    participants.append(
                        {
                            "key": str(key),
                            "anchor_id": army.anchor_id_str,
                            "score": int(army.hostscore or 0),
                            "score_known": "hostscore" in (debug_event.get("armies", {}).get(str(key)) or {}),
                        }
                    )

                participants.sort(key=lambda item: str(item.get("anchor_id") or item.get("key") or ""))

                payload["mode"] = "individual"
                payload["participants"] = participants

            if payload.get("mode") == "team":
                raw_teams = debug_event.get("teamArmies") or []
                for team in payload["teams"]:
                    team["score_known"] = any(
                        str(raw.get("teamId")) == team["team_id"] and "teamTotalScore" in raw
                        for raw in raw_teams if isinstance(raw, dict)
                    )

            self._write_payload(payload)

            if schedule_timeout:
                threading.Thread(
                    target=self._battle_timeout_worker,
                    args=(
                        unique_id,
                        battle_id,
                        generation,
                        start_time_ms,
                        duration_seconds,
                    ),
                    daemon=True,
                    name=f"BattleTimeout-{battle_id}",
                ).start()

    @staticmethod
    def _write_payload(payload: dict) -> None:
        # Keep durable history independent of Windows file sharing failures.
        try:
            try:
                from core.random_battle_dataset import record_battle_payload
            except ModuleNotFoundError:
                from random_battle_dataset import record_battle_payload
            record_battle_payload(payload)
        except Exception as exc:
            print(f"[Battle Dataset Save Error] {type(exc).__name__}: {exc}", flush=True)

        temp_path = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", dir=BATTLE_PATH.parent,
                prefix="latest_battle_", suffix=".tmp", delete=False,
            ) as handle:
                temp_path = Path(handle.name)
                json.dump(payload, handle, ensure_ascii=False, indent=2)
            for attempt in range(6):
                try:
                    temp_path.replace(BATTLE_PATH)
                    return
                except PermissionError:
                    if attempt == 5:
                        raise
                    time.sleep(0.02 * (2 ** attempt))
        except OSError as exc:
            print(f"[Battle Latest File Save Error] {type(exc).__name__}: {exc}", flush=True)
        finally:
            if temp_path is not None:
                try:
                    temp_path.unlink(missing_ok=True)
                except OSError as exc:
                    print(f"[Battle Temp Cleanup Error] {type(exc).__name__}: {exc}", flush=True)
