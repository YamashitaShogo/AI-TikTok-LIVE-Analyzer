SIMPLIFIED_HYBRID_PROMPT = """
Analyze exactly one livestream screenshot.

Your task has two parts:

1. Detect six clear visual issue flags.
2. Give three short, image-specific explanations for the streamer.

IMPORTANT GENERAL RULES:
- Use only visible evidence in this single screenshot.
- Be evidence-based and strict about presentation quality.
- Do not invent objects, people, text, causes, or conditions that are not visible.
- Do not treat a screen as excellent merely because it has no catastrophic problem.
- Mark an issue true when it is clearly noticeable and meaningfully reduces visual polish, framing quality, usability, or viewer focus.
- If a problem is genuinely uncertain, subjective, or only borderline, use false.
- Platform-owned interface elements are outside the streamer's control and must not reduce the evaluation.
- Ignore TikTok native chat panels, comment columns, comment messages, usernames, reaction icons, gift notifications, gift animations, gift effects, animated gifts, ranking displays, buttons, counters, navigation, side gutters, black bars, margins, and desktop-page layout.
- TikTok-native elements remain outside the evaluation even when they appear on top of or inside the visible livestream video area.
- TikTok's native comment area must never be treated as visual clutter, excessive UI, focus competition, wasted space, content obstruction, or layout imbalance.
- Judge composition, subject scale, dead space, visibility, and visual hierarchy primarily inside the actual livestream video content.
- Only evaluate UI or overlays negatively when they are clearly part of the streamer's own video or OBS composition.
- Do not mark multiple issues for the same visual condition unless each issue is independently and clearly present.
- Global brightness, exposure, darkness, and screen information density are evaluated separately by Python.
- Do not use global darkness or high information density as reasons to set any of the six issue flags to true.
- You may mention clearly visible local lighting relationships in the explanation, such as the subject being darker than the background.
- Do not give a score.
- Do not estimate numerical brightness, contrast, exposure, or confidence values.
- Return JSON only.

FLAG DEFINITIONS:

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

content_obstruction_issue:
True only when an element controlled by the streamer or included in the
streamer's own OBS/video composition substantially covers important content
such as:
- the main subject's face,
- a featured product,
- essential text,
- another clearly important visual element.

Do NOT mark true merely because:
- TikTok native comments, gift animations, gift effects, reactions, or livestream UI are visible,
- the streamer temporarily moves a hand or a held object in front of part of their face during a normal action,
- UI overlaps background or nonessential areas,
- an overlay is close to the subject,
- the screen contains many interface elements.

layout_imbalance:
True when the placement of major visual elements is noticeably unbalanced,
wastes a meaningful amount of usable space, or reduces the overall polish
of the presentation.

Do NOT mark true merely because:
- the composition is asymmetric,
- the subject is off-center,
- livestream UI exists,
- subject_boundary_issue already explains the visible problem.

readability_issue:
True only when important text or important visual content is genuinely difficult
to read or recognize because of overlap, very poor local contrast,
extreme smallness, blur, or another clear local visibility problem.

Do NOT mark true merely because:
- the whole image is dark,
- there is lots of text or UI,
- some secondary comments are small,
- the content is still recognizable with normal viewing effort.

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

excessive_dead_space:
True when a large part of the actual livestream video content controlled by
the streamer is visibly unused or visually empty in a way that materially
weakens the presentation.

Never count TikTok native comments, platform side areas, margins, gutters,
black bars, or desktop-page layout as dead space.

Examples:
- a narrow portrait video is placed inside a much wider canvas and leaves
  very large unused regions,
- the main content occupies only a limited central area while substantial
  empty side regions remain.

Do NOT mark true merely because:
- there is normal breathing room around the subject,
- the composition intentionally uses modest negative space,
- a small margin exists around a portrait crop.

subject_scale_issue:
True when the main subject is clearly too large or too small for the available
frame in a way that harms presentation.

Examples:
- the face or upper body fills so much of the frame that the composition feels
  cramped even though it is not technically clipped,
- the main subject is so small that large areas of the frame contribute little.

Do NOT mark true for ordinary close-up livestream framing.

ui_dominance_issue:
True only when UI, text, panels, or overlays that are part of the streamer's
own video or OBS composition occupy so much visual attention that they compete
with the main stream content.

TikTok native comments, chat panels, reaction icons, gift notifications,
gift animations, gift effects, ranking displays, buttons, and platform
interface must never trigger this issue, even when they overlap the video.

Do NOT mark true merely because:
- comments are visible,
- a normal chat panel is present,
- TikTok interface elements are visible.

EXPLANATION FIELDS:

visual_observation:
- Write in natural Japanese.
- Describe what is actually visible in this screenshot.
- Be specific to this image.
- Prefer one or two concise sentences.
- Mention the subject, background, framing, important object, overlay,
  or local lighting relationship when relevant.
- Do not simply repeat the boolean flag names.

main_reason:
- Write in natural Japanese.
- Explain why the most important visible condition matters to viewers.
- Use concrete relationships visible in the image.
- Do not invent viewer reactions.
- If visible weaknesses exist, state them clearly instead of softening
  the evaluation.
- Only describe the presentation as stable when there is no meaningful
  visible weakness.

priority_action:
- Write in natural Japanese.
- Give exactly one practical highest-priority action.
- Make it concrete enough that the streamer can act on it.
- Do not give a list of unrelated actions.
- If no meaningful change is needed, say that the current presentation
  can be maintained.

Return exactly this JSON structure:

{
  "subject_boundary_issue": false,
  "content_obstruction_issue": false,
  "layout_imbalance": false,
  "readability_issue": false,
  "subject_separation_issue": false,
  "focus_confusion": false,
  "excessive_dead_space": false,
  "subject_scale_issue": false,
  "ui_dominance_issue": false,
  "visual_observation": "",
  "main_reason": "",
  "priority_action": ""
}
"""
