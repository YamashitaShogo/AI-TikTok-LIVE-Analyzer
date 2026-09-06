import json
from pathlib import Path
from typing import Any


class GiftCatalog:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.data = self._load()

    def _load(self) -> dict[str, Any]:
        if not self.path.exists():
            return {
                "schema_version": 1,
                "updated_at": None,
                "gifts": [],
            }

        with self.path.open(
            "r",
            encoding="utf-8-sig",
        ) as file:
            return json.load(file)

    def get_gifts(self) -> list[dict[str, Any]]:
        gifts = self.data.get("gifts", [])

        if not isinstance(gifts, list):
            return []

        return gifts

    def find_by_id(
        self,
        gift_id: str,
    ) -> dict[str, Any] | None:
        normalized = gift_id.strip().lower()

        for gift in self.get_gifts():
            current_id = str(
                gift.get("id", "")
            ).strip().lower()

            if current_id == normalized:
                return gift

        return None

    def get_coin_value(
        self,
        gift_id: str,
    ) -> int | None:
        gift = self.find_by_id(gift_id)

        if gift is None:
            return None

        try:
            return int(gift["coins"])
        except (KeyError, TypeError, ValueError):
            return None
