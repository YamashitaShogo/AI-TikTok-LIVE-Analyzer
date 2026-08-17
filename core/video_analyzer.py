from pathlib import Path

import cv2


def extract_frames(
    video_path: str,
    interval_seconds: int = 5,
    max_frames: int = 12,
) -> list[str]:
    """
    動画から一定間隔でフレームを抽出してJPEG保存する。

    Args:
        video_path:
            対象動画のパス

        interval_seconds:
            何秒ごとにフレームを取得するか
            デフォルト: 5秒

        max_frames:
            最大何枚保存するか
            デフォルト: 12枚
            5秒 × 12枚 = 約60秒分

    Returns:
        保存した画像ファイルのパス一覧
    """

    video_path_obj = Path(video_path)

    if not video_path_obj.exists():
        raise FileNotFoundError(
            f"動画ファイルが見つかりません: {video_path_obj}"
        )

    if interval_seconds <= 0:
        raise ValueError("interval_seconds は1以上にしてください")

    cap = cv2.VideoCapture(str(video_path_obj))

    if not cap.isOpened():
        raise RuntimeError(
            f"動画を開けませんでした: {video_path_obj}"
        )

    try:
        fps = cap.get(cv2.CAP_PROP_FPS)

        if fps <= 0:
            raise RuntimeError(
                f"FPSを取得できませんでした: {video_path_obj}"
            )

        total_frames = int(
            cap.get(cv2.CAP_PROP_FRAME_COUNT)
        )

        duration_seconds = (
            total_frames / fps
            if total_frames > 0
            else 0
        )

        print(f"[VideoAnalyzer] video={video_path_obj}")
        print(f"[VideoAnalyzer] fps={fps:.2f}")
        print(f"[VideoAnalyzer] total_frames={total_frames}")
        print(
            f"[VideoAnalyzer] duration="
            f"{duration_seconds:.2f}s"
        )

        output_dir = (
            video_path_obj.parent
            / f"{video_path_obj.stem}_frames"
        )

        output_dir.mkdir(
            parents=True,
            exist_ok=True,
        )

        frame_interval = max(
            1,
            int(round(fps * interval_seconds)),
        )

        saved_paths: list[str] = []

        frame_index = 0
        saved_count = 0

        while True:
            success, frame = cap.read()

            if not success:
                break

            if frame_index % frame_interval == 0:
                elapsed_seconds = frame_index / fps

                output_path = (
                    output_dir
                    / (
                        f"frame_{saved_count:03d}_"
                        f"{elapsed_seconds:06.2f}s.jpg"
                    )
                )

                write_success = cv2.imwrite(
                    str(output_path),
                    frame,
                )

                if not write_success:
                    raise RuntimeError(
                        f"画像保存に失敗しました: "
                        f"{output_path}"
                    )

                saved_paths.append(
                    str(output_path)
                )

                print(
                    f"[VideoAnalyzer] saved "
                    f"{elapsed_seconds:.2f}s "
                    f"-> {output_path}"
                )

                saved_count += 1

                if (
                    max_frames > 0
                    and saved_count >= max_frames
                ):
                    break

            frame_index += 1

        print(
            f"[VideoAnalyzer] "
            f"{len(saved_paths)} frames extracted"
        )

        return saved_paths

    finally:
        cap.release()