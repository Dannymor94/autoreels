import { useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, type ComparisonInput, type ComparisonState } from "../api/client";
import { formatDuration, variantShortName } from "../lib/clips";

const label = (v: string) => variantShortName(v) ?? "Основной";
type Props = { stem: string; clip: string; variants: string[]; active: string; onClose: () => void };

export function ComparisonPanel({ stem, clip, variants, active, onClose }: Props) {
  const [left, setLeft] = useState(active);
  const [right, setRight] = useState(variants.find(v => v !== active)!);
  const key = ["comparison", stem, clip, left, right];
  const qc = useQueryClient();
  const result = useQuery({
    queryKey: key, queryFn: () => api.comparison(stem, clip, left, right),
    retry: false, refetchOnWindowFocus: false, refetchOnReconnect: false,
    refetchOnMount: "always",
  });
  const state = result.data;
  return <section className="comparison-panel" aria-label="Сравнение вариантов">
    <div className="comparison-heading"><h3>Сравнение вариантов</h3><button onClick={onClose}>Закрыть сравнение</button></div>
    <div className="comparison-selects">
      <label>Вариант А<select aria-label="Вариант А" value={left} onChange={e => setLeft(e.target.value)}>
        {variants.map(v => <option key={v} value={v} disabled={v === right}>{label(v)}</option>)}
      </select></label>
      <label>Вариант Б<select aria-label="Вариант Б" value={right} onChange={e => setRight(e.target.value)}>
        {variants.map(v => <option key={v} value={v} disabled={v === left}>{label(v)}</option>)}
      </select></label>
    </div>
    <p className="secondary">Одинаковая секунда воспроизведения, не обязательно одинаковый фрагмент исходника. Синхронизация приблизительная. Выбор не разрешает экспорт.</p>
    {result.isFetching && <p role="status">Проверка двух версий…</p>}
    {result.isError && <p role="alert">Сравнение недоступно. <button onClick={() => void result.refetch()}>Повторить</button></p>}
    {state && !result.isFetching && !result.isError && <PairPlayer
      key={JSON.stringify([left, right, state.left_sha256, state.right_sha256])}
      stem={stem} clip={clip} left={left} right={right} state={state}
      onSaved={next => qc.setQueryData(key, next)}
      onRefresh={() => void result.refetch()} />}
  </section>;
}

