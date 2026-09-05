from typing import Dict


class HybridAnalysisFormatter:
    """
    Build stable Japanese advice from hybrid analysis results.
    """

    ISSUE_MESSAGES = {
        "subject_boundary_issue": (
            "被写体が画面端に寄っている、または一部が切れています。"
            "少し中央へ寄せるか、カメラを引いて余白を確保してください。"
        ),
        "content_obstruction_issue": (
            "UIやコメント表示が重要な内容に重なっています。"
            "表示位置やサイズを調整して、顔や重要部分を隠さないようにしてください。"
        ),
        "layout_imbalance": (
            "画面全体の配置バランスに偏りがあります。"
            "被写体や主要要素の位置を少し調整すると見やすくなります。"
        ),
        "readability_issue": (
            "一部の文字や表示が読み取りにくくなっています。"
            "文字サイズや背景、表示位置を調整してください。"
        ),
        "subject_separation_issue": (
            "被写体と背景の区別がやや分かりにくくなっています。"
            "背景との距離や照明、構図を調整すると改善できます。"
        ),
        "focus_confusion": (
            "視線を向ける場所が分散しています。"
            "重要な要素を1つ目立たせ、その他の表示を少し抑えてください。"
        ),
    }

    @classmethod
    def format(
        cls,
        issues: Dict[str, bool],
        brightness_score: int,
        information_score: int,
    ) -> str:
        improvements = []

        for issue_name, message in cls.ISSUE_MESSAGES.items():
            if issues.get(issue_name) is True:
                improvements.append(message)

        if brightness_score <= 12:
            improvements.append(
                "画面がかなり暗めです。"
                "照明を追加するか、カメラやOBS側の明るさを調整してください。"
            )
        elif brightness_score <= 17:
            improvements.append(
                "画面が少し暗めです。"
                "顔や主役部分をもう少し明るくすると見やすくなります。"
            )

        if information_score <= 11:
            improvements.append(
                "画面上の情報量が多くなっています。"
                "重要度の低いUIや表示を減らしてください。"
            )
        elif information_score <= 13:
            improvements.append(
                "画面上の情報がやや多めです。"
                "重要な表示を優先すると、より見やすくなります。"
            )

        if not improvements:
            return (
                "【良い点】\n"
                "大きな視覚上の問題は検出されませんでした。\n\n"
                "【改善点】\n"
                "現在の構成を維持しながら、配信中の変化を確認してください。"
            )

        lines = [
            "【良い点】",
            "配信画面の主要な内容は認識できます。",
            "",
            "【改善点】",
        ]

        for index, message in enumerate(improvements, start=1):
            lines.append(f"{index}. {message}")

        lines.extend([
            "",
            "【すぐ実行できる改善案】",
            improvements[0],
        ])

        return "\n".join(lines)
