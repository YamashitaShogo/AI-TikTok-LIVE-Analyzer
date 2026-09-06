from typing import Any


GIFT_DETECTION_PROMPT = """
Analyze exactly one livestream screenshot for visible gift events.

Your job is only to detect gifts that are clearly visible in the screenshot.

GENERAL RULES:
- Use only visible evidence in this single screenshot.
- Do not invent gifts.
- Do not infer a gift from unrelated icons, comments, hearts, likes, buttons, or decorations.
- If a gift cannot be identified reliably, use gift_id "unknown".
- If no gift is clearly visible, return an empty detections list.
- quantity means the visible gift count or multiplier shown in the screenshot.
- If no quantity or multiplier is visible, use quantity 1.
- sender_text means the visible sender name or account text clearly associated with that gift event.
- Preserve sender_text as closely as possible to the visible text.
- If the sender cannot be read or cannot be reliably associated with the gift, use null.
- bbox means the approximate bounding box of the entire visible gift event row/card, not only the gift icon.
- bbox format is [x, y, width, height], normalized to the full screenshot from 0.0 to 1.0.
- If a reliable bbox cannot be determined, use null.
- If multiple separate gift events are visible, return one detection object for each event.
- Never guess sender_text or bbox when the visual evidence is unclear.
- confidence must be between 0.0 and 1.0.
- Do not estimate coin values.
- Do not calculate totals.
- Coin values are handled separately by Python.
- Do not give advice.
- Do not explain reasoning.
- Return JSON only.
"""


def build_gift_detection_prompt(
    gifts: list[dict[str, Any]],
) -> str:
    catalog_lines: list[str] = []

    for gift in gifts:
        gift_id = str(
            gift.get("id", "")
        ).strip()

        name = str(
            gift.get("name", "")
        ).strip()

        if not gift_id:
            continue

        if name:
            catalog_lines.append(
                f"- gift_id: {gift_id} | name: {name}"
            )
        else:
            catalog_lines.append(
                f"- gift_id: {gift_id}"
            )

    if catalog_lines:
        catalog_text = "\n".join(
            catalog_lines
        )
    else:
        catalog_text = (
            "- No known gifts are currently registered."
        )

    return (
        GIFT_DETECTION_PROMPT
        + """

CATALOG RULES:
- The catalog below is the only list of known gift IDs.
- If a visible gift clearly matches a catalog entry, return that exact gift_id.
- Never use a display name as gift_id unless it is also the exact catalog ID.
- Never create a new gift_id.
- If the visible gift does not reliably match a catalog entry, use "unknown".
- Do not infer coin values from the catalog.

KNOWN GIFT CATALOG:
"""
        + catalog_text
        + """

Return exactly this structure:

{
  "detections": [
    {
      "gift_id": "unknown",
      "quantity": 1,
      "sender_text": null,
      "bbox": null,
      "confidence": 0.0
    }
  ]
}

If no gift is visible, return:

{
  "detections": []
}
"""
    )
