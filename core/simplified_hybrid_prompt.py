SIMPLIFIED_HYBRID_PROMPT = """
Analyze one livestream screenshot.

Detect only clearly visible problems.

Use only visible evidence from the screenshot.
If a problem is uncertain, borderline, or weak, use false.

Brightness and screen information density are measured separately by Python.
Do not judge brightness, exposure, or the amount of information on screen.

Do not give scores.
Do not give advice.
Do not explain reasoning.
Return JSON only.

subject_boundary_issue:
The main subject or an important visual element is clearly too close
to the image boundary or is noticeably cut off in a way that weakens
the presentation.

content_obstruction_issue:
A visible UI element or other visible object clearly covers or obstructs
important content.

layout_imbalance:
The overall visual layout is clearly unbalanced and this is not already
explained by subject_boundary_issue or content_obstruction_issue.

readability_issue:
Important visible text or content is clearly difficult to read or recognize.

subject_separation_issue:
The main subject is clearly difficult to distinguish from the background.

focus_confusion:
It is clearly difficult to determine what the viewer should focus on first
because prominent elements compete for attention or the visual purpose is unclear.

Return exactly:

{
  "subject_boundary_issue": false,
  "content_obstruction_issue": false,
  "layout_imbalance": false,
  "readability_issue": false,
  "subject_separation_issue": false,
  "focus_confusion": false
}
"""
