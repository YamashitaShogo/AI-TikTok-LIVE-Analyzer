import argparse
import csv
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(
        0,
        str(PROJECT_ROOT),
    )

from core.gift_analyzer import GiftAnalyzer


ROOT = Path(__file__).resolve().parent
IMAGE_DIR = ROOT / "images"
LABELS_PATH = ROOT / "labels.csv"
RESULTS_DIR = ROOT / "results"

CATALOG_PATH = (
    ROOT.parent.parent
    / "data"
    / "gifts"
    / "gift_catalog.json"
)


def parse_bool(value: str) -> bool:
    return value.strip().lower() in {
        "1",
        "true",
        "yes",
        "y",
    }


def load_labels():
    with LABELS_PATH.open(
        "r",
        encoding="utf-8-sig",
        newline="",
    ) as file:
        return list(
            csv.DictReader(file)
        )


def find_image(name: str):
    direct = IMAGE_DIR / name

    if direct.exists():
        return direct

    matches = list(
        IMAGE_DIR.rglob(name)
    )

    if len(matches) == 1:
        return matches[0]

    return None


def validate_case(
    analyzer,
    row,
):
    image_name = row["image"].strip()
    expected_visible = parse_bool(
        row["gift_visible"]
    )
    expected_gift_id = row[
        "expected_gift_id"
    ].strip()
    expected_quantity_text = row[
        "expected_quantity"
    ].strip()

    expected_quantity = (
        int(expected_quantity_text)
        if expected_quantity_text
        else None
    )

    image_path = find_image(
        image_name
    )

    if image_path is None:
        return {
            "image": image_name,
            "pass": False,
            "reason": "画像が見つかりません",
        }

    result = analyzer.analyze_image(
        image_path
    )

    accepted = result.get(
        "accepted_detections",
        [],
    )

    if not expected_visible:
        passed = len(accepted) == 0

        return {
            "image": image_name,
            "pass": passed,
            "reason": (
                "ギフトなし判定OK"
                if passed
                else f"誤検出: {accepted}"
            ),
        }

    matching = [
        item
        for item in accepted
        if item.get("gift_id")
        == expected_gift_id
    ]

    if not matching:
        return {
            "image": image_name,
            "pass": False,
            "reason": (
                "期待IDなし "
                f"expected={expected_gift_id} "
                f"actual={accepted}"
            ),
        }

    if expected_quantity is not None:
        quantity_ok = any(
            int(
                item.get(
                    "quantity",
                    1,
                )
            )
            == expected_quantity
            for item in matching
        )

        if not quantity_ok:
            return {
                "image": image_name,
                "pass": False,
                "reason": (
                    "数量不一致 "
                    f"expected={expected_quantity} "
                    f"actual={matching}"
                ),
            }

    return {
        "image": image_name,
        "pass": True,
        "reason": "ID・数量ともにOK",
    }


def main():
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--delay",
        type=float,
        default=13.0,
        help=(
            "AIリクエスト間の待機秒数。"
            "デフォルト13秒。"
        ),
    )

    args = parser.parse_args()

    rows = load_labels()

    rows = [
        row
        for row in rows
        if row.get(
            "image",
            "",
        ).strip()
    ]

    if not rows:
        print(
            "検証対象がありません。"
            "labels.csv にデータを追加してください。"
        )
        return

    analyzer = GiftAnalyzer(
        catalog_path=CATALOG_PATH,
        history_db=None,
    )

    results = []

    for index, row in enumerate(
        rows,
        start=1,
    ):
        print(
            f"[{index}/{len(rows)}] "
            f"{row['image']} を分析中..."
        )

        try:
            result = validate_case(
                analyzer,
                row,
            )

        except Exception as exc:
            result = {
                "image": row["image"],
                "pass": False,
                "reason": f"ERROR: {exc}",
            }

        results.append(
            result
        )

        status = (
            "PASS"
            if result["pass"]
            else "FAIL"
        )

        print(
            f"  {status}: "
            f"{result['reason']}"
        )

        if (
            index < len(rows)
            and args.delay > 0
        ):
            time.sleep(
                args.delay
            )

    passed = sum(
        1
        for result in results
        if result["pass"]
    )

    total = len(
        results
    )

    accuracy = (
        passed / total * 100
        if total
        else 0.0
    )

    RESULTS_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    timestamp = time.strftime(
        "%Y%m%d-%H%M%S"
    )

    result_path = (
        RESULTS_DIR
        / f"gift_validation_{timestamp}.csv"
    )

    with result_path.open(
        "w",
        encoding="utf-8-sig",
        newline="",
    ) as file:
        writer = csv.DictWriter(
            file,
            fieldnames=[
                "image",
                "pass",
                "reason",
            ],
        )

        writer.writeheader()
        writer.writerows(
            results
        )

    print()
    print("=" * 50)
    print(
        f"PASS = {passed}/{total}"
    )
    print(
        f"CASE ACCURACY = {accuracy:.1f}%"
    )
    print(
        f"RESULT CSV = {result_path}"
    )
    print("=" * 50)


if __name__ == "__main__":
    main()
