"""Build synthetic demo source in demo/reels-out/DEMO/.

Run: python demo/build_demo.py
Requires: ffmpeg in PATH, say (macOS) optional — falls back to 440 Hz sine.
"""
import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).parent.parent
OUT = REPO / "demo" / "reels-out" / "DEMO"

CLIPS = [
    ("r01", "#1a1a2e", "Это демо клип номер один"),
    ("r02", "#16213e", "Это демо клип номер два"),
    ("r03", "#0f3460", "Это демо клип номер три"),
]
VARIANT_B = ("r01", "#e94560", "Это вариант Б клип один")


def make_audio(text: str, dst: Path) -> None:
    with tempfile.NamedTemporaryFile(suffix=".aiff", delete=False) as f:
        aiff = f.name
    ok = subprocess.run(["say", "-v", "Milena", "-o", aiff, text], capture_output=True).returncode == 0
    if ok:
        subprocess.run(
            ["ffmpeg", "-y", "-i", aiff, "-c:a", "aac", "-b:a", "96k", str(dst)],
            capture_output=True, check=True,
        )
    else:
        subprocess.run(
            ["ffmpeg", "-y", "-f", "lavfi", "-i", "sine=frequency=440:duration=7",
             "-c:a", "aac", "-b:a", "96k", str(dst)],
            capture_output=True, check=True,
        )
    return ok


def make_clip(name: str, color: str, text: str, dst: Path, audio: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    fc = (
        f"[0]drawbox=x=440:y=200:w=200:h=200:color=white:t=fill,"
        f"drawbox=x=480:y=400:w=120:h=300:color=white:t=fill,"
        f"drawtext=text='{name}':fontsize=80:fontcolor=yellow:x=(w-tw)/2:y=h-150[v]"
    )
    subprocess.run([
        "ffmpeg", "-y",
        "-f", "lavfi", "-i", f"color=c={color}:size=1080x1920:rate=30",
        "-i", str(audio),
        "-filter_complex", fc,
        "-map", "[v]", "-map", "1:a",
        "-c:v", "libx264", "-crf", "30", "-preset", "veryfast",
        "-c:a", "aac", "-b:a", "96k",
        "-fflags", "+bitexact", "-map_metadata", "-1", "-movflags", "+faststart",
        "-t", "7",
        str(dst),
    ], capture_output=True, check=True)


def write_sidecar(mp4: Path, spec: str) -> None:
    fp = hashlib.sha1(spec.encode()).hexdigest()
    mp4.with_suffix(".render.json").write_text(json.dumps({"fingerprint": fp}))
    mp4.with_suffix(".txt").write_text(f"Демо клип {mp4.stem}\n")


def main():
    say_used = False
    with tempfile.TemporaryDirectory() as tmp:
        for name, color, text in CLIPS:
            mp4 = OUT / f"{name}.mp4"
            audio = Path(tmp) / f"{name}.aac"
            used_say = make_audio(text, audio)
            say_used = say_used or used_say
            make_clip(name, color, text, mp4, audio)
            write_sidecar(mp4, f"{name}:{color}")
            print(f"  {mp4.relative_to(REPO)}")

        vb_name, vb_color, vb_text = VARIANT_B
        vb_mp4 = OUT / "_gate" / "variant_b" / f"{vb_name}.mp4"
        audio = Path(tmp) / "variant_b.aac"
        make_audio(vb_text, audio)
        make_clip(vb_name, vb_color, vb_text, vb_mp4, audio)
        write_sidecar(vb_mp4, f"variant_b:{vb_color}")
        print(f"  {vb_mp4.relative_to(REPO)}")

    total = sum(f.stat().st_size for f in OUT.rglob("*") if f.is_file())
    print(f"Total: {total / 1024 / 1024:.1f} MB  (say={'yes' if say_used else 'sine fallback'})")


if __name__ == "__main__":
    main()
