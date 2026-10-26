"""Загрузка config/ (YAML) + profiles/ (JSON). Ноль магических чисел в коде.

Принципы (CLAUDE.md):
- **Типизация, не сырые dict.** Конфиг валидируется в Pydantic-объект, опечатка в ключе
  (`extra='forbid'`) падает на загрузке, а не молча течёт внутрь R0.
- **Fail-fast.** Битый/неполный файл → `ConfigError` на загрузке, без молчаливых дефолтов.
- **Пресет → числа в одном месте.** `duration_preset` резолвится в `min_duration`/
  `max_duration` здесь (`R0Config`), больше нигде.
- **Профиль валидируется.** crop в границах кадра, scale = целевое вертикальное разрешение.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from autoreels.core.models import SetupProfile

# Целевое вертикальное разрешение 9:16 — единственно допустимое для профиля сетапа.
TARGET_SCALE = [1080, 1920]


class ConfigError(Exception):
    """Любая проблема загрузки/валидации конфига. Бросается на загрузке (fail-fast)."""


# --------------------------------------------------------------------------- R0

class Preset(BaseModel):
    """Пресет длины клипа в секундах."""

    model_config = ConfigDict(extra="forbid")

    min: int
    max: int


class PromptPaths(BaseModel):
    """Пути к рантайм-промптам R0 (относительно корня репо). Не хардкод в коде."""

    model_config = ConfigDict(extra="forbid")

    system: str
    fewshot: str


class ChunkingConfig(BaseModel):
    """Параметры чанкинга: Whisper-чанкинг аудио + R0-чанкинг транскрипта."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    whisper_chunk_duration_sec: int = 600       # целевая длина одного аудио-чанка (10 мин)
    whisper_threshold_minutes: float = 15       # порог «чанкить по длительности»
    whisper_threshold_bytes: int = 20 * 1024 * 1024  # порог «чанкить по размеру» (20 МБ)
    silence_window_sec: float = 30              # окно поиска тишины вокруг target-границы
    silence_threshold_db: float = -40           # порог silencedetect (дБ)
    r0_chunk_tokens: int = 2000                 # целевой размер R0-чанка транскрипта (токены)
    r0_overlap_tokens: int = 300                # перекрытие R0-чанков (≥60с)
    r0_chunk_delay_sec: float = 2.0             # пауза между R0-чанками (избежать 429 TPM)
    dedup_overlap_ratio: float = 0.5            # порог дедупа рилов из разных R0-чанков
    fail_fast: bool = False                     # False → продолжать при провале чанка


class BlocksFilterConfig(BaseModel):
    """Stage-2 filter config: deterministic pre-filter before LLM scoring."""

    model_config = ConfigDict(extra="forbid")

    head_skip_sec: float = 30.0          # drop blocks whose midpoint < this (greetings)
    tail_skip_sec: float = 30.0          # drop blocks whose midpoint > total-this (sign-offs)
    speech_density_min: float = 0.4      # drop if spoken_time/wall_time < threshold
    repetition_unique_ratio_min: float = 0.3  # drop if unique_words/total_words < threshold
    artefact_markers: list[str] = Field(default_factory=lambda: [
        "субтитры создавал",
        "субтитры созданы",
        "субтитры сделал",
        "редактор субтитров",
        "続きは",
        "字幕",
    ])
    promo_keywords: list[str] = Field(default_factory=lambda: [
        "приходите на",
        "перерыв",
        "включите звук",
        "слышно меня",
        "запись идёт",
        "подписывайтесь",
    ])
    signoff_phrases: list[str] = Field(default_factory=lambda: [
        "спасибо, что были",
        "спасибо за внимание",
        "до встречи",
        "всем пока",
        "на этом всё",
        "до новых встреч",
        "здравствуйте",
        "добрый день",
        "рад вас видеть",
        "давайте начнём",
    ])


class BlockScoringConfig(BaseModel):
    """Stage-3 heuristic scoring config: weights and lists for score_block()."""

    model_config = ConfigDict(extra="forbid")

    # Positive weights (raw points contributed when feature is present)
    w_duration: float = 20.0        # bell-curve peak inside sweet_spot_min..sweet_spot_max
    w_ends_sentence: float = 10.0   # block ends on terminal punctuation
    w_opens_sentence: float = 10.0  # first word is not a dangling opener (pronoun/conjunction)
    w_question: float = 8.0         # block contains an interrogative sentence
    w_contrarian: float = 12.0      # block contains a contrarian / hook marker
    w_lexical: float = 8.0          # lexical richness: unique_words / total_words

    # Negative weights (subtracted from raw score)
    w_dangling: float = 10.0        # many pronouns/demonstratives in first sentence
    w_speaker_change: float = 20.0  # has_internal_speaker_change from stage 2
    w_density_penalty: float = 8.0  # speech density < 0.5 (near-silence); > 0.95 is normal speech

    # Duration bell-curve parameters
    min_sec: float = 18.0           # score = 0 at and below this (matches min_meaningful_sec)
    sweet_spot_min: float = 30.0    # ramp reaches 1.0 here
    sweet_spot_max: float = 60.0    # starts falling off here; hits 0 at sweet_max+(sweet_max-sweet_min)

    # Top-K filtering
    top_k_per_chunk: int = 8        # keep this many blocks per time window
    chunk_window_sec: float = 300.0 # time window size for per-chunk filtering (≈ R0 chunk in time)

    contrarian_markers: list[str] = Field(default_factory=lambda: [
        "на самом деле", "наоборот", "а вот и нет", "что интересно",
        "однако", "но дело в том", "интересно то", "всё дело в",
        "парадокс в том", "на самом же деле",
    ])
    # Words that make a bad first word: conjunctions indicating context-dependency,
    # 3rd-person pronouns, and demonstratives with definite back-reference.
    # "а" intentionally excluded: Russian host-question opener "А когда/А бывало ли" is standalone.
    bad_open_words: list[str] = Field(default_factory=lambda: [
        "и", "из", "но", "или",
        "поэтому", "потому", "однако", "ведь", "значит", "тоже", "также",
        "зато", "впрочем", "итак", "следовательно", "таким",
        "он", "она", "они", "оно", "его", "её", "их", "им", "ей",
        "тот", "та", "те", "этот", "эта", "эти", "этим",
    ])
    # 3rd-person pronouns and demonstratives used ONLY for dangling_reference density check
    # (NOT conjunctions — those appear mid-sentence normally and would inflate the ratio).
    dangling_pronouns: list[str] = Field(default_factory=lambda: [
        "он", "она", "они", "оно", "его", "её", "их", "им", "ей",
        "тот", "та", "те", "этот", "эта", "эти", "этим",
    ])


class FillerRemovalConfig(BaseModel):
    """Deterministic filler removal inside a chosen span (manual/edit path). Each removal becomes
    a gap between playback segments. On by default for human selections; a per-clip review marker
    (`f:0`/`f:1`) then a command flag then this config decide, mirroring the speed precedence."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    # Standalone fillers cut only at a clause edge (see cloud/edit.remove_fillers for the exact rule).
    filler_words: list[str] = Field(default_factory=lambda: [
        "ну", "вот", "как бы", "наверное", "значит", "типа", "короче",
    ])
    pause_shorten_sec: float = 0.8    # a silence longer than this is shortened…
    pause_residual_sec: float = 0.25  # …down to this residual (not removed entirely — no breathlessness)
    max_removed_share: float = 0.25   # never remove more than this share of the span


class LabelConfig(BaseModel):
    """`arl label` (cloud/label.py): LLM draft of the review lines, checked by code."""

    model_config = ConfigDict(extra="forbid")

    system: str = "prompts/label_system.md"
    fewshot: str = "prompts/label_fewshot.json"
    window_blocks: int = Field(4, ge=1, le=8)      # blocks per request; windows overlap (label.windows)
    min_sec: float = 20.0                          # played speech of a proposed clip
    max_sec: float = 90.0
    max_clip_blocks: int = Field(3, ge=1, le=3)    # a review line merges at most 3 blocks ('++')
    title_max_chars: int = 60
    repair_rounds: int = Field(1, ge=0, le=3)
    # M39: a clip whose time is less speech than this (speech map) is not a reel — guided practice,
    # meditation instructions with long silences. 0 = off.
    min_speech_share: float = Field(0.0, ge=0.0, le=1.0)
    interview: str = ""                            # extra system rules for source_kind interview
    rank: bool = False                             # one request per finished draft: clips ranked → score
    fewshot_examples: int = Field(2, ge=0, le=6)   # M41: owner-approved examples per request (other sources)


class MontageConfig(BaseModel):
    """M50: a montage line (M …) builds ONE clip from pieces of different blocks of a source.
    Off = M lines are reported and ignored (invariant 8). Numbers: see config/r0.yaml."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool = False
    seam_pad_sec: float = Field(0.20, ge=0.0, le=1.0)      # air on each side of a seam between pieces
    piece_min_sec: float = Field(6.0, ge=0.0)              # a shorter piece is reported
    seams_per_min_max: float = Field(3.0, gt=0.0)          # more seams per minute of clip is reported
    pace_ratio_max: float = Field(1.35, ge=1.0)            # speech rate of two joined pieces differs more → reported
    seam_jump_warn: float = Field(3.0, gt=0.0)             # picture jump at a seam above this × typical motion → reported
    loudness_diff_db: float = Field(4.0, gt=0.0)           # speech level on the two sides of a seam differs more → reported
    pitch_diff_st: float = Field(3.0, gt=0.0)              # median pitch on the two sides differs more (semitones) → reported
    side_sec: float = Field(4.0, gt=0.0)                   # loudness/pitch measured on this much played speech per side
    max_static_sec: float | None = Field(None, gt=0.0)     # M53: no shot of a montage clip lasts longer (None = off, M53c)
    min_shot_sec: float = Field(3.0, gt=0.0)               # … and every shot stays at least this long
    keywords: bool = True                                  # M53: k: words highlighted in a montage clip's subtitles
    emphasis: bool = True                                  # M53c: close shot on a k: keyword to the end of its sentence
    filler_cut: bool = False                               # M53b: cut «э»/pauses inside montage clips (f:1 / --filler win)
    filler_profile: str | None = None                      # M70: manual_filler_profiles entry for montage clips (--filler-profile wins)
    fx: "MontageFx" = Field(default_factory=lambda: MontageFx())   # M55: attention effects of montage clips
    join_gap_sec: float = Field(2.0, ge=0.0)               # M58: a piece that goes straight on (≤ this gap) joins the previous one
    join_heard: bool = False                                # M134: that gap is the pause heard (speech map / alignment), not Whisper's
    hook_air_sec: float = Field(0.0, ge=0.0, le=1.5)       # M74: silence kept after the cold open and before the body (0 = off)
    fx_auto_clips: bool = False                            # M77: the fx (not callouts) also on ordinary clips of an auto draft


