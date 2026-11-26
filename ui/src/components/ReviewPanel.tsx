import { useRef, useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { api, type ReviewInput, type ReviewState } from "../api/client";
import { formatDuration } from "../lib/clips";

const LABELS = { keep: "Оставить", fix: "Исправить", drop: "Убрать" } as const;

interface Props {
  stem: string;
  clip: string;
  variant: string;
  state: ReviewState;
  ready: boolean;
  position: () => number | null;
  onSaved: (state: ReviewState) => void;
  onRefresh: () => void;
}

export function ReviewPanel({ stem, clip, variant, state, ready, position, onSaved, onRefresh }: Props) {
  const [comment, setComment] = useState(state.current?.comment ?? "");
  const retry = useRef<ReviewInput | null>(null);
  const saving = useRef(false);
  const mutation = useMutation({
    mutationFn: (body: ReviewInput) => api.saveReview(stem, clip, variant, body),
    onSuccess: (next) => {
      retry.current = null;
      onSaved(next);
    },
    onSettled: () => { saving.current = false; },
  });

  function save(verdict: ReviewInput["verdict"]) {
    if (!ready || saving.current) return;
    const base_revision = state.current?.request_id ?? null;
    const previous = retry.current;
    const body: ReviewInput = previous && previous.verdict === verdict &&
      previous.comment === comment && previous.base_revision === base_revision &&
      previous.artifact_sha256 === state.artifact_sha256 ? previous : {
        request_id: crypto.randomUUID(),
        artifact_sha256: state.artifact_sha256,
        base_revision, verdict, comment, position_s: position(),
      };
    retry.current = body;
    saving.current = true;
    mutation.mutate(body);
  }

  return (
    <section className="review-panel" aria-label="Оценка ролика">
      <div className="review-panel-heading">
        <h3>Оценка ролика</h3>
        <span role="status">{state.current ? "Сохранено: " + LABELS[state.current.verdict] :
          state.history.length ? "Версия изменилась — нужна оценка" : "Не оценён"}</span>
      </div>
      <p className="secondary">Оценка этой версии. Экспорт утверждается отдельно.</p>
      <label htmlFor="review-comment">Комментарий (необязательно)</label>
      <textarea id="review-comment" rows={2} maxLength={2000} value={comment}
        disabled={mutation.isPending} onChange={(e) => setComment(e.target.value)}
        placeholder="Что хорошо или что исправить?" />
      <div className="review-actions">
        {(["keep", "fix", "drop"] as const).map(v => (
          <button type="button" key={v} aria-pressed={state.current?.verdict === v}
            disabled={!ready || mutation.isPending} onClick={() => save(v)}>{LABELS[v]}</button>
        ))}
      </div>
      <p className="secondary">При выборе оценки сохраняется текущая секунда видео.</p>
      {!ready && <p className="secondary">Для оценки дождитесь загрузки видео.</p>}
      {mutation.isPending && <p role="status">Сохранение…</p>}
      {mutation.isError && <p role="alert">Оценка не сохранена. Если версия изменилась, обновите её и проверьте снова.</p>}
      <button type="button" className="review-refresh" disabled={mutation.isPending} onClick={onRefresh}>Обновить версию</button>
      {(state.history.length > 0 || state.legacy.length > 0) && (
        <details>
          <summary>История оценок ({state.history.length + state.legacy.length})</summary>
          {state.history.map(e => <div key={e.request_id} className="review-history-entry">
            <strong>{LABELS[e.verdict]}</strong> · {e.artifact_sha256 === state.artifact_sha256 ? "эта версия" : "предыдущая версия"}
            {e.position_s !== null && " · " + formatDuration(e.position_s)}
            <p className="secondary">{new Date(e.created_at).toLocaleString("ru-RU")}</p>
            {e.comment && <p>{e.comment}</p>}
          </div>)}
          {state.legacy.map((e, i) => <div key={"legacy-" + i} className="review-history-entry">
            <strong>Старая оценка: {e.verdict}</strong> · версия не подтверждена
            <p className="secondary">{e.date}{e.gate && " · " + e.gate}</p>
            {e.comment && <p>{e.comment}</p>}
          </div>)}
        </details>
      )}
    </section>
  );
}
