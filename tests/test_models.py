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
        setup=_setup(), run_key="abc123", source_sha256="a" * 64,
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
        setup=_setup(), run_key="abc123", source_sha256="a" * 64,
    )
    assert m.status == ProjectStatus.pending
    # Граница Phase 1/Phase 2 выражена в типах.
    assert ProjectStatus.awaiting_review in set(ProjectStatus)
    assert ProjectStatus.approved in set(ProjectStatus)


def test_manifest_carries_source_sha256_for_local_resolution():
    # Локальный тир ищет исходник в inputs/ по sha256, а не по Mac-пути из source.
    # Значит контент-хэш источника обязан жить в манифесте (grounding идентичности).
    m = Manifest(
        source="/Users/danny/Documents/inputs/lecture.mp4", duration_preset="shorts",
        setup=_setup(), run_key="abc123",
        source_sha256="a" * 64,
    )
    assert m.source_sha256 == "a" * 64
    # source — провенанс/подсказка по имени; идентичность несёт хэш.
    assert "source_sha256" in Manifest.model_fields


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
        setup=_setup(), run_key="abc123", source_sha256="a" * 64,
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


def test_variable_speed_timing_and_subtitle_occurrences():
    import pytest
    from autoreels.core.models import Segment
    from autoreels.core.playback_timing import build_window_timing
    from autoreels.local.subtitles import remap_to_output

    windows=[Segment(start=4,end=6),Segment(start=0,end=2),Segment(start=4,end=6)]
    words=[Word(word="A",t0=0.5,t1=1.0),Word(word="gap",t0=3,t1=3.5),
           Word(word="B",t0=4.5,t1=5.0)]
    rates=(0.5,2.0,1.0)
    timing=build_window_timing(windows,rates)
    assert [(w.output_start,w.output_end) for w in timing]==[(0,4),(4,5),(5,7)]
    mapped=remap_to_output(words,windows,window_rates=rates)
    assert [(w.word,w.t0,w.t1) for w in mapped]==[("B",1,2),("A",4.25,4.5),("B",5.5,6)]
    for window in timing:
        middle=(window.source_start+window.source_end)/2
        assert window.to_source(window.to_output(middle))==pytest.approx(middle)
        assert window.to_source(window.output_end)==window.source_end
    assert remap_to_output(words,windows,speed=2)==remap_to_output(words,windows,window_rates=(2,2,2))
    assert [(w.word,w.t0,w.t1) for w in words]==[("A",0.5,1.0),("gap",3,3.5),("B",4.5,5.0)]


def test_variable_speed_rejects_ambiguous_or_unsupported_timing():
    import pytest
    from autoreels.core.models import Segment
    from autoreels.core.playback_timing import build_window_timing
    from autoreels.local.subtitles import remap_to_output

    windows=[Segment(start=0,end=1),Segment(start=3,end=4)]
    for rates in ((),(1,), (1,1,1),(True,1),(0,1),(0.49,1),(2.01,1),(float("nan"),1)):
        with pytest.raises(ValueError):
            build_window_timing(windows,rates)
    with pytest.raises(ValueError):
        build_window_timing([Segment(start=1,end=1)],(1,))
    with pytest.raises(ValueError):
        build_window_timing([],())
    with pytest.raises(ValueError):
        remap_to_output([],windows,speed=1.5,window_rates=(1,2))
    with pytest.raises(ValueError):
        remap_to_output([],windows,xfade_sec=0.1,window_rates=(1,2))
    with pytest.raises(ValueError):
        remap_to_output([Word(word="cross",t0=0.9,t1=1.1)],windows,window_rates=(1,2))


def test_window_rates_manifest_opt_in_and_legacy_serialization():
    import pytest
    from autoreels.core.models import Segment
    legacy=Reel(id="r01",start=0,end=2,score=80,hook="",title="",description="",
                planned=True,segments=[Segment(start=0,end=2)])
    assert "window_rates" not in legacy.model_dump()
    assert '"window_rates"' not in legacy.model_dump_json()
    assert Reel.model_validate_json(legacy.model_dump_json()).model_dump_json()==legacy.model_dump_json()
    rated=Reel.model_validate({**legacy.model_dump(),"window_rates":[0.5]})
    assert Reel.model_validate_json(rated.model_dump_json()).window_rates==[0.5]
    assert rated.playback_duration()==2  # legacy source-time contract remains unchanged
    for changes in ({"window_rates":[]},{"window_rates":[0.49]},{"window_rates":[True]},
                    {"window_rates":[1,2]},{"speed":1.5,"window_rates":[1]},
                    {"planned":False,"window_rates":[1]},{"fx":{"push":True},"window_rates":[1]}):
        with pytest.raises(ValueError):
            Reel.model_validate({**legacy.model_dump(),**changes})
    with pytest.raises(ValueError):
        rated.model_copy(update={"segments":[Segment(start=0,end=1),Segment(start=1,end=2)]}).check_segments()

def test_graphic_layer_optional_and_bound_to_output_duration():
    import pytest
    from autoreels.core.models import GraphicLayer, Segment

    base = Reel(id="r01",start=0,end=5,score=80,hook="",title="",description="",
                planned=True,segments=[Segment(start=0,end=2),Segment(start=3,end=5)],
                window_rates=[0.5,2.0])
    assert "graphic_layer" not in base.model_dump()
    spec = dict(x_pct=10,y_pct=10,width_pct=20,height_pct=20,
                start_ms=1000,end_ms=4500,color="white")
    layer = GraphicLayer(**spec)
    reel = Reel.model_validate({**base.model_dump(),"graphic_layer":layer})
    assert Reel.model_validate_json(reel.model_dump_json()) == reel
    for changes in ({"x_pct":90},{"start_ms":4500},{"end_ms":5001},
                    {"color":"white;null"},{"width_pct":True}):
        with pytest.raises(ValueError):
            Reel.model_validate({**base.model_dump(),"graphic_layer":{**spec,**changes}})
    with pytest.raises(ValueError):
        Reel.model_validate({**base.model_dump(),"graphic_layer":spec,"planned":False})
    with pytest.raises(ValueError):
        reel.model_copy(update={"graphic_layer":layer.model_copy(update={"end_ms":5001})}).check_segments()