class MontageFx(BaseModel):
    """M55: attention effects of a montage clip (local/fx.py, written to Reel.fx at --apply).
    Every switch off = the clip renders as before (invariant 8)."""

    model_config = ConfigDict(extra="forbid")

    push: bool = False                                     # slow push-in on every long shot
    push_pct: float = Field(4.0, ge=0.0, le=15.0)          # … this much closer by the end of the shot
    push_min_sec: float = Field(6.0, gt=0.0)               # … shots shorter than this stay still
    karaoke: bool = False                                  # subtitles light up word by word
    progress: bool = False                                 # thin bar at the bottom filling over the clip
    whoosh: bool = False                                   # soft whoosh under every seam
    whoosh_volume: float = Field(0.25, ge=0.0, le=1.0)
    callouts: bool = False                                 # o: callouts (big phrase for a moment)
    callout_numbers: bool = False                          # … plus every number said in the clip
    callout_numbers_max: int = Field(3, ge=0)
    callout_gap_sec: float = Field(8.0, ge=0.0)            # no two callouts closer than this
    callout_sec: float = Field(2.0, gt=0.0)                # a callout stays this long
    pop: bool = False                                      # M70: the clip opens zoomed in and settles (a sharp start)
    pop_pct: float = Field(8.0, ge=0.0, le=20.0)           # … this much closer on the first frame
    pop_sec: float = Field(0.6, gt=0.0, le=3.0)            # … back to the normal frame over this long
    plate_after_hook: bool = False                         # M74: the plate t: appears when the body starts, not over the hook

    def reel_fx(self, callouts: list[dict]) -> dict:
        """Reel.fx for one clip: only the switched-on effects ({} when all are off)."""
        out: dict = {}
        if self.push and self.push_pct > 0:
            out.update(push=True, push_pct=self.push_pct, push_min_sec=self.push_min_sec)
        if self.karaoke:
            out["karaoke"] = True
        if self.progress:
            out["progress"] = True
        if self.whoosh and self.whoosh_volume > 0:
            out.update(whoosh=True, whoosh_volume=self.whoosh_volume)
        if self.callouts and callouts:
            out.update(callouts=callouts, callout_sec=self.callout_sec)
        if self.pop and self.pop_pct > 0:
            out.update(pop=True, pop_pct=self.pop_pct, pop_sec=self.pop_sec)
        if self.plate_after_hook:
            out["plate_after_hook"] = True
        return out


class AutocutConfig(BaseModel):
    """M56: arl autocut — montage lines proposed from the map (cloud/autocut.py)."""

    model_config = ConfigDict(extra="forbid")

    clips: int = Field(5, ge=1)
    min_sec: float = Field(30.0, gt=0)
    target_sec: float = Field(60.0, gt=0)
    max_sec: float = Field(90.0, gt=0)
    max_pieces: int = Field(4, ge=1)
    min_punch: int = Field(3, ge=1, le=5)
    seed_punch: int = Field(4, ge=1, le=5)
    hook_min_words: int = Field(4, ge=1)
    overlap_max: float = Field(0.5, ge=0, le=1)
    use_filtered: bool = False
    check_pool: int = Field(3, ge=1)       # M60: candidates = clips × this; each checked by --apply, failures replaced
    max_shared: int = Field(0, ge=0)       # M68: thoughts two accepted clips may share (and never the same opener)
    # M119 (m118: 60 of the owner's 66 clips are one stretch of the talk inside one topic; build_clip failed on half the
    # seeds — a thought that leans back brings its whole chain; the start judge rejected 54–78% of the owner's starts)
    generator: str = Field("montage", pattern="^(montage|passage|mixed)$")   # passage: adjacent thoughts around a strong
    # one; mixed (M120): passage + a loop question from elsewhere + a later conclusion when the run has none
    seed_roles: list[Literal["thesis", "conclusion", "example", "metaphor", "question", "explanation", "address"]] = \
        Field(default_factory=list)                # roles a clip may grow around (punch ≥ seed_punch); [] = STORY
    passage_gap_sec: float = Field(30.0, gt=0)     # passage: a neighbour joins when at most this far from the run
    start_judge: str = Field("veto", pattern="^(veto|rank)$")   # rank: a start only the model rejects sorts the clip last
    clips_every_min: float = Field(0.0, ge=0)      # clips = max(clips, source minutes ÷ this); 0 = clips
    lean_depth: int = Field(0, ge=0)               # montage: links of what a thought leans on it brings; 0 = the chain
    # M120 (owner: «перестановки можно, без частых быстрых скачков; гибкий алгоритм кусков»): the jump rule
    rhythm: bool = False                           # every clip keeps it (cloud/autocut.py rhythm_why); False = as before
    rhythm_max_jumps: int = Field(2, ge=0)
    rhythm_jump_sec: float = Field(10.0, gt=0)     # a gap in the source longer than this (or going back) is a jump
    rhythm_settle_near: float = Field(6.0, ge=0)   # the piece after a jump: at least this after a short skip …
    rhythm_settle_far: float = Field(12.0, ge=0)   # … up to this after a far jump (rhythm_far_sec or more, or back)
    rhythm_far_sec: float = Field(120.0, gt=0)
    rhythm_tail: float = Field(0.5, ge=0, le=1)    # the last piece (the payoff) needs only this share
    # M138: the owner's taste learned from his clips (cloud/taste.py) orders the proposals; 0 = off
    taste_weight: float = Field(0.0, ge=0)
    taste_model: str = "config/taste.json"
    # M140: a pool smaller than the draft can take is filled with clips grown around seeds this strong; 0 = off
    fill_seed_punch: int = Field(0, ge=0, le=5)
    # M144: a clip's first sound needs this much silence heard before it (start, cold open); 0 = off
    start_pause_min: float = Field(0.0, ge=0.0, le=1.0)
    scenario_max_tokens: int = Field(6000, ge=500)   # M123: the scenarist's answer (arl autocut --scenario)
    scenario_timeout_sec: float = Field(300.0, gt=0)  # … the whole talk in one request takes longer than a judge
    scenario_tone: str = ""                # M142: the tone the scenarist keeps («строгий», «фановый», …); "" = none
    auto_mode: Literal["autocut", "scenario"] = "autocut"   # M153: who writes the reels in arl auto
    scenario_llm: Literal["haiku", "sonnet"] = "sonnet"     # M153: the scenarist's model in arl auto (paid)
    paid_llm: Literal["", "haiku", "sonnet"] = ""   # M157: arl auto --llm auto (map, judges, posts) → this model
    paid_until: str = ""                    # M157: …until this date (YYYY-MM-DD, inclusive); after it arl auto is free
    # M70 (owner: «берём 2, 4, 6»): the first 3 seconds, seams that hold, tempo
    hook_title: bool = True                # the model proposes a curiosity headline for the plate t: (grounded or not used)
    seam_check: bool = True                # the model judges every seam; a clip with a jarring seam goes behind clean ones
    short_variant: bool = True             # each accepted clip also gets a short version (weakest middle dropped)
    short_sec: float = Field(25.0, gt=0)
    short_min_sec: float = Field(15.0, gt=0)
    # M74 (owner: «начала дают мало контекста; после крючка резко идёт тело»)
    context_start: bool = False            # the first sentence after the hook must not lean on what was cut
    context_max_sec: float = Field(15.0, gt=0)   # … the thought right before may be added as context, this long at most
    context_drop_words: int = Field(5, ge=0)     # … a leaning first sentence this short may be dropped
    plate: str = Field("hook", pattern="^(hook|context)$")   # the model's plate t:: a curiosity headline | what the clip is about
    plate_hookless: str = Field("", pattern="^(|hook|context)$")   # M112: the plate of a clip with no cold open; "" = as plate
    # M75 (M74 report: «Уйти.», «Контролер, да, допустим.», «Хоть это…»; 6 of 15 clips had no pause after the hook)
    context_min_words: int = Field(0, ge=0)      # a start (not a question) shorter than this is a fragment; 0 = off
    context_judge: bool = False                  # the model says whether a first sentence stands on its own
    hook_pause_sec: float = Field(0.0, ge=0.0)   # no pause after the hook → the next of the top hooks that has one; 0 = off
    hook_pause_top: int = Field(3, ge=1)         # … looked for among the model's first this many hooks
    # M76 (M75 report: 11h42 4 → 2 clips, Pxl 5 → 3 — repairable starts were dropped)
    context_back: int = Field(1, ge=1, le=4)     # up to this many thoughts right before may be added as context
    context_later: bool = False                  # the clip may start at a later sentence of its first thought that stands
    context_later_min_sec: float = Field(8.0, gt=0)   # … when at least this much of that thought is left
    # M81 (owner: IMG r03 «начинается с фразы про кресло»): the cold open passes the same model check as the start
    hook_judge: bool = False                     # subject named, makes sense alone, leads into the clip — or it goes
    hook_judge_top: int = Field(6, ge=1)         # … among the first this many hook candidates; none passes = no cold open
    # M86 (M85: «И никогда, ребятки, не поздно.» rejected for leaving a question open — the teaser's job)
    hook_judge_mode: str = Field("start", pattern="^(start|teaser)$")   # teaser: an open question is fine, a pointer back is not
    owner_examples: int = Field(0, ge=0)         # the owner's verdicts (reviews/verdicts.jsonl) as examples for the judges
    judge_cache: bool = False                    # the judges' answers kept between runs (data/cache/autocut_judge.json)
    # M88: the model marks key words (k:) — highlighted in the subtitles, the close shot comes on them (montage.emphasis)
    keywords: bool = False
    keywords_every_sec: float = Field(12.0, gt=0)   # one key word per this many seconds of the clip …
    keywords_max: int = Field(4, ge=0)              # … at most this many
    keywords_voice: bool = False                    # M116 (M1.9 D): words the voice draws out are shown to the model
    keywords_voice_ratio: float = Field(1.25, ge=1.0)   # … duration per letter ≥ this × the sentence's median
    # M91 (ending package): the payoff in the close shot — the last sentences (≥ close_last_sec, at most two) c:
    close_last: bool = False
    close_last_sec: float = Field(3.0, ge=0)
    # M115 (M1.9 C): a clip does not end on a sentence spoken with the voice up («→»; the intonation map, arl prosody)
    end_tone: bool = False
    # M83 (m80: every cold open was the clip's own first sentence — no teaser): the cold open comes from later, replayed
    hook_teaser: bool = False                    # hook candidates only from hook_teaser_pos of the clip on, h:B.N!
    hookless_last: bool = False                  # M107: a clip left without a cold open is taken only when the hooked run out
    hook_teaser_pos: float = Field(0.5, ge=0.0, le=0.95)   # … fraction of the clip's sentences before the candidate
    hook_no_pointer: bool = False                # M92: a teaser pointing back («Это и есть…», «Но…», «Он…») is left out by the code
    # M65: interesting, hooky reels (cloud/autocut.py)
    loop: bool = True
    loop_max_sec: float = Field(20.0, gt=0)
    prune: bool = True
    prune_slack: float = Field(8.0, ge=0)
    hook_min_sec: float = Field(1.5, ge=0)
    hook_llm: str = "auto"                 # auto | cloud | local | none — the model ranks the hook candidates
    speed_slow_rate: float = Field(2.3, gt=0)
    speed_slow: float = Field(1.08, ge=1.0, le=1.2)
    speed_mid_rate: float = Field(2.6, gt=0)
    speed_mid: float = Field(1.05, ge=1.0, le=1.2)


