SIMPLIFIED_HYBRID_PROMPT = """
Analyze exactly one livestream screenshot.

Your task is to detect only clear, substantial visual problems.

IMPORTANT GENERAL RULES:
- Use only visible evidence in this single screenshot.
- Be conservative.
- If a problem is uncertain, minor, subjective, borderline, or merely stylistic, use false.
- A normal livestream UI, comments, icons, buttons, counters, or decorative overlays are NOT problems by themselves.
- Do not mark multiple issues for the same visual condition unless each issue is independently and clearly present.
- Brightness, exposure, darkness, and screen information density are evaluated separately by Python.
- Do not use darkness or high information density as reasons to set any flag to true.

Do not give scores.
Do not give advice.
Do not explain reasoning.
Return JSON only.

subject_boundary_issue:
Judge this issue using geometry and framing only.
Ignore brightness, darkness, contrast, colors, and information density.

True when the main subject or an important visual element is visibly clipped
by the left, right, top, or bottom image boundary in a way that weakens
the presentation.

Examples that should usually be true:
- a noticeable part of the main subject's head, hair, face, or upper body
  exits the left or right edge,
- an important product or visual element is visibly cut by the image edge,
- the main subject is pressed against an edge with clearly insufficient space.

Do NOT mark true merely because:
- the subject is not perfectly centered,
- normal portrait framing crops lower or unimportant body areas,
- there is slightly less space on one side,
- the image is dark or bright.

For two screenshots with the same subject position and crop,
the subject_boundary_issue result should remain the same even if brightness differs.

content_obstruction_issue:
True only when a visible UI element, overlay, object, or foreground element
substantially covers important content such as:
- the main subject's face,
- a featured product,
- essential text,
- another clearly important visual element.

Do NOT mark true merely because:
- comments or livestream UI are visible,
- UI overlaps background or nonessential areas,
- an overlay is close to the subject,
- the screen contains many interface elements.

If the important content remains clearly visible and understandable,
content_obstruction_issue must be false.

layout_imbalance:
True only when the overall placement of major visual elements is clearly awkward
or strongly unbalanced enough to harm the presentation.

Do NOT mark true merely because:
- the composition is asymmetric,
- the subject is off-center,
- livestream UI exists,
- subject_boundary_issue already explains the visible problem.

readability_issue:
True only when important text or important visual content is genuinely difficult
to read or recognize because of overlap, very poor contrast, extreme smallness,
blur, or another clear local visibility problem.

Do NOT mark true merely because:
- the whole image is dark,
- there is lots of text or UI,
- some secondary comments are small,
- the content is still recognizable with normal viewing effort.

Global brightness is handled separately by Python.

subject_separation_issue:
True only when the main subject is genuinely difficult to distinguish from
the background because the subject and background visually merge.

Do NOT mark true merely because:
- the background is busy,
- the colors are similar but the subject remains clearly recognizable,
- the image is globally dark.

focus_confusion:
True only when two or more major visual elements compete so strongly that it is
genuinely unclear what the viewer should look at first.

Do NOT mark true merely because:
- livestream comments or UI are present,
- the screen contains multiple secondary elements,
- there is high information density,
- the main subject is still visually obvious.

Return exactly this JSON structure:

{
  "subject_boundary_issue": false,
  "content_obstruction_issue": false,
  "layout_imbalance": false,
  "readability_issue": false,
  "subject_separation_issue": false,
  "focus_confusion": false
}
"""