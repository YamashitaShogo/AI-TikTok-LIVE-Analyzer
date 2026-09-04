from typing import Dict


class HybridScoreCalculator:
    """
    Stable hybrid scoring engine for Livemetry Pulse.

    AI handles a small number of semantic visual issues.
    Python handles brightness, information density, and final scoring.
    """

    MAX_SCORES = {
        "composition": 25,
        "brightness": 20,
        "visibility": 20,
        "information": 15,
        "clarity": 20,
    }

    AI_DEDUCTIONS = {
        # Composition
        "subject_boundary_issue": ("composition", 4),
        "content_obstruction_issue": ("composition", 2),
        "layout_imbalance": ("composition", 2),

        # Visibility
        "readability_issue": ("visibility", 2),
        "subject_separation_issue": ("visibility", 2),

        # Clarity
        "focus_confusion": ("clarity", 3),
    }

    @classmethod
    def calculate(
        cls,
        issues: Dict[str, bool],
        brightness_score: int,
        information_score: int,
    ) -> Dict[str, int]:

        scores = cls.MAX_SCORES.copy()

        for issue_name, active in issues.items():
            if active is not True:
                continue

            deduction = cls.AI_DEDUCTIONS.get(issue_name)

            if deduction is None:
                continue

            category, points = deduction

            scores[category] = max(
                0,
                scores[category] - points,
            )

        scores["brightness"] = max(
            0,
            min(
                20,
                int(brightness_score),
            ),
        )

        scores["information"] = max(
            0,
            min(
                15,
                int(information_score),
            ),
        )

        scores["total"] = sum(scores.values())

        return scores
