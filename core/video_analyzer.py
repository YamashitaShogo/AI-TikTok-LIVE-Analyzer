from math import ceil
from pathlib import Path

import cv2


def extract_frames(
    video_path: str,
    interval_seconds: int = 5,
    max_frames: int = 6,
) -> list[str]:
    """動画全体からフレームを均等に抽出してJPEG保存する。"""

    video_path_obj = Path(video_path)

    if not video_path_obj.is_file():
        raise FileNotFoundError(
            f"動画ファイルが見つかりません: {video_path_obj}"
        )

    if interval_seconds <= 0:
        raise ValueError(
            "interval_secondsは1以上にしてください。"
        )

    if max_frames <= 0:
        raise ValueError(
            "max_framesは1以上にしてください。"
        )

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
            (total_frames - 1) / fps
            if total_frames > 1
            else 0.0
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
        output_dir.mkdir(parents=True, exist_ok=True)

        saved_paths: list[str] = []

        def save_frame(
            frame,
            saved_index: int,
            elapsed_seconds: float,
        ) -> None:
            output_path = (
                output_dir
                / (
                    f"frame_{saved_index:03d}_"
                    f"{elapsed_seconds:06.2f}s.jpg"
                )
            )

            encode_success, encoded = cv2.imencode(
                ".jpg",
                frame,
                [cv2.IMWRITE_JPEG_QUALITY, 88],
            )

            if not encode_success:
                raise RuntimeError(
                    f"画像のJPEG変換に失敗しました: {output_path}"
                )

            encoded.tofile(str(output_path))
            saved_paths.append(str(output_path))

            print(
                f"[VideoAnalyzer] saved "
                f"{elapsed_seconds:.2f}s "
                f"-> {output_path}"
            )

        if total_frames > 0:
            sample_count = min(
                max_frames,
                max(
                    1,
                    ceil(
                        duration_seconds
                        / interval_seconds
                    ) + 1,
                ),
            )

            if sample_count == 1:
                frame_indexes = [0]
            else:
                last_frame_index = total_frames - 1
                frame_indexes = sorted(
                    {
                        round(
                            last_frame_index
                            * index
                            / (sample_count - 1)
                        )
                        for index in range(sample_count)
                    }
                )

            for frame_index in frame_indexes:
                cap.set(
                    cv2.CAP_PROP_POS_FRAMES,
                    frame_index,
                )

                success, frame = cap.read()

                if not success:
                    print(
                        "[VideoAnalyzer] skipped "
                        f"frame_index={frame_index}"
                    )
                    continue

                save_frame(
                    frame,
                    len(saved_paths),
                    frame_index / fps,
                )

        else:
            frame_interval = max(
                1,
                int(round(fps * interval_seconds)),
            )
            frame_index = 0

            while len(saved_paths) < max_frames:
                success, frame = cap.read()

                if not success:
                    break

                if frame_index % frame_interval == 0:
                    save_frame(
                        frame,
                        len(saved_paths),
                        frame_index / fps,
                    )

                frame_index += 1

        print(
            f"[VideoAnalyzer] "
            f"{len(saved_paths)} frames extracted"
        )

        return saved_paths

    finally:
        cap.release()
