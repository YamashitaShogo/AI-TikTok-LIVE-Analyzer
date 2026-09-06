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
- confidence must be between 0.0 and 1.0.
- Do not estimate coin values.
- Do not calculate totals.
- Coin values are handled separately by Python.
- Do not give advice.
- Do not explain reasoning.
- Return JSON only.

Return exactly this structure:

{
  "detections": [
    {
      "gift_id": "unknown",
      "quantity": 1,
      "confidence": 0.0
    }
  ]
}

If no gift is visible, return:

{
  "detections": []
}
"""