class TxCheckConfig(BaseModel):
    """M57: arl tx-check and clip warnings — Whisper inventions and holes (cloud/txcheck.py).
    Off = no warnings at --apply (invariant 8); the command works either way."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool = False                                  # warn at --apply on clips that play a flagged place
    repeat_words: int = Field(6, ge=3)                     # a verbatim run this long …
    repeat_far_sec: float = Field(60.0, ge=0.0)            # … heard again at least this far away
    sparse_win_sec: float = Field(10.0, gt=0.0)            # window of the «sound without words» check
    sparse_min_speech_sec: float = Field(6.0, gt=0.0)      # … with at least this much speech (speech map)
    sparse_max_rate: float = Field(0.8, gt=0.0)            # … and fewer words per second of speech
    known: list[str] = Field(default_factory=list)         # extra known inventions (added to the built-in list)
    on_speech_sec: float = Field(2.0, ge=0.0)              # M60: speech heard around a flagged place → «на речи»
    sparse_suspicious_sec: float = Field(60.0, ge=0.0)     # M60: this much «sound without words» → suspicious
    punct_chunk_words: int = Field(120, ge=20)             # M113: arl tx-punct --by llm — words the model sees at once


class PostConfig(BaseModel):
    """M94: arl describe — the post under a reel (cloud/postcopy.py). Numbers: config/r0.yaml post:."""

    model_config = ConfigDict(extra="forbid")

    sentences_min: int = Field(3, ge=1)
    sentences_max: int = Field(5, ge=1)
    max_chars: int = Field(700, ge=100)
    hashtags: int = Field(3, ge=0)            # the model's hashtags (said in the reel), after render.yaml hashtags_always
    auto: bool = False                        # M112: arl auto writes the posts (arl describe) before the review sheet


class ArticleConfig(BaseModel):
    """M100: arl article — longreads from the map's topics (cloud/article.py). Numbers: config/r0.yaml article:."""

    model_config = ConfigDict(extra="forbid")

    topics: int = Field(3, ge=1)               # articles per source: the largest real topics
    sections_min: int = Field(3, ge=2)
    sections_max: int = Field(5, ge=2)
    section_sentences_min: int = Field(2, ge=1)
    section_sentences_max: int = Field(8, ge=1)
    section_chars: int = Field(900, ge=200)


class MapConfig(BaseModel):
    """M54: arl map — the map of a whole source (cloud/thoughtmap.py). Numbers: config/r0.yaml."""

    model_config = ConfigDict(extra="forbid")

    system: str = "prompts/map_system.md"
    unit_min_sec: float = Field(8.0, gt=0)
    unit_max_sec: float = Field(30.0, gt=0)
    unit_max_sents: int = Field(4, ge=1)
    pause_split_sec: float = Field(1.0, ge=0)
    window_units: int = Field(20, ge=1)
    similar_min: float = Field(0.30, ge=0, le=1)
    similar_far_sec: float = Field(60.0, ge=0)
    max_missing: float = Field(0.1, ge=0, le=1)     # M66: more thoughts without a passport → the map is incomplete
    topic_chunk: int = Field(0, ge=0)               # M84: more thoughts → topics asked in parts of this many, merged; 0 = one request


class HeavyLockConfig(BaseModel):
    """M108: one lock for every heavy job of gamebox — the audiobook's synthesis, llama-server use, whisper.cpp
    (core/heavy_lock.py). Both sides take `flock` on `path` there; the second comer waits. Numbers: config/r0.yaml."""

    model_config = ConfigDict(extra="forbid")

    host: str = ""                                  # ssh host of the lock; "" = off (no lock, as before)
    path: str = "/mnt/data/locks/heavy.lock"
    llama_unit: str = "llama-server"                # systemd unit of the local model
    start_llama: bool = True                        # start it (sudo -n systemctl start) when it is down
    stop_if_started: bool = True                    # … and stop it again at the end when this side started it
    ready_timeout_sec: float = Field(600.0, ge=10)  # a 27B model takes minutes to load


class AnthropicConfig(BaseModel):
    """M116: Claude through the Messages API — `--llm haiku | sonnet` (paid: the owner's ANTHROPIC_API_KEY in .env).
    Model ids and prices (USD per 1M tokens, input/output) live here, not in the code."""

    model_config = ConfigDict(extra="forbid")

    models: dict[str, str] = Field(default_factory=lambda: {"haiku": "claude-haiku-5-5", "sonnet": "claude-sonnet-5-5"})
    prices: dict[str, list[float]] = Field(default_factory=dict)
    max_output_tokens: int = Field(2048, ge=100)
    timeout_sec: float = Field(120.0, ge=10, le=590)


class LocalLLMConfig(BaseModel):
    """M40: a local OpenAI-compatible server (llama.cpp `llama-server`) for the labeller.
    The address is machine-local: LOCAL_LLM_URL in .env (e.g. http://192.168.1.50:8080/v1)."""

    model_config = ConfigDict(extra="forbid")

    model: str = "local"                           # llama-server serves one model; the name is a label
    timeout_sec: float = Field(540.0, ge=10, le=590)  # a window on an RX 580 takes minutes; < pool budget 600 s
    max_output_tokens: int = Field(1500, ge=100)
    think_max_output_tokens: int = Field(3000, ge=500)   # M116: --llm local-think — the reasoning block counts too
    no_think: bool = True                          # Qwen3: answer without a reasoning block


