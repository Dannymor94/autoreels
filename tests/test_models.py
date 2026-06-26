"""Схема манифеста — ЕДИНСТВЕННЫЙ контракт между тирами (core/models.py).

Инварианты, которые тесты защищают:
- двухуровневость: crop/scale на уровне манифеста (SetupProfile), НЕ в Reel;
- subtitles[] несут word-level {word,t0,t1}, а не готовый текст (переживают R0→R1→R3);
- status + run_key заложены в типы сразу (two-phase), даже если M0 их не дёргает;
- reels/subtitles — обычный list с дефолтом [], без валидатора непустоты.
"""
from autoreels.core.models import (
    Manifest,
    Reel,
    SetupProfile,
    Crop,
    Word,
    Transcript,
    ProjectStatus,
)


def _setup() -> SetupProfile:
    return SetupProfile(
        setup_id="tearoom_main",
        crop=Crop(x=980, y=220, w=1010, h=1795),
        scale=[1080, 1920],
        frame=[3840, 2160],
    )


def test_crop_lives_at_manifest_level_not_in_reel():
    # Двухуровневость: прямоугольник кропа — на уровне сетапа манифеста.
    assert "crop" in SetupProfile.model_fields
    # В Reel копии/ссылки на crop быть не должно — он наследуется из manifest.setup.
    assert "crop" not in Reel.model_fields
    assert "scale" not in Reel.model_fields


def test_subtitles_carry_word_level_not_text():
    w = Word(word="привет", t0=124.3, t1=124.6)
    assert (w.word, w.t0, w.t1) == ("привет", 124.3, 124.6)
    reel = Reel(
        id="r01", start=124.3, end=168.9, score=87,
        hook="h", title="t", description="d", reason="r", topic="тема",
        subtitles=[w],
    )
    assert reel.subtitles[0].word == "привет"
    # В Reel нет поля с готовым текстом субтитров — группировка строк живёт на R3.
    assert "text" not in Reel.model_fields
    assert "lines" not in Reel.model_fields


def test_empty_reels_is_valid_default():
    # «Хороших моментов нет» — валидный исход. reels по дефолту [], без min_items.
    m = Manifest(
        source="lecture.mp4", duration_preset="shorts",
        setup=_setup(), run_key="abc123",
    )
    assert m.reels == []


def test_empty_subtitles_and_flags_default():
    reel = Reel(
        id="r01", start=1.0, end=20.0, score=70,
        hook="h", title="t", description="d", reason="r", topic="x",
    )
    assert reel.subtitles == []
    assert reel.flags == []  # чек-флаги ставит код (инвариант 6), по дефолту пусто


def test_status_defaults_pending_and_has_two_phase_boundary():
    m = Manifest(
        source="lecture.mp4", duration_preset="shorts",
        setup=_setup(), run_key="abc123",
    )
    assert m.status == ProjectStatus.pending
    # Граница Phase 1/Phase 2 выражена в типах.
    assert ProjectStatus.awaiting_review in set(ProjectStatus)
    assert ProjectStatus.approved in set(ProjectStatus)


def test_transcript_word_level_round_trip():
    # Транскрипт несёт word-level (та же форма Word, что и subtitles манифеста).
    tr = Transcript(
        language="russian",
        words=[Word(word="привет", t0=0.0, t1=0.5), Word(word="мир", t0=0.5, t1=0.9)],
    )
    restored = Transcript.model_validate_json(tr.model_dump_json())
    assert restored == tr
    assert restored.words[0].word == "привет"


def test_transcript_empty_words_is_valid_default():
    # Тишина/пустой транскрипт — валиден, без валидатора непустоты.
    tr = Transcript(language="russian")
    assert tr.words == []


def test_manifest_json_round_trip():
    m = Manifest(
        source="lecture.mp4", duration_preset="shorts",
        setup=_setup(), run_key="abc123",
        status=ProjectStatus.awaiting_review,
        reels=[
            Reel(
                id="r01", start=124.3, end=168.9, score=87,
                hook="За травмой скрыт ресурс", title="ЗА ТРАВМОЙ скрыт ДАР 🫀…",
                description="…", reason="контринтуитив + закрытая арка", topic="травма",
                flags=["too_long"],
                subtitles=[Word(word="за", t0=124.3, t1=124.5)],
            )
        ],
    )
    restored = Manifest.model_validate_json(m.model_dump_json())
    assert restored == m
