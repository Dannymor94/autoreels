import { useEffect, useMemo, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import { L } from "../labels";
import type { Action } from "../keys";
import { groupClips, pickVariant } from "../lib/clips";
import { persist } from "../lib/persist";
import { useHotkeys } from "../lib/useHotkeys";
import { ClipList } from "../components/ClipList";
import { VariantTabs } from "../components/VariantTabs";
import { HelpOverlay } from "../components/HelpOverlay";

interface Props {
  stem: string;
  onBack: () => void;
}

/** What to do once the new src has loaded: seek to t, then play or stay paused. */
interface Pending {
  t: number;
  play: boolean;
}

export function Source({ stem, onBack }: Props) {
  const { data, isLoading, error } = useQuery({ queryKey: ["clips", stem], queryFn: () => api.clips(stem) });
  const groups = useMemo(() => groupClips(data ?? []), [data]);

  const [clip, setClip] = useState<string | null>(null);
  const [variant, setVariant] = useState("");
  const [help, setHelp] = useState(false);
  const video = useRef<HTMLVideoElement>(null);
  const pending = useRef<Pending | null>(null);
  const lastSaved = useRef(0);

  // Restore where the owner stopped in this source (once the clip list is known).
  useEffect(() => {
    if (!groups.length || clip !== null) return;
    const pos = persist.position(stem);
    const g = groups.find((x) => x.clip === pos?.clip);
    if (pos && g) {
      pending.current = { t: pos.t, play: false };
      setClip(g.clip);
      setVariant(pickVariant(g, pos.variant));
    }
  }, [groups, clip, stem]);

  const group = groups.find((g) => g.clip === clip) ?? null;

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
      case "closeHelp": setHelp(false); break;
    }
  }
  useHotkeys(onAction);

  function onLoaded() {
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
    <main style={{ padding: 16 }}>
      <div style={{ display: "flex", alignItems: "baseline", gap: 16, marginBottom: 12 }}>
        <button onClick={onBack} style={{ cursor: "pointer", background: "none", border: "none", color: "var(--accent)" }}>
          {L.back}
        </button>
        <h2>{stem}</h2>
        <span style={{ marginLeft: "auto", color: "var(--fg2)", fontSize: 13 }}>{L.helpHint}</span>
      </div>

      <div style={{ display: "flex", gap: 16, alignItems: "flex-start" }}>
        <ClipList groups={groups} current={clip} onPick={(c) => openClip(c, true)} />
        <div style={{ flex: "1 1 auto" }}>
          {group ? (
            <>
              <VariantTabs variants={group.variants} current={variant} onPick={switchVariant} />
              <video
                ref={video}
                src={api.mediaUrl(stem, group.clip, variant)}
                controls
                playsInline
                onLoadedMetadata={onLoaded}
                onTimeUpdate={onTime}
                style={{ height: "80vh", aspectRatio: "9/16", background: "#000", borderRadius: "var(--radius)", display: "block" }}
              />
            </>
          ) : (
            <p style={{ color: "var(--fg2)" }}>{L.pickClip}</p>
          )}
        </div>
      </div>
      {help && <HelpOverlay onClose={() => setHelp(false)} />}
    </main>
  );
}
