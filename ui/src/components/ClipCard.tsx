import { useRef, useState, type CSSProperties } from "react";
import { api } from "../api/client";
import { formatDuration, type ClipGroup } from "../lib/clips";
import { L } from "../labels";

const HOVER_DELAY_MS = 400; // a passing mouse does not start videos

interface Props {
  stem: string;
  group: ClipGroup;
  onOpen: () => void;
}

/** Grid card: poster + duration + variants; muted preview while hovered. */
export function ClipCard({ stem, group, onOpen }: Props) {
  const [preview, setPreview] = useState(false);
  const timer = useRef<number | undefined>(undefined);
  const variant = group.variants[0];
  const extra = group.variants.length - 1;

  const enter = () => {
    timer.current = window.setTimeout(() => setPreview(true), HOVER_DELAY_MS);
  };
  const leave = () => {
    window.clearTimeout(timer.current);
    setPreview(false);
  };

  const badge: CSSProperties = {
    position: "absolute", bottom: 6, fontSize: 11, padding: "1px 6px",
    borderRadius: 4, background: "rgba(0,0,0,0.6)", color: "#fff",
  };

  return (
    <button
      onClick={onOpen}
      onMouseEnter={enter}
      onMouseLeave={leave}
      style={{
        display: "flex", flexDirection: "column", gap: 4, textAlign: "left",
        background: "none", border: "none", padding: 0, cursor: "pointer", color: "var(--fg)",
      }}
    >
      <div style={{ position: "relative", width: "100%", aspectRatio: "9/16", background: "#000", borderRadius: "var(--radius)", overflow: "hidden" }}>
        <img
          src={api.thumbUrl(stem, group.clip, variant)}
          alt=""
          loading="lazy"
          style={{ width: "100%", height: "100%", objectFit: "cover", display: "block" }}
          onError={(e) => ((e.target as HTMLImageElement).style.visibility = "hidden")}
        />
        {preview && (
          <video
            src={api.mediaUrl(stem, group.clip, variant)}
            muted
            autoPlay
            loop
            playsInline
            style={{ position: "absolute", inset: 0, width: "100%", height: "100%", objectFit: "cover" }}
          />
        )}
        <span style={{ ...badge, left: 6 }}>{formatDuration(group.info.duration_s)}</span>
        {extra > 0 && <span style={{ ...badge, right: 6 }}>{L.variantsMore(extra)}</span>}
      </div>
      <strong style={{ fontWeight: 600 }}>{group.clip}</strong>
      <span style={{ color: "var(--fg2)", fontSize: 12, lineHeight: 1.3 }}>{group.info.title ?? ""}</span>
    </button>
  );
}
