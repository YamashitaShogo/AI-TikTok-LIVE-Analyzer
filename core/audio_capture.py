from array import array
from pathlib import Path
import os
import time
import wave

import pyaudiowpatch as pyaudio


CAPTURE_DIR = (
    Path(os.getenv("LOCALAPPDATA", Path.home()))
    / "AI-TikTok-LIVE-Analyzer"
    / "capture"
)

LATEST_AUDIO_PATH = CAPTURE_DIR / "latest_audio.wav"


def capture_system_audio(
    seconds=20,
    samplerate=48000,
    output_path=LATEST_AUDIO_PATH,
):
    CAPTURE_DIR.mkdir(parents=True, exist_ok=True)

    chunks = []

    def callback(
        in_data,
        frame_count,
        time_info,
        status,
    ):
        chunks.append(in_data)
        return (in_data, pyaudio.paContinue)

    with pyaudio.PyAudio() as audio:
        device = audio.get_default_wasapi_loopback()

        channels = int(
            device["maxInputChannels"]
        )

        device_rate = int(
            device["defaultSampleRate"]
        )

        rate = int(
            samplerate or device_rate
        )

        with audio.open(
            format=pyaudio.paInt16,
            channels=channels,
            rate=rate,
            input=True,
            input_device_index=int(
                device["index"]
            ),
            frames_per_buffer=512,
            stream_callback=callback,
        ):
            time.sleep(float(seconds))

    if not chunks:
        raise RuntimeError(
            "\u97f3\u58f0\u30c7\u30fc\u30bf\u3092\u53d6\u5f97\u3067\u304d\u307e\u305b\u3093\u3067\u3057\u305f\u3002"
        )

    audio_bytes = b"".join(chunks)

    samples = array("h")
    samples.frombytes(audio_bytes)

    if not samples or max(
        abs(sample)
        for sample in samples
    ) == 0:
        raise RuntimeError(
            "\u9332\u97f3\u3057\u305f\u97f3\u58f0\u304c\u7121\u97f3\u3067\u3059\u3002"
        )

    output_path = Path(output_path)
    temp_path = output_path.with_name(
        "latest_audio.tmp.wav"
    )

    with wave.open(
        str(temp_path),
        "wb",
    ) as wav_file:
        wav_file.setnchannels(channels)
        wav_file.setsampwidth(2)
        wav_file.setframerate(rate)
        wav_file.writeframes(audio_bytes)

    temp_path.replace(output_path)

    return output_path


if __name__ == "__main__":
    path = capture_system_audio()
    print(path)
