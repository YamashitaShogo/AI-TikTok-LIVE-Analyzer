from typing import Any

from core.gift_catalog import GiftCatalog


class GiftCalculator:
    def __init__(self, catalog: GiftCatalog):
        self.catalog = catalog

    def calculate(
        self,
        gift_id: str,
        quantity: int = 1,
    ) -> dict[str, Any]:
        quantity = max(0, int(quantity))

        gift = self.catalog.find_by_id(
            gift_id
        )

        if gift is None:
            return {
                "found": False,
                "gift_id": gift_id,
                "name": None,
                "quantity": quantity,
                "coins_each": None,
                "total_coins": None,
            }

        coins_each = self.catalog.get_coin_value(
            gift_id
        )

        if coins_each is None:
            total_coins = None
        else:
            total_coins = coins_each * quantity

        return {
            "found": True,
            "gift_id": str(
                gift.get("id", gift_id)
            ),
            "name": gift.get("name"),
            "quantity": quantity,
            "coins_each": coins_each,
            "total_coins": total_coins,
        }

    def calculate_many(
        self,
        detections: list[dict[str, Any]],
    ) -> dict[str, Any]:
        items = []
        total_coins = 0
        unknown_count = 0

        for detection in detections:
            result = self.calculate(
                str(
                    detection.get(
                        "gift_id",
                        "",
                    )
                ),
                int(
                    detection.get(
                        "quantity",
                        1,
                    )
                ),
            )

            items.append(result)

            if result["found"] is False:
                unknown_count += 1
                continue

            if result["total_coins"] is not None:
                total_coins += result["total_coins"]

        return {
            "items": items,
            "total_coins": total_coins,
            "unknown_count": unknown_count,
        }
