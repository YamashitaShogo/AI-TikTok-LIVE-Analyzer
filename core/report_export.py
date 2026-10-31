"""Exports for the unattended observation report: JSON / CSV / PDF.

JSON carries the report dict unchanged (it already has a schema
version). CSV is a per-battle table readable in Excel. PDF is the
sales-facing document built with reportlab, which is already a build
dependency of Livemetry Pulse (requirements-build.txt) and already
used by the history page, so no new dependency is introduced.

Unknown values are exported as blanks / '未取得', never as 0.
"""
import csv
import json
import tempfile
from pathlib import Path

try:
    from .observation_sessions import format_jst
    from .settings import replace_with_retry
except ImportError:
    from observation_sessions import format_jst
    from settings import replace_with_retry


def export_json(report, destination):
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False)
    fd_path = None
    try:
        import os
        fd, fd_path = tempfile.mkstemp(dir=destination.parent, suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
        # Same transient-lock retry as settings writes: a report file
        # momentarily open in another app must not silently lose the
        # (best-effort) auto-generated JSON on Windows.
        replace_with_retry(fd_path, destination)
        fd_path = None
    finally:
        if fd_path and Path(fd_path).exists():
            Path(fd_path).unlink()
    return destination


CSV_COLUMNS = [
    ("nickname", "配信者"),
    ("unique_id", "配信者ID"),
    ("battle_id", "バトルID"),
    ("mode", "形式"),
    ("status_label", "終了状態"),
    ("first_seen_jst", "最初の記録（JST）"),
    ("partial_state", "観測の完全性"),
    ("final_score", "最終スコア"),
    ("last_known_score", "最新の確認スコア（参考・終了未確認時のみ）"),
    ("score_state", "スコア取得"),
    ("score_sample_count", "スコア記録回数"),
    ("viewer_median", "視聴者数中央値"),
    ("viewer_peak", "視聴者数最大"),
    ("viewer_sample_count", "視聴者数記録回数"),
]

_PARTIAL_LABELS = {"full": "開始から観測", "partial": "途中から観測", "unknown": "判定不可"}


def export_csv(report, destination):
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    # Write to a temp file and replace, like export_json: a failure
    # mid-write must not leave a truncated CSV at the destination.
    import os
    fd, fd_path = tempfile.mkstemp(dir=destination.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8-sig", newline="") as handle:
            _write_csv(report, handle)
        replace_with_retry(fd_path, destination)
        fd_path = None
    finally:
        if fd_path and Path(fd_path).exists():
            Path(fd_path).unlink()
    return destination


def _write_csv(report, handle):
    if True:
        writer = csv.writer(handle)
        writer.writerow([label for _, label in CSV_COLUMNS])
        for battle in report.get("battles", []):
            row = []
            for key, _ in CSV_COLUMNS:
                if key == "partial_state":
                    row.append(_PARTIAL_LABELS.get(battle.get(key), "判定不可"))
                elif key == "score_state":
                    if battle.get("score_known"):
                        row.append("取得済み")
                    elif battle.get("last_known_score") is not None:
                        row.append("参考値あり（終了未確認）")
                    else:
                        row.append("未取得")
                elif key == "final_score":
                    row.append(battle.get("final_score") if battle.get("score_known") else "")
                elif key == "last_known_score":
                    row.append("" if battle.get("finished_confirmed")
                               else (battle.get("last_known_score")
                                     if battle.get("last_known_score") is not None else ""))
                else:
                    value = battle.get(key)
                    row.append("" if value is None else value)
            writer.writerow(row)


# ------------------------------------------------------------------ charts
def make_series_chart(points, path, title, color="#367dcc"):
    """Small PIL line chart. None values break the line (no bridging)."""
    from PIL import Image, ImageDraw
    width, height = 960, 420
    image = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)
    left, top, right, bottom = 80, 50, 930, 360
    draw.text((30, 15), title, fill="black")
    known = [p for p in points if p.get("v") is not None]
    if not known:
        draw.text((left, top + 40), "no data", fill="#888888")
        image.save(path)
        return path
    t0, t1 = points[0]["t"], points[-1]["t"]
    vmax = max(p["v"] for p in known) or 1
    span = max(1.0, t1 - t0)
    draw.line((left, top, left, bottom), fill="#999999")
    draw.line((left, bottom, right, bottom), fill="#999999")
    for frac in (0, 0.5, 1.0):
        y = bottom - (bottom - top) * frac
        draw.line((left, y, right, y), fill="#e5e5e5")
        draw.text((8, y - 6), str(int(vmax * frac)), fill="black")

    def xy(point):
        x = left + (right - left) * (point["t"] - t0) / span
        y = bottom - (bottom - top) * (point["v"] / vmax)
        return x, y

    previous = None
    for point in points:
        if point.get("v") is None:
            previous = None
            continue
        current = xy(point)
        if previous is not None:
            draw.line((*previous, *current), fill=color, width=2)
        previous = current
    draw.text((left, bottom + 12), format_jst(t0), fill="black")
    end_label = format_jst(t1)
    draw.text((right - 9 * len(end_label), bottom + 12), end_label, fill="black")
    image.save(path)
    return path


# --------------------------------------------------------------------- PDF
def _register_japanese_font(pdfmetrics, TTFont):
    """Same font candidates as ui/pages/history.py, CID fallback."""
    candidates = [
        Path(r"C:\Windows\Fonts\YuGothR.ttc"),
        Path(r"C:\Windows\Fonts\YuGothM.ttc"),
        Path(r"C:\Windows\Fonts\msgothic.ttc"),
        Path(r"C:\Windows\Fonts\meiryo.ttc"),
    ]
    for candidate in candidates:
        if candidate.exists():
            try:
                pdfmetrics.registerFont(TTFont("LivemetryJP", str(candidate)))
                return "LivemetryJP"
            except Exception:
                continue
    try:
        from reportlab.pdfbase.cidfonts import UnicodeCIDFont
        pdfmetrics.registerFont(UnicodeCIDFont("HeiseiKakuGo-W5"))
        return "HeiseiKakuGo-W5"
    except Exception:
        return "Helvetica"


def _fmt(value, suffix=""):
    return "未取得" if value is None else f"{value:,}{suffix}" if isinstance(value, (int, float)) else str(value)


def export_pdf(report, destination, ai_text=None):
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_CENTER
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.platypus import (Image, PageBreak, Paragraph, SimpleDocTemplate,
                                    Spacer, Table, TableStyle)

    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    font = _register_japanese_font(pdfmetrics, TTFont)
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle("JPTitle", parent=styles["Title"], fontName=font,
                                 fontSize=22, leading=28, alignment=TA_CENTER, spaceAfter=8 * mm)
    heading = ParagraphStyle("JPHeading", parent=styles["Heading2"], fontName=font,
                             fontSize=14, leading=19, spaceBefore=5 * mm, spaceAfter=3 * mm)
    body = ParagraphStyle("JPBody", parent=styles["BodyText"], fontName=font,
                          fontSize=9.5, leading=14, wordWrap="CJK")
    small = ParagraphStyle("JPSmall", parent=body, fontSize=8.5, leading=12)

    summary = report.get("summary") or {}
    session = report.get("session") or {}
    targets = ", ".join("@" + t for t in (session.get("targets") or [])) or "指定なし（期間内の全記録）"
    story = [
        Spacer(1, 30 * mm),
        Paragraph("Livemetry Pulse", title_style),
        Paragraph("無人観測レポート", title_style),
        Spacer(1, 10 * mm),
        Paragraph(f"レポート対象: {targets}", body),
        Paragraph(f"観測期間: {summary.get('window_start_jst', '指定なし')} 〜 {summary.get('window_end_jst', '指定なし')}", body),
        Paragraph(f"生成日時: {report.get('generated_jst', '')}", body),
        Paragraph(f"データ種別: {report.get('profile', '')}", body),
        PageBreak(),
        Paragraph("1. 今回の観測概要", heading),
    ]
    overview_rows = [
        ["観測時間", f"{int((summary.get('observed_seconds') or 0) // 3600)}時間"
                      f"{int(((summary.get('observed_seconds') or 0) % 3600) // 60)}分"
                      "（配信時間ではありません）"],
        ["観測対象数", _fmt(summary.get("streamer_count"))],
        ["記録バトル数", _fmt(summary.get("record_count"))],
        ["ユニークバトル数", _fmt(summary.get("unique_battle_count"))],
        ["正常終了が確認できたバトル", _fmt(summary.get("finished_confirmed"))],
        ["中断・終了未確認バトル", _fmt(summary.get("unfinished"))],
        ["スコア取得済みバトル", _fmt(summary.get("score_known_battles"))],
        ["スコア未取得バトル", _fmt(summary.get("score_unknown_battles"))],
        ["スコア中央値", _fmt(summary.get("final_score_median"))],
        ["最大確認スコア", _fmt(summary.get("final_score_max"))],
        ["視聴者数の中央値", _fmt(summary.get("viewer_median"))],
        ["最大確認視聴者数", _fmt(summary.get("viewer_peak_max"))],
        ["途中から観測したバトル", _fmt(summary.get("partial_battles"))],
    ]
    table = Table([[Paragraph(a, body), Paragraph(b, body)] for a, b in overview_rows],
                  colWidths=[55 * mm, 115 * mm])
    table.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), font),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#cccccc")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    story += [table, Paragraph("2. バトル成績", heading)]
    battles = report.get("battles", [])
    if battles:
        header = ["配信者", "開始（JST）", "状態", "最終スコア", "視聴者中央値", "視聴者最大"]
        rows = [[Paragraph(h, small) for h in header]]
        for battle in battles[:100]:
            if battle.get("score_known"):
                score_cell = _fmt(battle.get("final_score"))
            elif battle.get("last_known_score") is not None:
                # Not a final score: the battle's end was never confirmed.
                score_cell = f"{battle['last_known_score']:,}（参考・終了未確認）"
            else:
                score_cell = "未取得"
            rows.append([
                Paragraph(str(battle.get("nickname") or battle.get("unique_id")), small),
                Paragraph(str(battle.get("first_seen_jst") or ""), small),
                Paragraph(str(battle.get("status_label") or ""), small),
                Paragraph(score_cell, small),
                Paragraph(_fmt(battle.get("viewer_median")), small),
                Paragraph(_fmt(battle.get("viewer_peak")), small),
            ])
        battle_table = Table(rows, colWidths=[38 * mm, 32 * mm, 28 * mm, 26 * mm, 24 * mm, 22 * mm],
                             repeatRows=1)
        battle_table.setStyle(TableStyle([
            ("FONTNAME", (0, 0), (-1, -1), font),
            ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#cccccc")),
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eef2f7")),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ]))
        story.append(battle_table)
        if len(battles) > 100:
            story.append(Paragraph(f"（表は先頭100件のみ。全{len(battles)}件はCSV/JSONに収録）", small))
    else:
        story.append(Paragraph("記録されたバトルはありません（データなし）。", body))

    story.append(Paragraph("3. 視聴者数推移", heading))
    representative = max(battles, key=lambda b: b.get("viewer_sample_count") or 0, default=None)
    if representative and representative.get("viewer_series"):
        with tempfile.TemporaryDirectory(prefix="pulse_report_") as tmp:
            chart = make_series_chart(representative["viewer_series"],
                                      Path(tmp) / "viewers.png",
                                      "viewers (representative battle)")
            story.append(Image(str(chart), width=170 * mm, height=74 * mm))
        story.append(Paragraph(
            f"代表バトル: {representative.get('nickname')}（視聴者サンプル数が最多のバトル）。"
            "記録のない区間は線を引いていません。", small))
    else:
        story.append(Paragraph("視聴者数の記録がありません（未取得）。", body))

    comparison = report.get("comparison")
    story.append(Paragraph("4. 前回との比較", heading))
    if comparison and comparison.get("rows"):
        rows = [[Paragraph(h, small) for h in ("指標", "前回", "今回", "差")]]
        for row in comparison["rows"]:
            delta = "比較不可" if not row["comparable"] else (
                f"{row['delta']:+,}" if isinstance(row["delta"], (int, float)) else "比較不可")
            rows.append([Paragraph(row["label"], small), Paragraph(_fmt(row["previous"]), small),
                         Paragraph(_fmt(row["current"]), small), Paragraph(delta, small)])
        comp_table = Table(rows, colWidths=[55 * mm, 38 * mm, 38 * mm, 39 * mm], repeatRows=1)
        comp_table.setStyle(TableStyle([
            ("FONTNAME", (0, 0), (-1, -1), font),
            ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#cccccc")),
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eef2f7")),
        ]))
        story.append(comp_table)
    else:
        story.append(Paragraph("比較できる前回レポートがありません。", body))

    if ai_text:
        story.append(Paragraph("5. AI分析・改善仮説", heading))
        for paragraph in str(ai_text).split("\n"):
            story.append(Paragraph(paragraph.replace("&", "&amp;").replace("<", "&lt;") or " ", body))

    story.append(Paragraph("6. データの取得条件・注意事項", heading))
    for note in report.get("data_notes", []):
        story.append(Paragraph("・" + note, body))
    for key, text in (report.get("definitions") or {}).items():
        story.append(Paragraph(f"・{key}: {text}", small))
    story.append(Paragraph(
        "本レポートは Livemetry Pulse が観測できた範囲の記録に基づきます。"
        "TikTok 公式サービスとの提携・認可を示すものではありません。", small))

    # Build into a temp file and replace, like the other exports: a
    # failure mid-build must not leave a truncated PDF behind.
    import os
    destination = Path(destination)
    fd, fd_path = tempfile.mkstemp(dir=destination.parent, suffix=".tmp")
    os.close(fd)
    try:
        doc = SimpleDocTemplate(str(fd_path), pagesize=A4,
                                leftMargin=20 * mm, rightMargin=20 * mm,
                                topMargin=18 * mm, bottomMargin=18 * mm,
                                title="Livemetry Pulse 無人観測レポート")
        doc.build(story)
        replace_with_retry(fd_path, destination)
        fd_path = None
    finally:
        if fd_path and Path(fd_path).exists():
            Path(fd_path).unlink()
    return destination
