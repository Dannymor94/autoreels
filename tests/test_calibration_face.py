"""M78: the auto crop placed on the speaker's face (owner on PXL_20260729_copy: «ракурс сбит»)."""
from __future__ import annotations

from autoreels.core.calibration import auto_crop, face_crop, load_or_auto_calibrate


def test_face_crop_centres_the_median_face_and_stays_in_frame():
    W, H = 1920, 1080
    base = auto_crop((W, H))
    faces = [(600, 400, 200, 200), (640, 410, 200, 200), (620, 405, 200, 200), (1500, 300, 50, 50)]
    c = face_crop((W, H), faces, samples=6)
    assert (c.w, c.h, c.y) == (base.w, base.h, base.y)
    assert abs((c.x + c.w / 2) - 620) <= 1                     # M87: 1500 is another place — median of 600, 620, 640
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


def test_faces_in_different_places_count_only_the_group_seen_most():
    """M87 (Pxl 20260621: a face in 10–11 of 20 frames, the median moved the frame 68–85 % of its width — between
    two places, on nobody): faces closer than half the crop width are one place; the place seen in the most frames
    wins (equal counts: the larger faces); that place alone must reach min_share, else the centre crop stays."""
    W, H = 3840, 2160
    base = auto_crop((W, H))
    left = [(300 + i * 10, 900, 300, 300) for i in range(7)]
    mid = [(1900 + i * 10, 800, 200, 200) for i in range(4)]
    c = face_crop((W, H), left + mid, samples=20)
    assert abs(c.x + c.w / 2 - 330) <= 1 or c.x == 0            # the left place (7 frames), not between the two
    tie = [(300, 900, 300, 300)] * 6 + [(1900, 800, 200, 200)] * 6
    assert abs(face_crop((W, H), tie, samples=20).x + base.w / 2 - 1900) > 1000      # equal: the larger faces
    split = [(300, 900, 300, 300)] * 5 + [(1900, 800, 200, 200)] * 5 + [(3500, 800, 200, 200)]
    assert face_crop((W, H), split, samples=20) is None         # 11 of 20 found, but no place reaches 30 %
    one = [(1800 + i * 40, 800, 200, 200) for i in range(8)]      # one place, spread a little: as before
    assert abs(face_crop((W, H), one, samples=20).x + base.w / 2 - (1800 + 3.5 * 40)) <= 1


def test_m102_the_reel_frame_moves_only_when_its_face_is_off_the_middle():
    from autoreels.core.calibration import reel_crop, reel_face
    from autoreels.core.models import Crop
    base = Crop(x=1240, y=0, w=1215, h=2160)
    faces = [(1000, 700, 300, 300), (1010, 690, 310, 300), (1015, 710, 290, 300), (3500, 500, 80, 80)]
    face = reel_face(faces, 7, base.w / 2)
    assert face == (1010.0, 700.0, 300.0, 300.0)                     # the place seen most; 3500 is someone else
    assert reel_face(faces, 20, base.w / 2) is None                  # 3 of 20 frames: below 40 %
    assert reel_face([], 7, base.w / 2) is None
    assert reel_crop(base, (3840, 2160), (1847, 700, 300, 300)) == base          # in the middle: as calibrated
    assert reel_crop(base, (3840, 2160), (1847 + 180, 700, 300, 300)) == base    # within 15 % of the width
    moved = reel_crop(base, (3840, 2160), (1007.5, 700, 300, 300))
    assert (moved.x, moved.y, moved.w, moved.h) == (400, 0, 1215, 2160)
    assert reel_crop(base, (3840, 2160), (100, 700, 300, 300)).x == 0           # clamped to the frame
    assert reel_crop(base, (3840, 2160), None) == base


def test_m102_the_close_shot_comes_from_the_face_and_does_not_go_soft():
    from autoreels.core.calibration import face_close_crop
    from autoreels.core.models import Crop
    wide = Crop(x=400, y=0, w=1215, h=2160)                          # 4K source: room to zoom
    c, z = face_close_crop(wide, (1007.5, 700, 300, 300), out_h=1920)
    assert z == 1.6 and (c.w, c.h, c.x, c.y) == (760, 1350, 628, 160)          # capped by max_scale
    c, z = face_close_crop(wide, (1007.5, 900, 500, 500), out_h=1920)
    assert z == round(2160 / c.h, 3) and 1.2 < z < 1.22                          # face 28 % of the height
    assert abs((c.y + 0.4 * c.h) - 900) <= 1 and abs((c.x + c.w / 2) - 1007.5) <= 1
    hd = Crop(x=656, y=0, w=608, h=1080)                             # 1080p source: the upscale caps it
    c, z = face_close_crop(hd, (960, 350, 120, 120), out_h=1920)
    assert z == round(1080 / c.h, 3) and z <= 1080 * 2.5 / 1920 + 0.01
    c, z = face_close_crop(hd, (960, 350, 700, 700), out_h=1920)     # a face already big: still a visible switch
    assert z >= 1.15
    c, _ = face_close_crop(hd, (660, 20, 120, 120), out_h=1920)      # at the corner: stays inside the wide frame
    assert c.x == 656 and c.y == 0 and c.x + c.w <= 656 + 608