class R0Config(BaseModel):
    """Типизированный config/r0.yaml. Пресет резолвится в числа через свойства ниже."""

    model_config = ConfigDict(extra="forbid")

    duration_preset: str
    model: str = "qwen/qwen3.6-27b"          # LLM R0 на Groq (основная, сильнее по качеству)
    openrouter_model: str = "mistralai/mistral-small-3.1-24b-instruct:free"
    openrouter_fallback_models: list[str] = Field(
        default_factory=lambda: [
            "meta-llama/llama-3.1-8b-instruct:free",
            "google/gemma-2-9b-it:free",
        ]
    )
    max_output_tokens: int = 900             # Groq free-tier OTPM cap = 1000 tok/min (no header).
                                             # Keep below 1000; 900 gives ~10% headroom.
    provider_strategy: str = "adaptive"      # распределение R0-нагрузки: adaptive | round_robin
                                             # adaptive: Groq основной, слив на OpenRouter под
                                             # троттлом (качество не плавает). round_robin:
                                             # чередовать поровну (макс. пропускная, но половина
                                             # чанков на слабую модель — компромисс качества).
    min_score: int
    min_meaningful_sec: float = 18    # планка «законченной мысли»: сегменты короче снимает
                                      # детерминированный пост-фильтр (выше техн. min_duration).
                                      # Лечит «пустые 15-сек клипы» на длинных видео.
    min_clip_duration: float = 8.0    # пост-snap минимум (snap+padding могут схлопнуть 18с → 1с);
                                      # перед отбросом код пробует расширить до границы фразы.
    max_reels: int | None
    candidate_multiplier: float = 1.75   # over-generation: цель кандидатов = max_reels * это.
                                         # Копим больше, ранжируем по score, режем top-N.
    chunk_tokens: int
    dedup_overlap_threshold: float
    sentence_pause_sec: float
    max_sentence_buffer_sec: float
    tail_sec: float            # хвост при snap к границе слова (технический)
    tail_pad_sec: float = 0.7  # «воздух» после последнего слова клипа (apply_padding)
    lead_pad_sec: float = 0.3  # заход перед первым словом клипа (apply_padding)
    snap_window_sec: float     # окно поиска границы слова/паузы при snap (±сек)
    # Snap «до завершения мысли»: конец клипа тянется до конца предложения (пунктуация) или
    # длинной паузы, пока есть запас до max_duration. Не обрывать на висячих словах/микропаузах.
    min_pause_for_phrase_end: float = 1.5   # пауза > порога = конец мысли. 1.5: thinking-паузы
                                            # спикера 0.7-1.2с (подбирает слово) — НЕ конец;
                                            # реальные разрывы ≥2с — конец. Крутить под спикера.
    review_pause_show_sec: float = 0.3      # пауза ≥ порога → показывать ⏸N.N в компактном ревью.
    review_pause_from_map: bool = False     # M98: ⏸ по паузе на слух (карта речи / выравнивание), не по зазору Whisper
    # Целевая длина блока сегментации (M1.6). Блок НЕ закрывается на «мягкой» границе (конец
    # предложения без паузы — спикер продолжил), пока не набрал этой длины; на «жёсткой» границе
    # (пауза/абзац/смена говорящего) закрывается всегда. Аудит: медиана блоков была 22с при
    # потолке 90, 88-91% границ — мягкие; тянуть до ~40с убирает половину ручных склеек.
    block_target_sec: float = 40.0
    max_micro_pause: float = 0.4            # пауза < порога = микропауза внутри фразы (не конец)
    max_end_search_sec: float = 12.0        # окно поиска конца предложения от r0_end (сек)
    end_repair_max_extend_sec: float = 6.0  # _repair_end: макс прирост к reel.end при продлении
    # Soft minimum-gap rule: if the gap from the clip's last word to the next source word is
    # below min_end_gap_sec, extend the end to the next sentence-terminal word whose following
    # gap is >= target_end_gap_sec, within end_gap_search_sec. Never fires on explicit e:.
    min_end_gap_sec: float = 0.15
    target_end_gap_sec: float = 0.30
    end_gap_search_sec: float = 20.0
    # Fix 1 (video review): плотность речи считается на ГОТОВОМ клипе (после merge/snap/padding).
    # Клип ниже порога сперва пробуют срезать по единой длинной паузе (оставив длинную половину),
    # и только если не вышло — снимают с причиной low_speech_density.
    final_speech_density_min: float = 0.80  # min доля времени клипа под речью (0=выкл проверку)
    speech_density_split_gap_sec: float = 3.0  # единая пауза ≥ этого → срез клипа по ней
    # Предпочтение более длинного клипа: если snap-конец даёт клип КОРОЧЕ ratio·max_duration
    # (грамматически завершён, но мысль спикер развивал дальше и был запас времени), тянуть
    # до следующей чистой границы предложения — максимум на max_extra_sentences вперёд.
    # ratio=0 отключает. Проверяется мгновенно через resnap (LLM не нужен).
    prefer_longer_below_ratio: float = 0.7  # <70% лимита (напр. <63с при 90с) → тянуть дальше
    max_extra_sentences: int = 2            # но не более +2 предложений (чтобы не уйти в др. тему)
    # Two lists, two decisions (a clip's start and its end are not symmetric): a clip must not
    # END on these connectives/prepositions/fillers (they leave the thought hanging)…
    hanging_end_words: list[str] = Field(default_factory=lambda: [
        "и", "а", "но", "что", "это", "как", "в", "на",
        "потому", "чтобы", "если", "когда", "то", "есть", "вот",
        # bare prepositions
        "с", "к", "по", "о", "от", "из", "у", "для", "про",
    ])
    # …but a clip may perfectly well START with most of them ("Если объединить…", "Когда ты…").
    # Only a genuinely dangling opener — a single word that refers back to something before the
    # clip — is repaired away from the start. Much shorter than the end list on purpose. (The
    # matcher is single-token, so multi-word connectives like "то есть"/"так что" fall through;
    # a bare "то"/"так" is not listed because it would also strip "То, что…"/"Так вот…".)
    hanging_start_words: list[str] = Field(default_factory=lambda: [
        "и", "а", "но", "поэтому", "потому",
    ])
    dangling_words: list[str] = Field(default_factory=list)  # extra blocklist for dangling_start gate
    host_affirmations: list[str] = Field(default_factory=list)  # tail sentences to trim (case-insensitive)
    max_start_repair_sec: float = 10.0  # scan window to find a sentence-initial word when repairing a dangling start
    source_kind: str = "lecture"  # "lecture" | "interview"
    host_turn_min_pause: float = 0.7  # pause before a sentence to count it as a host turn (interview)
    too_long_policy: str = "trim"   # trim | drop | keep (что делать с флагом too_long)
    title_style: str
    language: str
    presets: dict[str, Preset]
    prompts: PromptPaths
    chunking: ChunkingConfig = Field(default_factory=ChunkingConfig)
    blocks_filter: BlocksFilterConfig = Field(default_factory=BlocksFilterConfig)
    block_scoring: BlockScoringConfig = Field(default_factory=BlockScoringConfig)
    manual_max_duration_sec: float = 180.0  # ceiling for human-review merges (source span)
    beat_gap_sec: float = 0.25  # silence gap appended to each beat segment at --apply time
    seam_pad_sec: float = 0.04  # gap added/removed at internal seam cuts (smap audible boundary ± pad)
    start_pad_sec: float = Field(0.0, ge=0.0, le=0.5)   # M142: air before a clip's first sound; 0 = seam_pad_sec
    start_preroll_sec: float = Field(0.0, ge=0.0, le=0.2)  # M146: a glued first word starts this much earlier; 0 = off
    speed: float = 1.0                       # default playback speed for all clips
    filler_removal: FillerRemovalConfig = Field(default_factory=FillerRemovalConfig)
    # Trailing "pure wind-down" sentences dropped when the review gives no explicit end (e:).
    # A sentence is pure wind-down when, after dropping filler words, its text is empty or equals
    # one of these phrases (see cloud/edit.default_end_sentence).
    wind_down_phrases: list[str] = Field(default_factory=lambda: [
        "наверное, как-то так", "вот", "да", "понятно", "как-то так", "ну вот",
    ])
    # Whisper credit hallucination phrases to strip at word level (consecutive token match,
    # case-insensitive, punctuation-stripped). Applied once at transcript load.
    credit_word_patterns: list[str] = Field(default_factory=lambda: [
        "Субтитры создавал",
        "Субтитры делал",
        "Редактор субтитров",
        "DimaTorzok",
        "Продолжение следует",
    ])

    # Cold open (Part 5): a hook sentence (h:N) longer than this is refused with a warning.
    hook_max_sec: float = 6.0
    # Hook replay position rule: keep the hook in the body only if its sentence start lies at or
    # after this fraction of the body duration (0.5 = second half). h:N! forces keep; h:N- forces remove.
    hook_replay_min_pos: float = 0.5
    # docs/REEL_SPEC.md: human-path clips are built by ONE pure plan (cloud/plan.py) — windows,
    # shots, ending and subtitles from the review line — instead of the boundary-moving stages.
    # Off = the previous output (invariant 8).
    manual_plan: bool = False
    # M2.1: planned clips need the forced alignment (arl align → transcripts/<stem>.align.json);
    # True = --apply refuses without it. False = falls back to speech-map times with a warning.
    require_alignment: bool = False
    # Shot rule (REEL_SPEC §3): a close shot after a seam lasts accent_min..accent_max seconds.
    accent_min_sec: float = 3.0
    accent_max_sec: float = 8.0
    # M2.2: sentence-end intonation (arl prosody → transcripts/<stem>.prosody.json): the plan reports
    # an ending whose voice does not finish; the review export marks such sentences with ↗.
    # Off (or no prosody file) = the previous output (invariant 8).
    intonation_check: bool = False
    # REEL_SPEC §1.4: planned clips cut fillers («э», «ммм») and over-long pauses inside a window
    # (aligned word times + untranscribed speech). Per clip f:1/f:0 > --filler/--no-filler > this.
    # Thresholds: ManualPlanParams in cloud/plan.py. Off = the previous output (invariant 8).
    manual_filler_cut: bool = False
    # Balance presets for the filler cut (jump_max, min_cut_spacing_sec, jump_mask, …) and the default.
    manual_filler_profile: str | None = None
    manual_filler_profiles: dict[str, dict[str, float | bool]] = Field(default_factory=dict)
    # M79: a pause at least this long inside a planned clip is always shortened (a visible jump masked by a shot
    # switch; the profile's spacing rules do not hold it back). 0 = off.
    long_pause_sec: float = Field(0.0, ge=0.0)
    # M126 (owner: «много вводных слов у человека, который говорит»; «2 можно делать не часто»): standalone filler words
    # (filler_removal.filler_words) hidden from the subtitles / cut from the sound under the filler cut's rules
    subtitles_hide_fillers: bool = False
    filler_word_cut: bool = False
    # arl label: draft review lines by the LLM, checked by code (defaults in LabelConfig).
    label: LabelConfig = Field(default_factory=LabelConfig)
    local_llm: LocalLLMConfig = Field(default_factory=LocalLLMConfig)
    anthropic: AnthropicConfig = Field(default_factory=AnthropicConfig)
    heavy_lock: HeavyLockConfig = Field(default_factory=HeavyLockConfig)
    montage: MontageConfig = Field(default_factory=MontageConfig)
    map: MapConfig = Field(default_factory=MapConfig)
    tx_check: TxCheckConfig = Field(default_factory=TxCheckConfig)
    autocut: AutocutConfig = Field(default_factory=AutocutConfig)
    post: PostConfig = Field(default_factory=PostConfig)
    article: ArticleConfig = Field(default_factory=ArticleConfig)

    @property
    def min_duration(self) -> int:
        """Нижняя граница длины клипа (сек) активного пресета."""
        return self.presets[self.duration_preset].min

    @property
    def max_duration(self) -> int:
        """Верхняя граница длины клипа (сек) активного пресета."""
        return self.presets[self.duration_preset].max

    @property
    def target_candidates(self) -> int | None:
        """Целевое число кандидатов для over-generation (max_reels * candidate_multiplier).

        None когда max_reels=null (over-generation выключено → «вернуть все качественные»)."""
        if self.max_reels is None:
            return None
        return max(self.max_reels, round(self.max_reels * self.candidate_multiplier))

    @model_validator(mode="after")
    def _sync_block_min_sec(self) -> "R0Config":
        """Keep block_scoring.min_sec in sync with min_meaningful_sec (single source of truth)."""
        self.block_scoring.min_sec = self.min_meaningful_sec
        return self

    @property
    def max_sentence_sec(self) -> float:
        """Порог дробления строк compress: max_duration пресета + запас.

        Привязан к пресету, чтобы НЕ рубить легальные моменты длиной до max_duration;
        дробятся только строки-гиганты длиннее этого порога.
        """
        return self.max_duration + self.max_sentence_buffer_sec


