import hashlib
import shutil
import time
from collections import deque
from pathlib import Path
from typing import Any


class GiftCandidateQueue:
    """
    Keep rate-limited gift candidate screenshots on disk.

    The queue is FIFO and bounded so continuous monitoring
    cannot grow disk usage without limit.
    """

    def __init__(
        self,
        directory: str | Path = "images/gift_pending",
        max_items: int = 30,
    ):
        if max_items <= 0:
            raise ValueError(
                "max_items must be greater than 0"
            )

        self.directory = Path(directory)
        self.max_items = max_items

        self.directory.mkdir(
            parents=True,
            exist_ok=True,
        )

        self._items: deque[dict[str, Any]] = deque()
        self._last_digest: str | None = None

    def _digest(
        self,
        image_path: Path,
    ) -> str:
        hasher = hashlib.sha256()

        with image_path.open("rb") as file:
            for chunk in iter(
                lambda: file.read(1024 * 1024),
                b"",
            ):
                hasher.update(chunk)

        return hasher.hexdigest()

    def enqueue(
        self,
        image_path: str | Path,
    ) -> dict[str, Any]:
        source = Path(image_path)

        if (
            not source.exists()
            or not source.is_file()
            or source.stat().st_size <= 0
        ):
            return {
                "queued": False,
                "reason": "invalid_source",
                "path": None,
                "size": len(self._items),
            }

        digest = self._digest(source)

        # Avoid filling the queue with the exact same
        # blocked screenshot on every polling cycle.
        if digest == self._last_digest:
            return {
                "queued": False,
                "reason": "duplicate",
                "path": None,
                "size": len(self._items),
            }

        if len(self._items) >= self.max_items:
            return {
                "queued": False,
                "reason": "queue_full",
                "path": None,
                "size": len(self._items),
            }

        suffix = (
            source.suffix
            if source.suffix
            else ".png"
        )

        filename = (
            f"{time.time_ns()}_"
            f"{digest[:12]}"
            f"{suffix}"
        )

        destination = (
            self.directory
            / filename
        )

        shutil.copy2(
            source,
            destination,
        )

        item = {
            "path": destination,
            "digest": digest,
            "created_at_ns": time.time_ns(),
        }

        self._items.append(item)
        self._last_digest = digest

        return {
            "queued": True,
            "reason": "queued",
            "path": str(destination),
            "size": len(self._items),
        }

    def peek(self) -> Path | None:
        if not self._items:
            return None

        return Path(
            self._items[0]["path"]
        )

    def acknowledge(self) -> Path | None:
        if not self._items:
            return None

        item = self._items.popleft()
        path = Path(item["path"])

        if path.exists():
            path.unlink()

        if self._items:
            self._last_digest = (
                self._items[-1]["digest"]
            )
        else:
            self._last_digest = None

        return path

    def clear(self) -> None:
        while self._items:
            item = self._items.popleft()
            path = Path(item["path"])

            if path.exists():
                path.unlink()

        self._last_digest = None

    def __len__(self) -> int:
        return len(self._items)