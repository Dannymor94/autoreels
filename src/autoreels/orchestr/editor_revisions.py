"""Isolated editor revision store: one Manifest commit point, no live migration.

The trusted caller supplies a dedicated SQLite connection and exact initial
manifest bytes. Not registered in the API, legacy CLI or production storage.
Supports explicit single-word subtitle correction and trusted precomputed
synthetic cut selection in separate fixture projects.
"""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from autoreels.core.models import Crop, GraphicLayer, Manifest
from .synthetic_soundtrack import soundtrack
from .synthetic_image import IMAGE
from .synthetic_video import VIDEO

Digest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
OpaqueId = Annotated[str, Field(pattern=r"^[A-Za-z0-9_-]{1,64}$")]
Token = Annotated[str, Field(min_length=1, max_length=128)]


class Conflict(RuntimeError):
    """No mutation performed; refresh or resolve the conflicting revision."""


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class Correction(BaseModel):
    model_config = ConfigDict(frozen=True, strict=True, extra="forbid")
    op_id: OpaqueId
    project_id: OpaqueId
    clip_uid: Digest
    base_revision: Annotated[int, Field(ge=0)]
    base_plan_sha256: Digest
    word_index: Annotated[int, Field(ge=0)]
    expected_text: Token
    replacement: Token
    action: Literal["edit", "undo", "redo"] = "edit"


# Fixed source frame and bounded crop presets for the isolated cut fixture.
# These are source pixels, not browser-dependent percentages.
FIXTURE_CROPS = ((18, 30, 60, 100), (0, 30, 60, 100),
                 (36, 30, 60, 100), (18, 0, 60, 100),
                 (18, 60, 60, 100), (24, 40, 48, 80))


# Bounded synthetic UI choices: final-frame %, output ms, palette index.
FIXTURE_GRAPHICS = (
    (10, 10, 20, 20, 0, 500, 1),
    (70, 10, 20, 20, 0, 500, 1),
    (10, 10, 20, 20, 500, 1000, 1),
    (10, 10, 20, 20, 0, 1000, 2),
    (10, 10, 25, 25, 0, 500, 3),
    (10, 10, 25, 25, 0, 1000, 4),
)


def graphic_for(code):
    if code is None:
        return None
    if len(code)!=7 or any(type(n) is not int for n in code):
        raise Conflict("invalid fixture graphic")
    x, y, w, h, start, end, color = code
    if color not in (1,2,3,4) or min(w,h)<5 or end>6000:
        raise Conflict("invalid fixture graphic")
    try:
        return GraphicLayer(x_pct=x, y_pct=y, width_pct=w, height_pct=h,
                            start_ms=start, end_ms=end, color={1:"white",2:"blue"}.get(color),
                            image=IMAGE if color==3 else None,
                            video=VIDEO if color==4 else None)
    except ValueError as exc:
        raise Conflict("invalid fixture graphic") from exc


class FixtureSelection(BaseModel):
    model_config = ConfigDict(frozen=True, strict=True, extra="forbid")
    action: Literal["select-fixture"]
    op_id: OpaqueId
    project_id: OpaqueId
    clip_uid: Digest
    base_revision: Annotated[int, Field(ge=0)]
    base_plan_sha256: Digest
    candidate_plan_sha256: Digest
    removed: tuple[int, ...]
    order: tuple[int, ...] | None = None
    trim: tuple[int, int, int] | None = None  # window index, edge (1/2), source ms
    rates: tuple[int, ...] | None = None  # percent, indexed by playback window
    crop: tuple[int, int, int, int] | None = None
    navigation: Literal["undo", "redo"] | None = None
    music: tuple[int, int, int, int] | None = None
    dip_ms: int | None = None
    graphic: tuple[int, int, int, int, int, int, int] | None = None

    @property
    def selection_key(self) -> tuple[int, ...]:
        """Legacy cut key, or a disjoint key for a nonchronological fixture."""
        if (any(n <= 0 for n in self.removed)
                or tuple(sorted(set(self.removed))) != self.removed):
            raise Conflict("invalid fixture removal key")
        key = self.removed
        if self.order is not None:
            if (not self.order or any(n <= 0 for n in self.order)
                    or len(set(self.order)) != len(self.order)
                    or set(self.order) & set(self.removed)
                    or tuple(sorted(self.order)) == self.order):
                raise Conflict("invalid fixture permutation key")
            key = (*key, 0, *self.order)
        if self.trim is not None:
            index, edge, ms = self.trim
            if index < 0 or edge not in (1, 2) or ms < 0:
                raise Conflict("invalid fixture trim key")
            key = (*key, -1, index, edge, ms)
        if self.rates is not None:
            if not self.rates or any(n not in (50, 100, 200) for n in self.rates) or all(n == 100 for n in self.rates):
                raise Conflict("invalid fixture rate vector")
            key = (*key, -2, *self.rates)
        if self.crop is not None:
            if self.crop not in FIXTURE_CROPS:
                raise Conflict("invalid fixture crop")
            key = (*key, -3, *self.crop)
        if self.music is not None:
            try:
                soundtrack(self.music)
            except ValueError as exc:
                raise Conflict("invalid fixture soundtrack") from exc
            key = (*key, -4, *self.music)
        if self.dip_ms is not None:
            if self.dip_ms not in (100, 200, 300):
                raise Conflict("invalid fixture transition")
            key = (*key, -5, self.dip_ms)
        if self.graphic is not None:
            graphic_for(self.graphic)
            key = (*key, -6, *self.graphic)
        return key