# ------------------------------------------------------------------------ Render

class CodecProfile(BaseModel):
    """Один кодек-профиль: связка ffmpeg-кодек + целевой битрейт.

    Кодек и битрейт связаны неразрывно (h264 нужен выше битрейт, hevc/av1 — ниже при том
    же качестве), поэтому живут в одной записи, а не в двух независимых таблицах.
    """

    model_config = ConfigDict(extra="forbid")

    codec: str        # ffmpeg-энкодер (h264_amf | hevc_amf | av1_amf | libx264 | …)
    bitrate: str      # целевой битрейт (напр. '5M'); при rate_control='cqp' игнорируется
    # Качество AMF (аппаратный кодер): часто важнее битрейта. Диагностика показала, что softness
    # на равном битрейте — от AMF, а не от 5 Мбит/с. Применяются ТОЛЬКО к *_amf кодекам.
    quality: str | None = None        # -quality: quality | balanced | speed (дефолт AMF — balanced)
    rate_control: str | None = None   # 'cqp' → -rc cqp + qp (лучше качество, размер непредсказуем);
                                      # иначе (None/'vbr') — целевой битрейт (предсказуемый размер)
    qp: int | None = None             # базовый QP для cqp (qp_i=qp, qp_p=qp+2); ниже = качественнее
    label: str = ""                   # заметка для меню: скорость/качество


# Дефолтные профили: prod — системник Windows AMD (AMF-энкодеры).
_DEFAULT_PROFILES: dict[str, dict] = {
    "h264":    {"codec": "h264_amf", "bitrate": "7M", "quality": "quality",
                "label": "быстро, совместимый (дефолт, web-safe)"},
    "hevc":    {"codec": "hevc_amf", "bitrate": "5M", "quality": "quality",
                "label": "быстро, компактный (web-плееры перекодируют)"},
    "hevc_hq": {"codec": "hevc_amf", "bitrate": "12M", "quality": "quality",
                "rate_control": "cqp", "qp": 18, "label": "быстро, лучше качество (крупнее файл)"},
    "h264_hq": {"codec": "h264_amf", "bitrate": "16M", "quality": "quality",
                "label": "быстро, лучше, совместимый (крупный файл)"},
    "hevc_sw": {"codec": "libx265", "bitrate": "5M",
                "label": "МЕДЛЕННО, максимум качества (для избранных клипов)"},
    "av1":     {"codec": "av1_amf", "bitrate": "4M", "label": "экспериментально, компактно"},
}


class Encoder(BaseModel):
    """Видеоэнкодер + rate-control под соцсети.

    Кодек выбирается ПРОФИЛЕМ (`profiles[profile]`): каждый профиль — связка кодек+битрейт.
    h264 (безопасный, универсальный, DELIVERY-дефолт) / hevc (компактный) / av1 (экспериментальный).
    Размер файла контролируется ЦЕЛЕВЫМ БИТРЕЙТОМ, а не CRF: битрейт предсказуемо задаёт
    размер (30с ≈ битрейт×30/8) одним проходом и, главное, работает на аппаратном AMF
    (который без rate-control раздувает файл в разы — отсюда прежняя нужда дожимать HandBrake).
    `cq` оставлен для совместимости конфига.
    """

    model_config = ConfigDict(extra="forbid")

    profile: str = "h264"                    # DELIVERY-дефолт H.264 High (web-совместимый); hevc — явно
    profiles: dict[str, CodecProfile] = Field(
        default_factory=lambda: {k: CodecProfile(**v) for k, v in _DEFAULT_PROFILES.items()}
    )
    preset: str
    cq: int
    pix_fmt: str = "yuv420p"                 # универсальная совместимость соцсетей/плееров
    faststart: bool = True                   # moov-atom в начало (соцсети требуют для стрима)

    @property
    def active(self) -> CodecProfile:
        """Активный кодек-профиль (по имени `profile`)."""
        return self.profiles[self.profile]

    @property
    def codec(self) -> str:
        """ffmpeg-кодек активного профиля (напр. 'hevc_amf')."""
        return self.active.codec

    @property
    def video_bitrate(self) -> str:
        """Целевой битрейт активного профиля (напр. '5M')."""
        return self.active.bitrate


class Audio(BaseModel):
    model_config = ConfigDict(extra="forbid")

    codec: str
    bitrate: str


class AudioProcessing(BaseModel):
    """Обработка звука клипа. Порядок фильтров: шумоподавление → нормализация → фейд."""

    model_config = ConfigDict(extra="forbid")

    # Нормализация громкости (loudnorm) — ГЛАВНОЕ: единый уровень для всех клипов (стандарт
    # соцсетей -14 LUFS). Однопроходный: для клипов 30-60с точности достаточно, двухпроходный
    # (медленнее, +проход анализа) не нужен. Включено по умолчанию.
    loudnorm_enabled: bool = True
    target_lufs: float = -14.0     # I=  (целевая интегральная громкость, LUFS)
    true_peak: float = -1.5        # TP= (потолок истинного пика, дБ)
    # M147: dynamic = one-pass loudnorm per clip (its gain settles in the first second: −2.4 dB in the first 0.3 s, m143);
    # source = one gain for the whole source (measured once), a peak limiter — no settling, clips of a source equally loud
    loudnorm_mode: str = "dynamic"
    static_gain_db: float | None = None   # set by the render for loudnorm_mode: source (not in yaml)
    loudness_range: float = 11.0   # LRA=
    # Шумоподавление (afftdn) — ВЫКЛ по умолчанию: агрессивно может съедать голос.
    denoise_enabled: bool = False
    denoise_strength: float = 12.0   # afftdn nr= (сила подавления, дБ)
    # Фейд видео+звука в начале/конце (убирает резкий старт/обрыв). ВЫКЛ по умолчанию.
    # Хвост фейд-аута ложится на padding-«воздух» в конце клипа — не режет речь.
    fade_enabled: bool = False
    fade_duration: float = 0.25      # секунды (0.2-0.3 обычно)
    # Аудио-фейд в САМОМ конце клипа (только звук, БЕЗ видео-фейда в чёрное). Два режима:
    # CLEAN — чистый хвост (нет следующего слова): fade только последних tail_fade_sec, дыхание слышно.
    # Оба случая вычисляются из tail_last_word_end/tail_next_word_start манифеста при рендере.
    tail_fade_sec: float = 0.35          # clean tail: длина fade в конце клипа
    last_word_margin_sec: float = 0.2   # safety margin added after last subtitle word's t1 on every path
    # Микро-фейд на КРАЯХ каждого аудиосегмента многосегментного клипа (гасит щелчок на склейке).
    # НЕ кроссфейд: fade-out в конце сегмента + fade-in в начале следующего, затем обычный concat —
    # без перекрытия, поэтому длина звука в ТОЧНОСТИ равна длине видео (нет дрейфа губ-синка). Только
    # клипы с >1 сегментом; одиночный span не затрагивается. 0 → встык без фейдов.
    audio_edge_fade_sec: float = 0.01
    start_fade_in_sec: float = Field(0.0, ge=0.0, le=0.2)   # M146: the clip's sound fades in over this (pre-roll); 0 = off
    # Видео-кроссфейд на каждом внутреннем шве многосегментного клипа (xfade-фильтр). Сглаживает
    # «прыжок» при смене позы (холодный старт, склейки). Аудио НЕ кроссфейдируется — остаётся concat,
    # иначе укорочение аудио вернуло бы дрейф. Выход короче суммы сегментов на (N−1)×xfade_sec.
    # Длительность снаппится к сетке кадров при рендере. 0 → жёсткий concat (байт-идентичен старому).
    video_xfade_sec: float = 0.08
    # Видео-фейд в чёрное в конце клипа, синхронный с аудио-хвостовым фейдом. ВЫКЛ по умолчанию.
    # CLEAN хвост: fade той же длины, что audio tail_fade_sec (одинаковый старт и длина).
    # INTRUDED хвост: короткий fade tail_video_fade_min_sec в самом конце клипа.
    # Фейд ПОСЛЕ субтитров — субтитры уходят вместе с картинкой. Не меняет длину.
    tail_video_fade: bool = False
    tail_video_fade_min_sec: float = 0.25
    # Dynamic ending: clips end with a fast fade to black, no frozen frame.
    # When on (default): no synthetic frozen tail; end = last audible word + end_air_sec (never
    # later than next onset − onset_margin_sec); video fades to black over end_video_fade_sec;
    # audio fades over end_audio_fade_sec; last frame is black.  Off = legacy behaviour
    # (synthetic_tail_cfg / tail_video_fade / tail_fade_sec / r0 tail_pad_sec).
    dynamic_ending: bool = True
    end_air_sec: float = 0.30            # air after the last audible word (replaces the long tail pad)
    end_audio_fade_ms: int = 40          # legacy declick; superseded by end_audio_fade_sec below
    end_audio_fade_sec: float = 0.25     # audio fade-out at clip end (dynamic_ending)
    end_video_fade_sec: float = 0.25     # video fade to black at clip end (dynamic_ending)


