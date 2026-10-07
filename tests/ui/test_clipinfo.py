"""Overview data: duration, title, poster. Real ffmpeg if available, otherwise skipped."""

import shutil
import subprocess

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from autoreels.orchestr import clipinfo  # noqa: E402

needs_ffmpeg = pytest.mark.skipif(
    not (shutil.which("ffmpeg") and shutil.which("ffprobe")), reason="ffmpeg/ffprobe not installed"
)


def _make_mp4(path, seconds=3):
    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"color=c=blue:size=108x192:rate=10:d={seconds}",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path)],
        check=True,
    )


@pytest.fixture()
def root(tmp_path):
    src = tmp_path / "reels-out" / "SRC"
    src.mkdir(parents=True)
    return tmp_path


@pytest.fixture()
def client(root):
    import autoreels.orchestr.settings as _s
    from autoreels.orchestr.settings import Settings
    _s.settings = Settings.from_env(root_override=str(root))
    from autoreels.orchestr.app import app
    return TestClient(app)


def test_title_first_nonempty_line(tmp_path):
    mp4 = tmp_path / "r01.mp4"
    mp4.write_bytes(b"x")
    assert clipinfo.title(mp4) is None
    (tmp_path / "r01.txt").write_text("\n  Почему мы ругаем себя  \nописание\n", encoding="utf-8")
    assert clipinfo.title(mp4) == "Почему мы ругаем себя"


def test_missing_ffmpeg_gives_none(tmp_path, monkeypatch):
    mp4 = tmp_path / "r01.mp4"
    mp4.write_bytes(b"x")
    monkeypatch.setattr(clipinfo.shutil, "which", lambda name: None)
    clipinfo._duration_cache.clear()
    assert clipinfo.duration_s(mp4) is None
    assert clipinfo.poster(mp4, tmp_path / "cache") is None


@needs_ffmpeg
def test_clips_have_duration_and_title(client, root):
    mp4 = root / "reels-out" / "SRC" / "r01.mp4"
    _make_mp4(mp4, 3)
    (mp4.with_suffix(".txt")).write_text("Заголовок\n", encoding="utf-8")
    c = client.get("/api/sources/SRC/clips").json()[0]
    assert c["title"] == "Заголовок"
    assert 2.9 <= c["duration_s"] <= 3.1


@needs_ffmpeg
def test_thumb_is_jpeg_cached_and_refreshed_after_rerender(client, root):
    mp4 = root / "reels-out" / "SRC" / "r01.mp4"
    _make_mp4(mp4, 3)
    r = client.get("/api/thumb/SRC/r01")
    assert r.status_code == 200 and r.headers["content-type"] == "image/jpeg"
    assert r.content[:2] == b"\xff\xd8"
    thumbs = root / "data" / "cache" / "ui" / "thumbs"
    assert len(list(thumbs.glob("*.jpg"))) == 1
    client.get("/api/thumb/SRC/r01")  # second call: served from cache
    assert len(list(thumbs.glob("*.jpg"))) == 1
    _make_mp4(mp4, 2)  # "re-render": new size/mtime → new poster
    client.get("/api/thumb/SRC/r01")
    assert len(list(thumbs.glob("*.jpg"))) == 2


def test_thumb_rejects_traversal(client, root):
    for url in ("/api/thumb/%2E%2E/r01", "/api/thumb/SRC/..%2Fr01", "/api/thumb/SRC/r01?variant=../.."):
        assert client.get(url).status_code == 404
