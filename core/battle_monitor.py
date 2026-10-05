import asyncio
import json
import os
import threading
import time
from pathlib import Path
from typing import Optional

from TikTokLive import TikTokLiveClient
from TikTokLive.events import LinkMicArmiesEvent, LinkMicBattleEvent
from TikTokLiveProto.v3.webcast.im import LinkMicBattleBattleAction


APP_NAME = "AI-TikTok-LIVE-Analyzer"

CAPTURE_DIR = (
    Path(
        os.environ.get(
            "LOCALAPPDATA",
            os.path.expanduser("~"),
        )
    )
    / APP_NAME
    / "capture"
)

CAPTURE_DIR.mkdir(parents=True, exist_ok=True)

BATTLE_PATH = CAPTURE_DIR / "latest_battle.json"


class BattleMonitor:
    def __init__(self) -> None:
        self._thread: Optional[threading.Thread] = None
        self._client: Optional[TikTokLiveClient] = None
        self._loop = None
        self._lock = threading.Lock()

        self._unique_id: Optional[str] = None
        self._battle_id: Optional[int] = None
        self._last_update_time = 0
        self._finished_battle_ids: set[int] = set()
        self._generation = 0

    def is_running(self) -> bool:
        return (
            self._thread is not None
            and self._thread.is_alive()
        )

    def start(self, unique_id: str) -> bool:
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
            self._battle_id = None
            self._last_update_time = 0
            self._finished_battle_ids.clear()

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

            self._client = None
            self._loop = None
            self._thread = None
            self._unique_id = None
            self._battle_id = None
            self._last_update_time = 0
            self._finished_battle_ids.clear()

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
        client = TikTokLiveClient(
            unique_id=f"@{unique_id}",
            ws_kwargs={"close_timeout": 1},
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

        client.add_listener(LinkMicArmiesEvent, on_battle)
        client.add_listener(LinkMicBattleEvent, on_battle_state)

        loop = client._asyncio_loop

        with self._lock:
            if generation != self._generation:
                return

            self._client = client
            self._loop = loop

        print(
            f"[Battle Monitor] watching @{unique_id}",
            flush=True,
        )

        try:
            client.run(
                fetch_room_info=False,
                fetch_gift_info=False,
                fetch_live_check=True,
            )
        except Exception as exc:
            print(
                f"[Battle Monitor Error] "
                f"{type(exc).__name__}: {exc}",
                flush=True,
            )
        finally:
            with self._lock:
                if generation == self._generation:
                    self._client = None
                    self._loop = None

    def _handle_battle_state(
        self,
        event: LinkMicBattleEvent,
        unique_id: str,
        generation: int,
    ) -> None:
        if event.action not in (
            LinkMicBattleBattleAction.FINISH,
            LinkMicBattleBattleAction.LINK_MIC_BATTLE_BATTLE_ACTION_CUT_SHORT,
        ):
            return

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
                    for key in ("mode", "participants", "teams"):
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
        battle_id = int(event.battle_id or 0)
        update_time = int(event.update_battle_score_time or 0)

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

            if (
                update_time
                and update_time < self._last_update_time
            ):
                return

            if update_time:
                self._last_update_time = update_time

        payload = {
            "active": True,
            "unique_id": unique_id,
            "battle_id": battle_id,
            "update_time": update_time,
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
                    }
                )

            payload["mode"] = "individual"
            payload["participants"] = participants

        self._write_payload(payload)

    @staticmethod
    def _write_payload(payload: dict) -> None:
        temp_path = BATTLE_PATH.with_suffix(".tmp")

        temp_path.write_text(
            json.dumps(
                payload,
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

        temp_path.replace(BATTLE_PATH)