function PairPlayer({ stem, clip, left, right, state, onSaved, onRefresh }: {
  stem: string; clip: string; left: string; right: string; state: ComparisonState;
  onSaved: (s: ComparisonState) => void; onRefresh: () => void;
}) {
  const a = useRef<HTMLVideoElement>(null), b = useRef<HTMLVideoElement>(null);
  const [readyA, setReadyA] = useState(false), [readyB, setReadyB] = useState(false);
  const [durationA, setDurationA] = useState(0), [durationB, setDurationB] = useState(0);
  const [position, setPosition] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [audio, setAudio] = useState<"a" | "b">("a");
  const [comment, setComment] = useState(state.current?.comment ?? "");
  const [mediaError, setMediaError] = useState(false);
  const retry = useRef<ComparisonInput | null>(null);
  const busy = useRef(false);
  const shaA = left === state.left_variant ? state.left_sha256 : state.right_sha256;
  const shaB = right === state.right_variant ? state.right_sha256 : state.left_sha256;
  const limit = Math.min(durationA, durationB);
  const ready = readyA && readyB && limit > 0 && !mediaError;
  const save = useMutation({
    mutationFn: (body: ComparisonInput) => api.saveComparison(stem, clip, left, right, body),
    onSuccess: next => { retry.current = null; onSaved(next); },
    onSettled: () => { busy.current = false; },
  });
  function pause() { a.current?.pause(); b.current?.pause(); setPlaying(false); }
  function seek(t: number) {
    pause();
    const p = Math.max(0, Math.min(t, limit));
    if (a.current) a.current.currentTime = p;
    if (b.current) b.current.currentTime = p;
    setPosition(p);
  }
  async function toggle() {
    if (!ready || !a.current || !b.current) return;
    if (playing) { pause(); return; }
    const p = a.current.currentTime >= limit ? 0 : a.current.currentTime;
    a.current.currentTime = p;
    b.current.currentTime = p;
    try {
      await Promise.all([a.current.play(), b.current.play()]);
      if (a.current && b.current && !a.current.paused && !b.current.paused) setPlaying(true);
      else pause();
    } catch { pause(); }
  }
  function tick() {
    const x = a.current, y = b.current;
    if (!x || !y || !ready) return;
    const t = Math.min(x.currentTime, limit);
    setPosition(t);
    if (t >= limit || x.ended || y.ended) { pause(); return; }
    if (playing && !x.seeking && !y.seeking && Math.abs(y.currentTime - t) > 0.3) y.currentTime = t;
  }
  function failed() { pause(); setMediaError(true); }
  function choose(winner: string) {
    if (!ready || busy.current) return;
    pause();
    const base_revision = state.current?.request_id ?? null;
    const old = retry.current;
    const body = old && old.winner === winner && old.comment === comment && old.base_revision === base_revision
      ? old : {request_id: crypto.randomUUID(), left_sha256: shaA, right_sha256: shaB, base_revision, winner, comment};
    retry.current = body;
    busy.current = true;
    save.mutate(body);
  }
  return <>
    <div className="comparison-videos">
      <div><strong>А · {label(left)}</strong><video ref={a} className="comparison-video" src={api.mediaUrl(stem, clip, left, shaA)}
        playsInline preload="auto" muted={audio !== "a"} onLoadedMetadata={e => {setDurationA(e.currentTarget.duration); setReadyA(true);}}
        onTimeUpdate={tick} onWaiting={pause} onEnded={pause} onError={failed} /></div>
      <div><strong>Б · {label(right)}</strong><video ref={b} className="comparison-video" src={api.mediaUrl(stem, clip, right, shaB)}
        playsInline preload="auto" muted={audio !== "b"} onLoadedMetadata={e => {setDurationB(e.currentTarget.duration); setReadyB(true);}}
        onWaiting={pause} onEnded={pause} onError={failed} /></div>
    </div>
    <div className="comparison-controls">
      <button disabled={!ready} onClick={() => void toggle()}>{playing ? "Пауза обоих" : "Воспроизвести оба"}</button>
      <label>Звук <select value={audio} onChange={e => setAudio(e.target.value as "a" | "b")}><option value="a">А</option><option value="b">Б</option></select></label>
      <span>{formatDuration(position)} / {formatDuration(limit)}</span>
    </div>
    <input aria-label="Общая позиция" type="range" min={0} max={limit || 1} step={0.05} value={Math.min(position, limit)} disabled={!ready} onChange={e => seek(Number(e.target.value))} />
    {mediaError && <p role="alert">Видео изменилось или не загрузилось. Обновите сравнение.</p>}
    <label htmlFor="comparison-comment">Комментарий к выбору</label>
    <textarea id="comparison-comment" rows={2} maxLength={2000} value={comment} disabled={save.isPending} onChange={e => setComment(e.target.value)} />
    <div className="comparison-selects">
      <button disabled={!ready || save.isPending} onClick={() => choose(left)}>Выбрать А</button>
      <button disabled={!ready || save.isPending} onClick={() => choose(right)}>Выбрать Б</button>
    </div>
    <p role="status">{state.current ? "Выбран: " + label(state.current.winner) : state.history.length ? "Версии изменились — нужен новый выбор" : "Предпочтение не сохранено"}</p>
    {save.isError && <p role="alert">Выбор не сохранён. Обновите версии при конфликте.</p>}
    <button disabled={save.isPending} onClick={() => { pause(); onRefresh(); }}>Обновить сравнение</button>
    {state.history.length > 0 && <details><summary>История выбора ({state.history.length})</summary>
      {state.history.map(e => <div className="review-history-entry" key={e.request_id}>
        <strong>{label(e.winner)}</strong> · {e.left_sha256 === state.left_sha256 && e.right_sha256 === state.right_sha256 ? "текущая пара" : "предыдущая пара"}
        <p>{e.comment}</p>
      </div>)}
    </details>}
  </>;
}
