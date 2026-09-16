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
        is_black_screen: bool = False,
    ) -> str:
        if is_black_screen:
            return (
                "\u3010\u72b6\u614b\u3011\n"
                "\u6620\u50cf\u304c\u307b\u307c\u5b8c\u5168\u306a\u9ed2\u753b\u9762\u306e\u305f\u3081\u3001"
                "\u901a\u5e38\u306e\u914d\u4fe1\u5206\u6790\u3092\u884c\u3048\u307e\u305b\u3093\u3002\n\n"
                "\u3010\u6539\u5584\u70b9\u3011\n"
                "OBS\u306e\u30b7\u30fc\u30f3\u3001\u6620\u50cf\u30bd\u30fc\u30b9\u3001"
                "\u30ad\u30e3\u30d7\u30c1\u30e3\u5bfe\u8c61\u304c\u6b63\u3057\u304f"
                "\u8868\u793a\u3055\u308c\u3066\u3044\u308b\u304b\u78ba\u8a8d\u3057\u3066\u304f\u3060\u3055\u3044\u3002\n\n"
                "\u3010\u3059\u3050\u5b9f\u884c\u3067\u304d\u308b\u6539\u5584\u6848\u3011\n"
                "OBS\u306e\u30d7\u30ec\u30d3\u30e5\u30fc\u753b\u9762\u3092\u78ba\u8a8d\u3057\u3001"
                "\u6620\u50cf\u30bd\u30fc\u30b9\u304c\u975e\u8868\u793a\u30fb\u505c\u6b62\u30fb"
                "\u53d6\u5f97\u5931\u6557\u306b\u306a\u3063\u3066\u3044\u306a\u3044\u304b"
                "\u78ba\u8a8d\u3057\u3066\u304f\u3060\u3055\u3044\u3002"
            )

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

        if brightness_score <= 12:
            good_point = (
                "配信画面の主要な内容は"
                "認識できますが、"
                "全体的にかなり暗めです。"
            )
        else:
            good_point = (
                "配信画面の主要な内容は"
                "認識できます。"
            )

        lines = [
            "【良い点】",
            good_point,
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