@dataclass(frozen=True)
class Revision:
    project_id: str
    number: int
    plan_sha256: str
    plan_bytes: bytes
    clip_uids: tuple[tuple[str, str], ...]  # (display alias, immutable uid)

    def manifest(self) -> Manifest:
        return Manifest.model_validate_json(self.plan_bytes)


class Store:
    """One transaction stores each immutable Manifest revision and operation.

    Project IDs are explicit trusted IDs. Initial migration is deliberately
    exact-only; ambiguous clip aliases or duplicate recorded source identities
    are rejected, not matched heuristically. The initial UID map persists
    across corrections. No live CLI/manifest file writes or second live head.
    """
    def __init__(self, conn: sqlite3.Connection, *, initialize: bool = True):
        self.conn = conn
        if conn.in_transaction:
            raise ValueError("editor store requires dedicated idle connection")
        if not initialize:
            return
        with self._tx():
            conn.execute("""
                CREATE TABLE IF NOT EXISTS editor_projects_v1 (
                    project_id TEXT PRIMARY KEY,
                    source_key TEXT NOT NULL UNIQUE,
                    initial_sha TEXT NOT NULL,
                    clip_uids TEXT NOT NULL
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS editor_revisions_v1 (
                    project_id TEXT NOT NULL,
                    revision INTEGER NOT NULL,
                    plan_sha TEXT NOT NULL,
                    plan BLOB NOT NULL,
                    op_id TEXT UNIQUE,
                    op_payload TEXT,
                    PRIMARY KEY(project_id, revision)
                )
            """)

    @contextmanager
    def _tx(self):
        if self.conn.in_transaction:
            raise ValueError("nested editor transaction")
        self.conn.execute("BEGIN IMMEDIATE")
        try:
            yield
            self.conn.commit()
        except BaseException:
            self.conn.rollback()
            raise

    def _read(self, project_id: str, number: int | None = None) -> Revision:
        query = """
            SELECT r.revision,r.plan_sha,r.plan,p.clip_uids
            FROM editor_revisions_v1 r JOIN editor_projects_v1 p USING(project_id)
            WHERE r.project_id=?
        """
        args = (project_id,)
        if number is not None:
            query += " AND r.revision=?"
            args += (number,)
        row = self.conn.execute(query + " ORDER BY r.revision DESC LIMIT 1", args).fetchone()
        if row is None:
            raise Conflict("unknown editor revision")
        revision, digest, raw, mapping = row
        if _sha(raw) != digest:
            raise Conflict("stored editor revision corrupted")
        return Revision(project_id, revision, digest, raw,
                        tuple(tuple(x) for x in json.loads(mapping)))

    def current(self, project_id: str) -> Revision:
        return self._read(project_id)

    def has_project(self, project_id: str) -> bool:
        return self.conn.execute("SELECT 1 FROM editor_projects_v1 WHERE project_id=?",(project_id,)).fetchone() is not None

    def import_initial(self, project_id: str, raw: bytes, *, expected_sha256: str) -> Revision:
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", project_id):
            raise ValueError("explicit project ID required")
        if type(raw) is not bytes or _sha(raw) != expected_sha256:
            raise Conflict("initial manifest digest mismatch")
        manifest = Manifest.model_validate_json(raw)
        if (manifest.source_hash_scheme not in ("full", "partial-p1")
                or not re.fullmatch(r"[0-9a-f]{64}", manifest.source_sha256)):
            raise ValueError("invalid recorded source identity")
        aliases = [reel.id for reel in manifest.reels]
        if len(set(aliases)) != len(aliases) or any(not re.fullmatch(r"r\d{2,3}", a) for a in aliases):
            raise Conflict("ambiguous legacy clip aliases")
        for reel in manifest.reels:
            reel.check_segments()
        source_key = manifest.source_hash_scheme + ":" + manifest.source_sha256
        mapping = [(alias, _sha(f"editor-v1:{project_id}:{expected_sha256}:{alias}".encode("ascii")))
                   for alias in aliases]
        with self._tx():
            old = self.conn.execute("SELECT initial_sha FROM editor_projects_v1 WHERE project_id=?",
                                    (project_id,)).fetchone()
            if old:
                if old[0] != expected_sha256:
                    raise Conflict("project already bound to another initial revision")
                return self._read(project_id)
            try:
                self.conn.execute("INSERT INTO editor_projects_v1 VALUES(?,?,?,?)",
                                  (project_id, source_key, expected_sha256, json.dumps(mapping)))
            except sqlite3.IntegrityError:
                raise Conflict("recorded source already has a project") from None
            self.conn.execute("INSERT INTO editor_revisions_v1 VALUES(?,?,?,?,NULL,NULL)",
                              (project_id, 0, expected_sha256, raw))
            return self._read(project_id)

    def _history_payloads(self, project_id: str):
        return [row[0] for row in self.conn.execute(
            "SELECT op_payload FROM editor_revisions_v1 WHERE project_id=? AND revision>0 ORDER BY revision",
            (project_id,),
        )]

    def history(self, project_id: str) -> list[Correction]:
        try:
            return [Correction.model_validate_json(raw) for raw in self._history_payloads(project_id)]
        except ValueError as exc:
            raise Conflict("incompatible editor history") from exc

    def selection_history(self, project_id: str) -> list[FixtureSelection]:
        try:
            return [FixtureSelection.model_validate_json(raw) for raw in self._history_payloads(project_id)]
        except ValueError as exc:
            raise Conflict("incompatible fixture history") from exc

    @staticmethod
    def stacks(history: list[Correction]) -> tuple[list[Correction], list[Correction]]:
        undo, redo = [], []
        for op in history:
            if op.action == "edit":
                undo.append(op)
                redo.clear()
            elif op.action == "undo":
                if not undo:
                    raise Conflict("invalid stored undo history")
                redo.append(undo.pop())
            else:
                if not redo:
                    raise Conflict("invalid stored redo history")
                undo.append(redo.pop())
        return undo, redo

    def correct(self, op: Correction, *, max_revision: int | None = None) -> Revision:
        # This is spelling/text only: no insertion/removal of words, no
        # timing edits, no transcript or audio changes. Whitespace/control
        # characters cannot turn one word anchor into multiple words.
        if (op.replacement == op.expected_text
                or any(c.isspace() or not c.isprintable() for c in op.replacement)):
            raise ValueError("one changed printable token required")
        payload = op.model_dump_json()
        with self._tx():
            prior = self.conn.execute("SELECT project_id,revision,op_payload FROM editor_revisions_v1 WHERE op_id=?",
                                      (op.op_id,)).fetchone()
            if prior:
                if prior[0] != op.project_id or Correction.model_validate_json(prior[2]) != op:
                    raise Conflict("operation ID already bound")
                return self._read(prior[0], prior[1])
            base = self._read(op.project_id)
            if base.number != op.base_revision or base.plan_sha256 != op.base_plan_sha256:
                raise Conflict("stale editor revision")
            if max_revision is not None and base.number >= max_revision:
                raise Conflict("revision limit reached")
            history = self.history(op.project_id)
            if len(history) != base.number:
                raise Conflict("incomplete editor history")
            if op.action != "edit":
                undo, redo = self.stacks(history)
                stack = undo if op.action == "undo" else redo
                if not stack:
                    raise Conflict("no matching history action")
                target = stack[-1]
                before, after = ((target.replacement, target.expected_text)
                                 if op.action == "undo" else (target.expected_text, target.replacement))
                if (op.clip_uid, op.word_index, op.expected_text, op.replacement) != (
                        target.clip_uid, target.word_index, before, after):
                    raise Conflict("history action target changed")
            aliases = [alias for alias, uid in base.clip_uids if uid == op.clip_uid]
            manifest = base.manifest()
            matches = [i for i, reel in enumerate(manifest.reels) if reel.id in aliases]
            if len(aliases) != 1 or len(matches) != 1:
                raise Conflict("unknown or ambiguous clip UID")
            index = matches[0]
            reel = manifest.reels[index]
            if op.word_index >= len(reel.subtitles):
                raise Conflict("word anchor unavailable")
            old = reel.subtitles[op.word_index]
            if old.word != op.expected_text:
                raise Conflict("word anchor changed")
            words = list(reel.subtitles)
            words[op.word_index] = old.model_copy(update={"word": op.replacement})
            reels = list(manifest.reels)
            reels[index] = reel.model_copy(update={"subtitles": words})
            candidate = manifest.model_copy(update={"reels": reels})
            raw = candidate.model_dump_json().encode("utf-8")
            # Validate the exact stored bytes; never commit an invalid model_copy.
            Manifest.model_validate_json(raw)
            number = base.number + 1
            self.conn.execute("INSERT INTO editor_revisions_v1 VALUES(?,?,?,?,?,?)",
                              (op.project_id, number, _sha(raw), raw, op.op_id, payload))
            return self._read(op.project_id, number)


    @staticmethod
    def fixture_stacks(history: list[FixtureSelection], initial_sha: str):
        """Replay the immutable selection log. Legacy operations are ordinary edits."""
        undo = [((), initial_sha)]
        redo = []
        for op in history:
            target = (op.selection_key, op.candidate_plan_sha256)
            if op.navigation == "undo":
                if len(undo) < 2 or undo[-2] != target:
                    raise Conflict("invalid stored fixture undo")
                redo.append(undo.pop())
            elif op.navigation == "redo":
                if not redo or redo[-1] != target:
                    raise Conflict("invalid stored fixture redo")
                undo.append(redo.pop())
            else:
                undo.append(target)
                redo.clear()
        return undo, redo

    def select_fixture(self, op: FixtureSelection, *, choices: dict[tuple[int, ...], bytes],
                       max_revision: int = 100) -> Revision:
        """Commit a server-computed candidate from a fixed synthetic plan set.

        Internal fixture adapter only; clients cannot supply Manifest bytes.
        This is deliberately not a generic production import/write path.
        """
        raw = choices.get(op.selection_key)
        initial = choices.get(())
        if raw is None or initial is None or _sha(raw) != op.candidate_plan_sha256:
            raise Conflict("fixture candidate changed or unavailable")
        candidate = Manifest.model_validate_json(raw)
        baseline = Manifest.model_validate_json(initial)
        expected_setup = baseline.setup
        if op.crop is not None:
            if (baseline.setup is None or baseline.setup.frame != [96, 160]
                    or baseline.setup.crop.model_dump() != dict(x=0, y=0, w=96, h=160)):
                raise Conflict("fixture crop outside supported source")
            expected_setup = baseline.setup.model_copy(update={"crop": Crop(
                **dict(zip(("x", "y", "w", "h"), op.crop)))})
        if (len(candidate.reels) != 1 or len(baseline.reels) != 1
                or candidate.reels[0].id != baseline.reels[0].id
                or candidate.setup != expected_setup
                or candidate.reels[0].background_track != soundtrack(op.music)
                or candidate.reels[0].seam_dip_ms != op.dip_ms
                or candidate.reels[0].graphic_layer != graphic_for(op.graphic)
                or candidate.model_copy(update={"reels":baseline.reels, "setup":baseline.setup}) != baseline):
            raise Conflict("fixture candidate outside initial manifest")
        candidate.reels[0].check_segments()
        payload = op.model_dump_json(exclude_none=True)
        with self._tx():
            prior = self.conn.execute("SELECT project_id,revision,op_payload FROM editor_revisions_v1 WHERE op_id=?",
                                      (op.op_id,)).fetchone()
            if prior:
                if prior[0] != op.project_id or prior[2] != payload:
                    raise Conflict("operation ID already bound")
                return self._read(prior[0],prior[1])
            base = self._read(op.project_id)
            if (base.number != op.base_revision or base.plan_sha256 != op.base_plan_sha256
                    or self._read(op.project_id,0).plan_bytes != initial
                    or base.plan_bytes not in choices.values()
                    or base.clip_uids != ((baseline.reels[0].id,op.clip_uid),)):
                raise Conflict("stale or incompatible fixture revision")
            history = self.selection_history(op.project_id)
            if len(history) != base.number or base.number >= max_revision:
                raise Conflict("fixture history unavailable or full")
            undo, redo = self.fixture_stacks(history, _sha(initial))
            if undo[-1][1] != base.plan_sha256:
                raise Conflict("fixture navigation does not match head")
            target = (op.selection_key, op.candidate_plan_sha256)
            if op.navigation == "undo" and (len(undo) < 2 or undo[-2] != target):
                raise Conflict("fixture undo target changed")
            if op.navigation == "redo" and (not redo or redo[-1] != target):
                raise Conflict("fixture redo target changed")
            if raw == base.plan_bytes:
                raise Conflict("fixture selection unchanged")
            number = base.number+1
            self.conn.execute("INSERT INTO editor_revisions_v1 VALUES(?,?,?,?,?,?)",
                              (op.project_id,number,_sha(raw),raw,op.op_id,payload))
            return self._read(op.project_id,number)