class AudioExtract(BaseModel):
    """Параметры извлечения аудиодорожки под Whisper (cloud/extract_audio.py)."""

    model_config = ConfigDict(extra="forbid")

    sample_rate: int
    channels: int
    codec: str
    format: str
    bitrate: str | None = None   # напр. "64k" для mp3; None для PCM (bitrate неприменим)


class Music(BaseModel):
    """Фоновая музыка под речь. Микс: речь → шумоподавление → нормализация → микс с музыкой →
    финальная нормализация (анти-клиппинг). Музыка заметно тише голоса. ВЫКЛ по умолчанию."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool = False
    file: str | None = None        # трек: путь (абсолютный или относительно music/)
    random: bool = False           # случайный трек из music/ (разнообразие)
    volume: float = 0.13           # громкость музыки (0..1) — тише голоса
    fade_seconds: float = 2.0      # фейд музыки в начале/конце
    ducking: bool = False          # приглушать музыку под речь (sidechaincompress)
    final_normalize: bool = True   # финальная нормализация микса (сумма не клиппит)


class Zoom(BaseModel):
    """Эффект зума (акцент на моменте). Качество: зум берётся ИЗ ИСХОДНОГО разрешения —
    zoompan сэмплит уже вырезанный полноразмерный регион и выводит 1080×1920 (динамический
    кроп меньшей области), НЕ апскейлит готовый кадр. ВЫКЛ по умолчанию."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool = False
    percent: float = 8.0        # величина наезда, % (8% = z до 1.08)
    duration: float = 0.25      # секунды на наезд и на возврат
    scheme: str = "hook"        # hook (лёгкий зум в начале + возврат) | none
    hook_seconds: float = 2.5   # длина hook-жеста от начала клипа (наезд+удержание+возврат)
    fps: int = 30               # ignored: renderer follows source fps to prevent A/V drift


class PaletteEq(BaseModel):
    """eq-фильтр цветокоррекции. Дефолты = нейтрально (картинка не меняется)."""
    model_config = ConfigDict(extra="forbid")
    brightness: float = 0.0   # -1..1
    contrast: float = 1.0     # 0..2
    saturation: float = 1.0   # 0..3
    gamma: float = 1.0        # 0.1..10


class PaletteUnsharp(BaseModel):
    """unsharp (резкость). ВЫКЛ по умолчанию — перебор даёт звон по контурам, соцсети усилят."""
    model_config = ConfigDict(extra="forbid")
    enabled: bool = False
    luma_msize_x: int = 5
    luma_msize_y: int = 5
    luma_amount: float = 0.8


class PaletteCurves(BaseModel):
    """Тени/света через curves. Шкала ПОНЯТНАЯ снаружи (-100..+100), пересчёт в точки кривой —
    в рендере. 0 = нейтрально (curves вообще не добавляется). shadows +N поднимает нижнюю часть
    кривой (вытягивает тени), highlights -N прибирает верхнюю (приглушает света). Концы кривой
    зафиксированы — крайние значения не выбивают детали в чёрном/белом (без клиппинга).
    Осторожно: подъём теней вытаскивает шум из тёмных участков (телефон в помещении — заметно)."""
    model_config = ConfigDict(extra="forbid")
    shadows: int = Field(default=0, ge=-100, le=100)
    highlights: int = Field(default=0, ge=-100, le=100)


class Palette(BaseModel):
    """Пресет палитры: curves + eq + unsharp + опц. цветовая температура. neutral = всё по дефолтам."""
    model_config = ConfigDict(extra="forbid")
    curves: PaletteCurves = Field(default_factory=PaletteCurves)
    eq: PaletteEq = Field(default_factory=PaletteEq)
    unsharp: PaletteUnsharp = Field(default_factory=PaletteUnsharp)
    colortemperature: int | None = None   # Кельвины; <6500 теплее, >6500 холоднее; None = выкл
    label: str = ""                       # заметка для меню


# Готовые пресеты палитры (значения — не хардкод в коде рендера).
_DEFAULT_PALETTES: dict[str, dict] = {
    "neutral": {"label": "без изменений (дефолт)"},
    "vivid":   {"eq": {"saturation": 1.15, "contrast": 1.10},
                "label": "живее: насыщенность +15%, контраст +10% (соцсети)"},
    "soft":    {"eq": {"contrast": 0.95, "saturation": 1.05}, "colortemperature": 5400,
                "curves": {"shadows": 10},
                "label": "мягче + теплее, тени +10 (talking-head)"},
    "sharp":   {"eq": {"contrast": 1.05}, "unsharp": {"enabled": True, "luma_amount": 0.6},
                "label": "умеренный unsharp + лёгкий контраст"},
}


class SyntheticTailConfig(BaseModel):
    """M1.8: synthetic tail appended when real room after last word is too short.

    enabled: master switch (default off — renders byte-identical to pre-feature).
    min_room_sec: room threshold; below this the synthetic tail fires.
    keep_sec: real source kept past audible_end before the cut (no fade on speech).
    tail_sec: duration of the synthetic tail (room tone + slowed/frozen video).
    fade_sec: audio+video fade-out at the end of the synthetic tail.
    push: optional slow push-in zoom on the frozen/slowed frame (default off).
    """

    model_config = ConfigDict(extra="forbid")

    enabled: bool = False
    min_room_sec: float = 0.60
    keep_sec: float = 0.15
    tail_sec: float = 1.0
    fade_sec: float = 0.60
    push: bool = False


class SpeechMapConfig(BaseModel):
    """M1.8 Stage B: параметры energy-based speech map.

    All fields here are part of the map cache key (except cut_pause_min_sec which is a
    consumer threshold only).  Changing any field invalidates cached .speechmap.json files.
    """

    model_config = ConfigDict(extra="forbid")

    # Energy detection parameters (affect interval detection, part of params_hash)
    frame_sec: float = 0.01          # energy window length
    noise_percentile: float = 10.0   # noise floor = Nth percentile of frame energies
    headroom_db: float = 15.0        # threshold = noise_floor + headroom_db
    min_silence_sec: float = 0.05    # minimum silence duration to split intervals
    pause_min_sec: float = 0.15      # minimum pause to count as a word boundary
    # Residue filter parameters (affect untranscribed_speech, part of params_hash)
    min_edge_dist: float = 0.060     # interval within this distance of a word edge → residue, dropped
    untranscribed_min_sec: float = 0.100  # minimum duration for a detached interval to count
    # Consumer thresholds / render-stage params (NOT in params_hash — like cut_pause_min_sec)
    # Rationale: voiceless stop closures (e.g. "т" in "такая?") produce genuine energy gaps
    # of ~0.3 s that are continuous speech by ear — see regression case #568 (0.29 s).
    cut_pause_min_sec: float = 0.35
    tail_pad_sec: float = 1.50      # max silence air after audible_end at render stage
    onset_margin_sec: float = 0.06  # guard kept before next speech onset
    fade_keep_sec: float = 0.20     # unfaded air right after audible_end before fade begins
    # Own-word-tail filter: a short untranscribed interval immediately after the last word
    # that is separated from the next speech by real silence is the word's own acoustic decay.
    # Extend audible_end past it so it is not mistaken for the next speech onset (N).
    own_tail_window_sec: float = 0.30   # interval must start within this distance after ae
    own_tail_short_sec: float = 0.25    # interval must be shorter than this (duration rule)
    own_tail_gap_min_sec: float = 0.10  # gap from interval end to next word audible_start
    # Whisper-t1 hint: if the interval contains (or ends within this margin of) last_t1,
    # it is the word's own tail regardless of its length.
    own_tail_t1_margin_sec: float = 0.15  # iv_e <= last_t1 + margin → own tail (Whisper hint)


class RemoteRender(BaseModel):
    """M161: render on another machine over ssh (local/remote.py)."""
    host: str = ""                        # ssh name; "" = off
    root: str = ""                        # project folder there
    encoder: str = "h264_vaapi"           # RX 580: HEVC breaks long clips (m160), H.264 is clean
    profile: str = "h264"
    lock: str = ""                        # flock file of the shared heavy lock there ("" = none)


