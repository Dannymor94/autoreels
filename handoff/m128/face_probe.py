#!/usr/bin/env python3
"""M128 (замер, пишет только handoff/m128/frames/*.jpg): что именно детектор лица находит на Pxl 20260621 112938952.

    .venv/bin/python handoff/m128/face_probe.py "Pxl 20260621 112938952" [кадров]

m127: «лицо» нашлось в 29 из 40 кадров на x ≈ 880 (высота ≈ 650 px из 2160), рамка ушла туда — а там полки с чайником;
ролики, где «лица» не нашлось (рамка посередине), владелец назвал правильными. Похоже на ложное срабатывание
каскада Хаара на неподвижном предмете. Здесь на равномерных кадрах видео рисуются:
  красный  — каскад Хаара как в рендере (самое большое найденное);
  жёлтый   — тот же, но только с найденным в нём глазом (каскад глаз в верхней половине рамки);
  зелёный  — YuNet (нейросетевой детектор OpenCV), если модель удалось скачать в data/models/;
  синий    — рамка ролика 9:16 по красному (как ставит рендер) — что видит зритель.
Печатает по кадру: что нашёл каждый детектор (центр x, высота).
"""
from __future__ import annotations

import json
import subprocess
import sys
import urllib.request
from pathlib import Path

import cv2
import numpy as np

YUNET_URL = "https://github.com/opencv/opencv_zoo/raw/main/models/face_detection_yunet/face_detection_yunet_2023mar.onnx"


def frame(video: str, t: float, width: int = 960):
    raw = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{t:.2f}", "-i", video, "-frames:v", "1",
                          "-vf", f"scale={width}:-2", "-f", "image2pipe", "-vcodec", "png", "-"],
                         capture_output=True, check=True).stdout
    return cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)


def main() -> int:
    stem = sys.argv[1]
    n = int(sys.argv[2]) if len(sys.argv) > 2 else 12
    m = json.load(open(f"manifests/{stem}.json", encoding="utf-8"))
    video = m.get("source_path") or str(Path("inputs") / m["source"])
    W, H = m["setup"]["frame"]
    crop_w = int(m["setup"]["crop"]["w"])
    dur = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0",
                                video], capture_output=True, text=True, check=True).stdout.strip())
    out = Path("handoff/m128/frames")
    out.mkdir(parents=True, exist_ok=True)
    face_c = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
    eye_c = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_eye.xml")
    yunet = None
    mp = Path("data/models/face_detection_yunet_2023mar.onnx")
    try:
        if not mp.is_file():
            mp.parent.mkdir(parents=True, exist_ok=True)
            urllib.request.urlretrieve(YUNET_URL, mp)
        yunet = cv2.FaceDetectorYN.create(str(mp), "", (320, 320), 0.7)
    except Exception as exc:  # noqa: BLE001 — YuNet is optional here
        print(f"YuNet: нет ({type(exc).__name__}: {str(exc)[:80]})")
    print(f"{stem}: {W}×{H}, рамка {crop_w} px, кадров {n}")
    for i in range(n):
        t = dur * (i + 0.5) / n
        img = frame(video, t)
        h, w = img.shape[:2]
        k = W / w
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        found = face_c.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=6, minSize=(max(24, w // 20),) * 2)
        line = [f"{t:7.1f} с:"]
        if len(found):
            x, y, fw, fh = max(found, key=lambda f: f[2] * f[3])
            cv2.rectangle(img, (x, y), (x + fw, y + fh), (0, 0, 255), 3)
            eyes = eye_c.detectMultiScale(gray[y:y + fh // 2, x:x + fw], 1.1, 5)
            line.append(f"хаар x {(x + fw / 2) * k:.0f} h {fh * k:.0f}, глаз {len(eyes)}")
            if len(eyes):
                cv2.rectangle(img, (x + 4, y + 4), (x + fw - 4, y + fh - 4), (0, 255, 255), 2)
            cx = (x + fw / 2) * k
            x0 = max(0, min(W - crop_w, cx - crop_w / 2)) / k
            cv2.rectangle(img, (int(x0), 0), (int(x0 + crop_w / k), h - 1), (255, 0, 0), 2)
        else:
            line.append("хаар —")
        if yunet is not None:
            yunet.setInputSize((w, h))
            _, faces = yunet.detect(img)
            if faces is not None and len(faces):
                f = max(faces, key=lambda r: r[2] * r[3])
                fx, fy, fw2, fh2 = (int(v) for v in f[:4])
                cv2.rectangle(img, (fx, fy), (fx + fw2, fy + fh2), (0, 255, 0), 3)
                line.append(f"yunet x {(fx + fw2 / 2) * k:.0f} h {fh2 * k:.0f} score {f[-1]:.2f}")
            else:
                line.append("yunet —")
        cv2.imwrite(str(out / f"f{i:02d}.jpg"), img, [cv2.IMWRITE_JPEG_QUALITY, 70])
        print("   " + "; ".join(line))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
