"""Архивация обработанного входа: inputs/ → inputs-archive/ ПОСЛЕ успеха (batch, M0).

Инварианты:
- успех → видео уезжает в архив, из inputs/ исчезает (дренаж, не копия);
- идемпотентность: то же видео уже в архиве (имя+содержимое) → skip, дубликат из
  inputs/ убирается, архив не трогаем (повторный batch не падает и не плодит);
- конфликт: в архиве файл с тем же именем, но ДРУГИМ содержимым → ошибка, ничего не
  двигаем (не теряем данные молчаливой перезаписью);
- is_archived — True только при совпадении имени И sha (контентная идентичность).
"""
from pathlib import Path

import pytest

from autoreels.local.archive import ArchiveError, archive_input, is_archived


def _file(path: Path, data: bytes) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


def test_archive_input_moves_video_to_archive(tmp_path):
    inputs = tmp_path / "inputs"
    archive = tmp_path / "inputs-archive"
    video = _file(inputs / "lecture.mp4", b"VIDEO-BYTES")

    res = archive_input(video, archive)

    assert res.status == "archived"
    assert res.dest == archive / "lecture.mp4"
    assert (archive / "lecture.mp4").read_bytes() == b"VIDEO-BYTES"   # в архиве
    assert not video.exists()                                         # из inputs/ ушло (дренаж)


def test_archive_creates_archive_dir_if_missing(tmp_path):
    video = _file(tmp_path / "inputs" / "v.mp4", b"x")
    archive = tmp_path / "inputs-archive"           # ещё не существует
    archive_input(video, archive)
    assert (archive / "v.mp4").is_file()


def test_archive_idempotent_when_same_video_already_archived(tmp_path):
    # то же видео (имя+содержимое) уже в архиве, дубль завис в inputs/ → skip + дренаж дубля
    archive = tmp_path / "inputs-archive"
    _file(archive / "v.mp4", b"SAME")
    dup = _file(tmp_path / "inputs" / "v.mp4", b"SAME")

    res = archive_input(dup, archive)

    assert res.status == "skipped"
    assert (archive / "v.mp4").read_bytes() == b"SAME"   # архив не тронут
    assert not dup.exists()                              # дубль из inputs/ убран


def test_archive_conflict_same_name_different_content_errors(tmp_path):
    # в архиве тот же ИМЯ, но другое содержимое → ошибка, ничего не двигаем (не теряем)
    archive = tmp_path / "inputs-archive"
    _file(archive / "v.mp4", b"OLD")
    video = _file(tmp_path / "inputs" / "v.mp4", b"NEW")

    with pytest.raises(ArchiveError):
        archive_input(video, archive)

    assert (archive / "v.mp4").read_bytes() == b"OLD"    # архив не перезаписан
    assert video.read_bytes() == b"NEW"                  # вход на месте (не потеряли)


def test_is_archived_true_only_on_same_content(tmp_path):
    archive = tmp_path / "inputs-archive"
    video = _file(tmp_path / "inputs" / "v.mp4", b"DATA")

    assert is_archived(video, archive) is False          # архива нет вовсе

    _file(archive / "v.mp4", b"DATA")
    assert is_archived(video, archive) is True           # имя+содержимое совпали

    _file(archive / "v.mp4", b"OTHER")
    assert is_archived(video, archive) is False           # имя то же, содержимое иное
