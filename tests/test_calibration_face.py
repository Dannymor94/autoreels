"""M78: the auto crop placed on the speaker's face (owner on PXL_20260729_copy: «ракурс сбит»)."""
from __future__ import annotations

from autoreels.core.calibration import auto_crop, face_crop, load_or_auto_calibrate


def test_face_crop_centres_the_median_face_and_stays_in_frame():
    W, H = 1920, 1080
    base = auto_crop((W, H))
    faces = [(600, 400, 200, 200), (640, 410, 200, 200), (620, 405, 200, 200), (1500, 300, 50, 50)]
    c = face_crop((W, H), faces, samples=6)
    assert (c.w, c.h, c.y) == (base.w, base.h, base.y)
    assert abs((c.x + c.w / 2) - 630) <= 1                     # median of 600, 620, 640, 1500 = 630
    assert face_crop((W, H), [(5, 400, 80, 80)] * 4, samples=4).x == 0          # clamped left
    assert face_crop((W, H), [(1915, 400, 80, 80)] * 4, samples=4).x == W - base.w
    assert face_crop((W, H), faces[:1], samples=20) is None    # a face in 1 of 20 frames: not enough
    assert face_crop((W, H), [], samples=20) is None


def test_auto_calibration_uses_the_face_and_falls_back_to_the_centre(tmp_path, capsys):
    size = (1920, 1080)
    s = load_or_auto_calibrate(tmp_path, "a" * 64, "v.mp4", get_frame_size=lambda: size,
                               get_faces=lambda: ([(600, 400, 200, 200)] * 10, 20))
    assert s.setup_id == "auto-face" and abs(s.crop.x + s.crop.w / 2 - 600) <= 1
    assert "ПО ЛИЦУ" in capsys.readouterr().out
    assert load_or_auto_calibrate(tmp_path, "a" * 64, "v.mp4", get_frame_size=lambda: size,
                                  get_faces=lambda: None).crop == auto_crop(size)
    def boom():
        raise RuntimeError("no ffmpeg")
    assert load_or_auto_calibrate(tmp_path, "a" * 64, "v.mp4", get_frame_size=lambda: size,
                                  get_faces=boom).crop == auto_crop(size)
    assert load_or_auto_calibrate(tmp_path, "a" * 64, "v.mp4", get_frame_size=lambda: size).crop == auto_crop(size)
    assert not list(tmp_path.iterdir())                         # nothing written to calibrations/


def test_detect_faces_reads_its_cache_and_needs_no_opencv_then(tmp_path, monkeypatch):
    import json
    import builtins
    from autoreels.local import autocrop
    cache = tmp_path / "x.faces.json"
    cache.write_text(json.dumps({"version": autocrop.FACES_VERSION, "samples": 20, "frame": [1920, 1080],
                                 "faces": [[600, 400, 200, 200]]}))
    real_import = builtins.__import__
    monkeypatch.setattr(builtins, "__import__",
                        lambda name, *a, **k: (_ for _ in ()).throw(ImportError(name)) if name == "cv2" else real_import(name, *a, **k))
    assert autocrop.detect_faces("v.mp4", (1920, 1080), cache_path=cache) == ([(600, 400, 200, 200)], 20)
    logs = []
    assert autocrop.detect_faces("v.mp4", (1280, 720), cache_path=cache, log=logs.append) is None   # other frame, no cv2
    assert "OpenCV не установлен" in logs[0]