class RenderConfig(BaseModel):
    """Типизированный config/render.yaml."""

    model_config = ConfigDict(extra="forbid")

    scale: list[int]
    encoder: Encoder
    audio: Audio
    audio_extract: AudioExtract
    ffmpeg: str = "ffmpeg"   # путь к ffmpeg-бинарю; Windows: D:\ffmpeg\bin\ffmpeg.exe
    audio_processing: AudioProcessing = Field(default_factory=AudioProcessing)
    music: Music = Field(default_factory=Music)
    zoom: Zoom = Field(default_factory=Zoom)
    palette: str = "neutral"                 # активная палитра (--palette / render.local.yaml)
    palettes: dict[str, Palette] = Field(
        default_factory=lambda: {k: Palette(**v) for k, v in _DEFAULT_PALETTES.items()}
    )
    role: str = "both"        # "analyze" | "render" | "both" (machine-local, render.local.yaml)
    auto_render: bool = False   # авто-рендер после анализа (machine-local, render.local.yaml)
    parallel_render: bool = True  # рендер в фоне пока идёт следующий анализ (render.local.yaml)
    # Hashtags for publish sidecars. hashtags_always: fixed tags for every clip of this source
    # (e.g. speaker's topic area). hashtags_max: total cap including always-tags.
    hashtags_always: list[str] = Field(default_factory=list)
    hashtags_max: int = 5
    # M1.7 step 1: two-shot switching (wide/close crop within a clip). Off by default — feature-off
    # renders are byte-identical (or same argv when encoder is non-deterministic).
    two_shot: bool = False
    two_shot_xfade: bool = False   # crossfade at shot-change seams instead of hard cut
    close_shot_scale: float = 1.25  # close shot is this many times tighter than wide
    close_shot_anchor_y: float = 0.35  # anchor point: 35% of wide height stays at 35% of close height
    # M1.7 step 1b: automatic shot alternation at seams (requires two_shot: true).
    two_shot_auto: bool = False          # auto-alternate wide/close at x:/splice/filler seams
    # Human clips (selection_source=human): allow auto-alternation. Default False = seams and c: only.
    two_shot_auto_human: bool = False
    two_shot_max_shot_sec: float = 9.0   # force a switch if any shot (wide OR close) exceeds this
    two_shot_min_sec: float = 2.5        # suppress a switch that would create a shorter shot
    two_shot_min_middle_sec: float = 4.0  # A-B-A middle span shorter than this is merged away
    shot_tolerance_frames: int = 2        # verifier frame tolerance for span floor checks
    # M1.7 step 3: beat-clip shot rule. Shot changes ONLY at jump seams for beat reels.
    beat_clip_shots_only_at_seams: bool = True
    # Fallback gap threshold for is_jump_seam when sentence words are not available.
    jump_seam_gap_sec: float = 2.0
    # M1.7 step 1d: shot-change transitions inside close_intervals windows. Off by default.
    # Flag off → identical cmd. M103: "punch" — over punch_sec before a close shot that comes inside a window the
    # wide frame zooms into it (local/fx.push_vf), the switch lands on it; seams and filler cuts stay hard cuts.
    shot_transition: str = "cut"         # "cut" | "punch" (arl render --transition)
    punch_sec: float = Field(0.3, gt=0, le=1.0)
    # M1.7 step 1d: dissolve on same-shot seams (filler/splice without shot change). Off by default.
    # 0 = disabled (falls back to video_xfade_sec). Flag off → identical cmd.
    same_shot_dissolve_frames: int = 0   # dissolve duration in frames (0 = disabled)
    # M1.8: energy-based speech map — off by default (Stage A; no consumers yet)
    speech_map: bool = False
    # M1.8 Stage B: speech map parameters (cache key + consumer thresholds)
    speech_map_cfg: SpeechMapConfig = Field(default_factory=SpeechMapConfig)
    # M1.8 Stage B consumer 2: synthetic tail (room tone + slowed/frozen video). Off by default.
    synthetic_tail_cfg: SyntheticTailConfig = Field(default_factory=SyntheticTailConfig)

    @property
    def two_shot_max_wide_sec(self) -> float:
        """Backward-compat alias for two_shot_max_shot_sec."""
        return self.two_shot_max_shot_sec

    # M1.7 step 2: per-word keyword highlighting in subtitles. Off by default — feature-off
    # renders are byte-identical. k: review field specifies words per sentence.
    subtitle_keywords: bool = False
    # M89: <reel>.cover.jpg next to every rendered clip (a frame in the reel's crop and colour + its plate). The clip
    # itself is unchanged; off = no file.
    cover: bool = False
    # M96: the cover frame is the moment (of 7 in the body) with the largest face and open eyes (OpenCV); off or no
    # OpenCV = the middle of the longest body window (M89).
    cover_face: bool = False
    # M97 (ending package, PLAN M1.7 B): a clip whose last thought goes on past its end (open_thought) shows
    # continue_text in the title plate over its last continue_sec seconds. Off = the clip as before.
    continue_plate: bool = False
    # M151 (ending package, PLAN M1.7 B — owner: «просто чтобы была такая опция»): options, all off
    ending_loop: bool = False             # a clip with a cold open does not fade to black — it loops into its teaser
    end_freeze_sec: float = Field(0.0, ge=0.0, le=5.0)   # hold the last frame this long after the clip, then black
    end_sting_path: str = ""              # a sound played after the clip ends (under the held frame); "" = none
    end_sting_volume: float = Field(0.8, ge=0.0, le=2.0)
    remote: RemoteRender = Field(default_factory=RemoteRender)   # M161: arl render --remote, arl auto --remote
    continue_sec: float = Field(2.5, gt=0)
    continue_text: str = "Продолжение →"
    # M102 (owner: «чтобы кадры подбирались автоматически… динамика кадра для удержания внимания»): where the face
    # is in each reel — framing_samples frames over its body (OpenCV); the place seen in at least framing_min_share
    # of them counts. reel_framing: the reel's own frame — the source's crop moved sideways so this reel's face is
    # in its middle when it is more than framing_center_zone of the crop width away (static within the reel, no
    # tracking). close_from_face: the close shot from the face — the face box close_face_h of the frame height,
    # its centre at close_face_y from the top; the scale within close_min_scale…close_max_scale and an upscale to
    # the output height of at most close_max_upscale. No face / no OpenCV — as before. Both off = as before.
    reel_framing: bool = False
    close_from_face: bool = False
    framing_samples: int = Field(7, ge=1)
    framing_min_share: float = Field(0.4, gt=0, le=1)
    framing_center_zone: float = Field(0.15, ge=0, le=0.5)
    close_face_h: float = Field(0.28, gt=0, lt=1)
    close_face_y: float = Field(0.40, gt=0, lt=1)
    close_max_upscale: float = Field(2.5, ge=1)
    close_max_scale: float = Field(1.6, ge=1)
    close_min_scale: float = Field(1.15, ge=1)
    # M127 (owner on Pxl 112938952 m125: «фокус взят на чайник» — 12 of 16 reels found no face of their own and kept
    # the source's frame, the middle): a reel without its own face is framed on the speaker's place in the whole
    # source (framing_source_samples frames, the dominant place seen in ≥ framing_source_min_faces). Off = as before.
    framing_source_fallback: bool = False
    framing_source_samples: int = Field(40, ge=1)
    framing_source_min_faces: int = Field(4, ge=1)
    # M129 (m128 on Pxl 112938952: the Haar cascade framed the reels on a shelf of teapots, YuNet found the face in 12 of
    # 12 frames): the YuNet face model (OpenCV FaceDetectorYN) for the reel framing; "" or no file = the Haar cascade
    face_model: str = ""

    @field_validator("shot_transition")
    @classmethod
    def _validate_transition(cls, v: str) -> str:
        if v not in ("cut", "punch"):
            raise ValueError(f"shot_transition must be 'cut' or 'punch'; got '{v}'")
        return v

    @field_validator("role")
    @classmethod
    def _validate_role(cls, v: str) -> str:
        if v not in ("analyze", "render", "both"):
            raise ValueError(f"role must be 'analyze', 'render', or 'both'; got '{v}'")
        return v

    @property
    def active_palette(self) -> Palette:
        """Активный пресет палитры (по имени `palette`)."""
        return self.palettes[self.palette]


# ----------------------------------------------------------------------- Subtitles

class SubtitlesConfig(BaseModel):
    """Типизированный config/subtitles.yaml — стиль выжигаемых субтитров (R3).

    Все параметры числами/строками-числами, чтобы крутить стиль без кода (UI-крутилку
    осознанно отложили). Цвета — RRGGBB; в ASS уходят как &HAABBGGRR (см. subtitles.ass_color).
    """

    model_config = ConfigDict(extra="forbid")

    font: str
    font_size: int
    text_color: str
    bold: bool
    uppercase: bool
    outline_color: str
    outline_width: int
    shadow: int
    fill_enabled: bool
    fill_color: str
    fill_opacity: int          # % непрозрачности подложки-бокса (если fill_enabled)
    position_v: int            # MarginV — подъём от низа кадра
    words_per_line: int
    subtitle_break_pause_sec: float   # пауза-граница фразы рвёт группу субтитров (R3-fix)
    fade_in_ms: int            # плавное появление группы (\fad); 0 = без fade
    fade_out_ms: int           # плавное исчезновение группы (\fad); 0 = без fade
    alignment: str             # center | left | right
    char_width_ratio: float    # оценка ширины символа (доля font_size) для подгонки строки
    max_text_width_px: int     # макс. ширина строки в px
    # Title plate (Part 4): overlay at the TOP for the first seconds, above the subtitle zone.
    # Rendered only when a reel carries title_overlay (review `t:`). Defaults keep old subtitles.yaml
    # valid; title_font_size 0 → reuse font_size.
    title_lead_sec: float = 3.5       # seconds the plate stays on
    title_font_size: int = 0          # 0 → same as font_size
    title_position_v: int = 150       # MarginV from the TOP (alignment 8, top-centre)
    title_fade_ms: int = 250          # plate fade in/out
    # Keyword style (M1.7 step 2): applied to words marked in review `k:N=word,...`.
    # Only rendered when subtitle_keywords=True in RenderConfig AND k: is present; otherwise
    # output is byte-identical. Font size unchanged (size change reflows the line).
    keyword_color: str = "FFE000"     # bright yellow — readable on dark and light backgrounds
    keyword_bold: bool = True
    # M55 attention effects (used only when a reel carries fx; otherwise no effect on the output).
    karaoke_color: str = "4CFF4C"     # the word being spoken (karaoke subtitles)
    callout_color: str = "FFE000"     # big phrase / number (o: in a montage line)
    callout_font_size: int = 0        # 0 → 1.5 × font_size
    callout_lift: int = 260           # px above the subtitle line (MarginV = position_v + lift)
    progress_color: str = "FFFFFF"    # progress bar along the bottom edge
    progress_height: int = 8          # px


