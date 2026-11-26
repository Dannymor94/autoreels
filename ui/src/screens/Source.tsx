import { useEffect, useMemo, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import { L } from "../labels";
import type { Action } from "../keys";
import { groupClips, pickVariant } from "../lib/clips";
import { persist } from "../lib/persist";
import { useHotkeys } from "../lib/useHotkeys";
import { ClipList } from "../components/ClipList";
import { VariantTabs } from "../components/VariantTabs";
import { HelpOverlay } from "../components/HelpOverlay";
import { ReviewPanel } from "../components/ReviewPanel";

interface Props {
  stem: string;
  initialClip: string;
  initialVariant: string;
  onBack: () => void; // to the overview (level 2)
  onChange: (clip: string, variant: string) => void; // keep the address in sync
}

/** What to do once the new src has loaded: seek to t, then play or stay paused. */
interface Pending {
  t: number;
  play: boolean;
}

export function Source({ stem, initialClip, initialVariant, onBack, onChange }: Props) {
  const { data, isLoading, error } = useQuery({ queryKey: ["clips", stem], queryFn: () => api.clips(stem) });
  const groups = useMemo(() => groupClips(data ?? []), [data]);

  const [clip, setClip] = useState<string | null>(null);
  const [variant, setVariant] = useState("");
  const [help, setHelp] = useState(false);
  const video = useRef<HTMLVideoElement>(null);
  const pending = useRef<Pending | null>(null);
  const lastSaved = useRef(0);
  const [loadedVersion, setLoadedVersion] = useState<string | null>(null);
  const qc = useQueryClient();

  // Open the clip from the address; resume the saved second if it is the same clip and variant.
  useEffect(() => {
    if (!groups.length || clip !== null) return;
    const g = groups.find((x) => x.clip === initialClip) ?? groups[0];
    const v = pickVariant(g, initialVariant);
    const pos = persist.position(stem);
    const resume = pos && pos.clip === g.clip && pos.variant === v ? pos.t : 0;
    pending.current = { t: resume, play: true };
    setClip(g.clip);
    setVariant(v);
  }, [groups, clip, stem, initialClip, initialVariant]);

  useEffect(() => {
    if (clip !== null) onChange(clip, variant);
  }, [clip, variant]); // onChange deliberately not a dependency: it changes on every render

  const group = groups.find((g) => g.clip === clip) ?? null;
  const reviewKey = ["review", stem, clip, variant];
  const review = useQuery({
    queryKey: reviewKey,
    queryFn: () => api.review(stem, clip!, variant),
    enabled: group !== null && group.variants.includes(variant),
    retry: false, refetchOnWindowFocus: false, refetchOnReconnect: false,
    refetchOnMount: "always",
  });
  const state = review.data;
  const mediaUrl = group && state ? api.mediaUrl(stem, group.clip, variant, state.artifact_sha256) : null;

  function refreshReview() {
    void review.refetch();
    setLoadedVersion(null);
    video.current?.load();
  }

  function position(): number | null {
    const v = video.current;
    if (!v || loadedVersion !== mediaUrl || !Number.isFinite(v.currentTime)) return null;
    v.pause();
    return Math.round(v.currentTime * 1000) / 1000;
  }

  function openClip(next: string, play: boolean) {
    const g = groups.find((x) => x.clip === next);
    if (!g) return;
    const v = video.current;
    if (g.clip === clip && pickVariant(g, variant) === variant && v) {
      v.currentTime = 0; // same src: no reload, so act directly
      if (play) v.play().catch(() => {});
      return;
    }
    pending.current = { t: 0, play };
    setClip(g.clip);
    setVariant(pickVariant(g, variant));
  }

  function switchVariant(next: string) {
    if (next === variant) return;
    const v = video.current;
    pending.current = { t: v?.currentTime ?? 0, play: v ? !v.paused : false };
    setVariant(next);
  }

  function step(dir: 1 | -1) {
    if (!groups.length) return;
    const i = groups.findIndex((g) => g.clip === clip);
    const j = i < 0 ? 0 : Math.min(groups.length - 1, Math.max(0, i + dir));
    openClip(groups[j].clip, true);
  }

  function onAction(a: Action) {
    const v = video.current;
    switch (a) {
      case "playPause": if (v) { if (v.paused) v.play().catch(() => {}); else v.pause(); } break;
      case "back2": if (v) v.currentTime = Math.max(0, v.currentTime - 2); break;
      case "fwd2": if (v) v.currentTime = Math.min(v.duration || 0, v.currentTime + 2); break;
      case "nextClip": step(1); break;
      case "prevClip": step(-1); break;
      case "nextVariant":
        if (group && group.variants.length > 1) {
          const k = group.variants.indexOf(variant);
          switchVariant(group.variants[(k + 1) % group.variants.length]);
        }
        break;
      case "toggleHelp": setHelp((h) => !h); break;
      case "escape": if (help) setHelp(false); else onBack(); break;
    }
  }
  useHotkeys(onAction);

  function onLoaded() {
    setLoadedVersion(mediaUrl);
    const v = video.current;
    const p = pending.current;
    pending.current = null;
    if (!v || !p) return;
    v.currentTime = Math.min(p.t, v.duration || p.t);
    if (p.play) v.play().catch(() => {});
  }

  function onTime() {
    const v = video.current;
    if (!v || !clip) return;
    const now = Date.now();
    if (now - lastSaved.current < 1000) return;
    lastSaved.current = now;
    persist.setPosition(stem, { clip, variant, t: v.currentTime });
  }

  if (isLoading) return <p style={{ padding: 16 }}>{L.loading}</p>;
  if (error)
    return (
      <main style={{ padding: 16 }}>
        <button onClick={onBack} style={{ cursor: "pointer", background: "none", border: "none", color: "var(--accent)" }}>
          {L.back}
        </button>
        <p style={{ color: "red", marginTop: 12 }}>{L.error}: {String(error)}</p>
      </main>
    );
  if (!groups.length) return <p style={{ padding: 16 }}>{L.noClips}</p>;

  return (
    <main className="workspace">
      <div className="workspace-heading review-heading">
        <button onClick={onBack} style={{ cursor: "pointer", background: "none", border: "none", color: "var(--accent)" }}>
          {L.backToOverview}
        </button>
        <h2>{stem}</h2>
        <span style={{ marginLeft: "auto", color: "var(--fg2)", fontSize: 13 }}>{L.helpHint}</span>
      </div>

      <div className="review-layout">
        <div className="review-player">
          {group ? (
            <>
              <VariantTabs variants={group.variants} current={variant} onPick={switchVariant} />
              {review.isLoading && <p role="status">Проверка версии видео…</p>}
              {review.isError && <p role="alert">Версия недоступна. <button onClick={refreshReview}>Повторить</button></p>}
              {state && mediaUrl && (
                <>
                  <video key={mediaUrl}
                    ref={video}
                    src={mediaUrl}
                    controls
                    playsInline
                    onLoadedMetadata={onLoaded}
                    onError={() => setLoadedVersion(null)}
                    onTimeUpdate={onTime}
                    className="review-video"
                  />
                  <ReviewPanel key={mediaUrl + (state.current?.request_id ?? "")}
                    stem={stem} clip={group.clip} variant={variant} state={state}
                    ready={loadedVersion === mediaUrl && !review.isFetching && !review.isError}
                    position={position} onSaved={(next) => qc.setQueryData(reviewKey, next)}
                    onRefresh={refreshReview} />
                </>
              )}
            </>
          ) : (
            <p style={{ color: "var(--fg2)" }}>{L.pickClip}</p>
          )}
        </div>
        <aside className="review-clips" aria-label="Клипы">
          <ClipList groups={groups} current={clip} onPick={(c) => openClip(c, true)} />
        </aside>
      </div>
      {help && <HelpOverlay onClose={() => setHelp(false)} />}
    </main>
  );
}
