import argparse
import csv
import json
import re
import statistics
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.ai_client import AIClient
from core.brightness_analyzer import BrightnessAnalyzer
from core.information_analyzer import InformationAnalyzer
from core.hybrid_score_calculator import HybridScoreCalculator
from core.simplified_hybrid_prompt import SIMPLIFIED_HYBRID_PROMPT


ISSUE_NAMES = (
    "subject_boundary_issue",
    "content_obstruction_issue",
    "layout_imbalance",
    "readability_issue",
    "subject_separation_issue",
    "focus_confusion",
)

IMAGE_EXTENSIONS = {
    ".png",
    ".jpg",
    ".jpeg",
    ".webp",
}


def parse_issues(raw_answer: str) -> dict[str, bool]:
    match = re.search(
        r"\{.*\}",
        str(raw_answer),
        flags=re.DOTALL,
    )

    if not match:
        raise ValueError("AI response did not contain JSON.")

    data = json.loads(match.group(0))

    return {
        name: data.get(name) is True
        for name in ISSUE_NAMES
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Validate Livemetry Pulse hybrid scoring."
    )
    parser.add_argument(
        "--images",
        default=str(ROOT / "test_images"),
        help="Directory containing validation images.",
    )
    parser.add_argument(
        "--repeats",
        type=int,
        default=3,
        help="AI analysis repetitions per image.",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=13.0,
        help="Seconds between AI requests.",
    )

    args = parser.parse_args()

    image_dir = Path(args.images).resolve()

    if not image_dir.exists():
        raise FileNotFoundError(
            f"Image directory not found: {image_dir}"
        )

    images = sorted(
        path
        for path in image_dir.rglob("*")
        if path.is_file()
        and path.suffix.lower() in IMAGE_EXTENSIONS
    )

    if not images:
        raise RuntimeError(
            f"No validation images found in {image_dir}"
        )

    repeats = max(1, args.repeats)
    delay = max(0.0, args.delay)

    ai = AIClient()
    rows = []

    request_number = 0
    total_requests = len(images) * repeats

    print(
        f"Images: {len(images)} | "
        f"Repeats: {repeats} | "
        f"AI requests: {total_requests}"
    )
    print()

    for image_index, image_path in enumerate(images, start=1):
        brightness = BrightnessAnalyzer.analyze(
            str(image_path)
        )
        information = InformationAnalyzer.analyze(
            str(image_path)
        )

        image_scores = []
        image_times = []
        issue_counts = {
            name: 0
            for name in ISSUE_NAMES
        }

        print(
            f"=== {image_index}/{len(images)} "
            f"{image_path.name} ==="
        )
        print(
            "Brightness:",
            brightness["score"],
            "| Information:",
            information["score"],
        )

        for run in range(1, repeats + 1):
            request_number += 1

            started_at = time.perf_counter()

            raw_answer = ai.analyze_image(
                str(image_path),
                SIMPLIFIED_HYBRID_PROMPT,
            )

            elapsed = (
                time.perf_counter() - started_at
            )

            issues = parse_issues(raw_answer)

            scores = HybridScoreCalculator.calculate(
                issues,
                brightness_score=brightness["score"],
                information_score=information["score"],
            )

            total_score = scores["total"]

            active_issues = [
                name
                for name, active in issues.items()
                if active
            ]

            for name in active_issues:
                issue_counts[name] += 1

            image_scores.append(total_score)
            image_times.append(elapsed)

            rows.append({
                "image": image_path.name,
                "run": run,
                "total_score": total_score,
                "composition": scores["composition"],
                "brightness": scores["brightness"],
                "visibility": scores["visibility"],
                "information": scores["information"],
                "clarity": scores["clarity"],
                "elapsed_sec": round(elapsed, 2),
                **issues,
            })

            print(
                f"Run {run}: "
                f"score={total_score} "
                f"time={elapsed:.2f}s "
                f"issues={active_issues}"
            )

            if request_number < total_requests:
                time.sleep(delay)

        score_range = (
            max(image_scores) - min(image_scores)
        )

        stability_pass = score_range <= 5

        print(
            "Summary:",
            f"scores={image_scores}",
            f"range={score_range}",
            f"avg_score={statistics.mean(image_scores):.2f}",
            f"avg_time={statistics.mean(image_times):.2f}s",
        )

        print(
            "Stability:",
            "PASS" if stability_pass else "FAIL",
            "(target: range <= 5)",
        )

        print("Issue rates:")

        for name in ISSUE_NAMES:
            rate = (
                issue_counts[name]
                / repeats
                * 100
            )

            print(
                f"  {name}: "
                f"{issue_counts[name]}/{repeats} "
                f"({rate:.0f}%)"
            )

        print()

    output_dir = ROOT / "tests" / "results"
    output_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    timestamp = datetime.now().strftime(
        "%Y%m%d_%H%M%S"
    )

    csv_path = (
        output_dir
        / f"hybrid_validation_{timestamp}.csv"
    )

    fieldnames = [
        "image",
        "run",
        "total_score",
        "composition",
        "brightness",
        "visibility",
        "information",
        "clarity",
        "elapsed_sec",
        *ISSUE_NAMES,
    ]

    with csv_path.open(
        "w",
        newline="",
        encoding="utf-8-sig",
    ) as file:
        writer = csv.DictWriter(
            file,
            fieldnames=fieldnames,
        )
        writer.writeheader()
        writer.writerows(rows)

    print("Validation complete.")
    print("CSV:", csv_path)


if __name__ == "__main__":
    main()