# --------------------------------------------------------------------- Transcribe

class GroqWhisper(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model: str = "whisper-large-v3"
    # Priming-текст: Whisper копирует пунктуационный стиль initial_prompt. Русская
    # разговорная речь (лекция/интервью) без него теряет точки/вопросы → пропадает
    # sentence-путь snap'а. Прайм короткой хорошо пунктуированной прозой в том же
    # регистре. Пустая строка = не слать prompt (старое поведение).
    #
    # ОГРАНИЧЕНИЕ: текст должен быть самодостаточным и законченным — НЕ начинаться
    # как реплика диктора (нет «я расскажу», «сейчас разберём», вопросов к аудитории).
    # Незавершённый нарратив Whisper дописывает в начало транскрипта — утечка промпта
    # в субтитры. Используйте нейтральные, завершённые предложения без первого лица.
    initial_prompt: str = (
        "Тема сегодняшней беседы — психология принятия решений. "
        "Специалисты выделяют несколько ключевых факторов. "
        "Каждый из них влияет на результат по-своему."
    )
    # M124: two passes — words without the prompt, sentence ends with it (cloud/transcribe.py GroqDualBackend)
    dual: bool = False


class FasterWhisperParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model_size: str = "large-v3"
    device: str = "cpu"
    compute_type: str = "int8"


class WhisperCppParams(BaseModel):
    """M62: whisper.cpp over ssh (cloud/transcribe.WhisperCppBackend). Paths are the remote ones;
    `$W` etc. come from `env` sourced first."""

    model_config = ConfigDict(extra="forbid")

    host: str = "gamebox"                       # ssh host; "" = run on this machine
    env: str = "~/llama.env"                    # sourced before the command ("" = none)
    cli: str = "~/whisper.cpp/build/bin/whisper-cli"
    model: str = "$W/ggml-large-v3-turbo.bin"
    vad_model: str = "$W/ggml-silero-v5.1.2.bin"   # "" = no VAD
    language: str = "ru"
    threads: int = 8
    max_context: int = 0                        # -mc: 0 = no prompting from the previous text
    extra_args: str = ""
    remote_dir: str = "~/autoreels_tx"
    prompt: str = ""                            # M64: --prompt (punctuation style); "" = none
    prompt_context: int = 64                    # M64b: -mc used with a prompt when max_context is 0 (0 drops it)


class TranscribeConfig(BaseModel):
    """Типизированный config/transcribe.yaml. backend отсюда, ключ — из env."""

    model_config = ConfigDict(extra="forbid")

    backend: str = "groq"
    language: str = "ru"
    groq: GroqWhisper = Field(default_factory=GroqWhisper)
    faster_whisper: FasterWhisperParams = Field(default_factory=FasterWhisperParams)
    whispercpp: WhisperCppParams = Field(default_factory=WhisperCppParams)


# ------------------------------------------------------------------------ readers

def _read_yaml(path: Path) -> dict:
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError as e:
        raise ConfigError(f"не удалось прочитать конфиг {path}: {e}") from e
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as e:
        raise ConfigError(f"битый YAML в {path}: {e}") from e
    if not isinstance(data, dict):
        raise ConfigError(
            f"конфиг {path} должен быть YAML-маппингом, получено: {type(data).__name__}"
        )
    return data


def _read_json(path: Path) -> dict:
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError as e:
        raise ConfigError(f"не удалось прочитать профиль {path}: {e}") from e
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        raise ConfigError(f"битый JSON в {path}: {e}") from e
    if not isinstance(data, dict):
        raise ConfigError(f"профиль {path} должен быть JSON-объектом")
    return data


def load_r0_config(path: str | Path) -> R0Config:
    """config/r0.yaml → R0Config. Падает на неизвестном пресете и любой опечатке ключа."""
    data = _read_yaml(Path(path))
    try:
        cfg = R0Config.model_validate(data)
    except ValidationError as e:
        raise ConfigError(f"невалидный r0-конфиг {path}:\n{e}") from e
    if cfg.duration_preset not in cfg.presets:
        known = ", ".join(sorted(cfg.presets))
        raise ConfigError(
            f"неизвестный duration_preset '{cfg.duration_preset}' в {path}; "
            f"известные пресеты: {known}"
        )
    from autoreels.cloud.providers import POOL_STRATEGIES
    if cfg.provider_strategy not in POOL_STRATEGIES:
        raise ConfigError(
            f"неизвестный provider_strategy '{cfg.provider_strategy}' в {path}; "
            f"допустимо: {', '.join(POOL_STRATEGIES)}"
        )
    return cfg


def _deep_merge(base: dict, override: dict) -> dict:
    """Рекурсивно наложить override на base: вложенные маппинги мержатся по ключам,
    скаляры/списки заменяются целиком. Не мутирует аргументы."""
    result = dict(base)
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(result.get(k), dict):
            result[k] = _deep_merge(result[k], v)
        else:
            result[k] = v
    return result


def load_render_config(path: str | Path, *, local_path: str | Path | None = None) -> RenderConfig:
    """config/render.yaml → RenderConfig.

    Машинно-локальные настройки (путь к ffmpeg, кодек энкодера, font_dir) кладутся в
    сосед `render.local.yaml` (в .gitignore) и накладываются поверх общего render.yaml
    через deep-merge. Так машинный путь ffmpeg не уезжает в git и не ломает другую машину
    (у Mac свой ffmpeg из PATH). Override частичный — задаются только отличающиеся ключи.
    """
    path = Path(path)
    data = _read_yaml(path)
    if local_path is None:
        local_path = path.with_name(f"{path.stem}.local{path.suffix}")
    else:
        local_path = Path(local_path)
    if local_path.is_file():
        data = _deep_merge(data, _read_yaml(local_path))
    try:
        cfg = RenderConfig.model_validate(data)
    except ValidationError as e:
        raise ConfigError(f"невалидный render-конфиг {path}:\n{e}") from e
    validate_profile(cfg.encoder.profile, cfg.encoder.profiles, where=str(path))
    return cfg


def validate_profile(profile: str, profiles: dict, *, where: str) -> None:
    """Профиль существует в таблице профилей → иначе ConfigError (fail-fast).

    Переиспользуется валидацией конфига И CLI-флагом `--profile` (опечатка ловится сразу,
    а не падает KeyError глубоко в рендере)."""
    if profile not in profiles:
        known = ", ".join(sorted(profiles))
        raise ConfigError(
            f"неизвестный профиль кодека '{profile}' в {where}; известные: {known}"
        )


def load_subtitles_config(path: str | Path) -> SubtitlesConfig:
    """config/subtitles.yaml → SubtitlesConfig."""
    data = _read_yaml(Path(path))
    try:
        return SubtitlesConfig.model_validate(data)
    except ValidationError as e:
        raise ConfigError(f"невалидный subtitles-конфиг {path}:\n{e}") from e


def load_transcribe_config(path: str | Path) -> TranscribeConfig:
    """config/transcribe.yaml → TranscribeConfig."""
    data = _read_yaml(Path(path))
    try:
        return TranscribeConfig.model_validate(data)
    except ValidationError as e:
        raise ConfigError(f"невалидный transcribe-конфиг {path}:\n{e}") from e


def load_profile(path: str | Path) -> SetupProfile:
    """profiles/*.json → SetupProfile. Валидирует кроп в границах кадра и целевой scale."""
    data = _read_json(Path(path))
    # Документирующие ключи-комментарии (_comment и т.п.) — не часть схемы.
    data = {k: v for k, v in data.items() if not k.startswith("_")}
    try:
        prof = SetupProfile.model_validate(data)
    except ValidationError as e:
        raise ConfigError(f"невалидный профиль {path}:\n{e}") from e

    if prof.scale != TARGET_SCALE:
        raise ConfigError(
            f"профиль {path}: scale должен быть {TARGET_SCALE} (целевое 9:16), "
            f"получено {prof.scale}"
        )
    if len(prof.frame) != 2:
        raise ConfigError(
            f"профиль {path}: frame должен быть [w, h], получено {prof.frame}"
        )

    frame_w, frame_h = prof.frame
    c = prof.crop
    if c.x + c.w > frame_w or c.y + c.h > frame_h:
        raise ConfigError(
            f"профиль {path}: кроп выходит за границы кадра — "
            f"crop right={c.x + c.w}/bottom={c.y + c.h} при кадре {frame_w}x{frame_h}"
        )
    return prof
