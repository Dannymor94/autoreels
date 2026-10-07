import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import { L } from "../labels";

interface Props {
  stem: string;
  onBack: () => void;
}

export function Source({ stem, onBack }: Props) {
  const { data, isLoading, error } = useQuery({
    queryKey: ["clips", stem],
    queryFn: () => api.clips(stem),
  });
  const [playing, setPlaying] = useState<{ clip: string; variant: string } | null>(null);

  if (isLoading) return <p style={{ padding: 16 }}>{L.loading}</p>;
  if (error) return <p style={{ padding: 16, color: "red" }}>{L.error}: {String(error)}</p>;
  if (!data?.length) return <p style={{ padding: 16 }}>{L.noClips}</p>;

  return (
    <main style={{ padding: 16 }}>
      <button onClick={onBack} style={{ marginBottom: 12, cursor: "pointer", background: "none", border: "none", color: "var(--accent)" }}>
        {L.back}
      </button>
      <h2 style={{ marginBottom: 12 }}>{stem}</h2>

      <div style={{ display: "flex", gap: 16, flexWrap: "wrap" }}>
        <div style={{ flex: "0 0 auto", maxWidth: 300 }}>
          <h3 style={{ marginBottom: 8 }}>{L.clips}</h3>
          <ul style={{ listStyle: "none", display: "flex", flexDirection: "column", gap: 4 }}>
            {data.map((c) => {
              const active = playing?.clip === c.clip && playing?.variant === c.variant;
              return (
                <li key={`${c.clip}:${c.variant}`}>
                  <button
                    onClick={() => setPlaying({ clip: c.clip, variant: c.variant })}
                    style={{
                      background: active ? "var(--accent)" : "var(--bg2)",
                      color: active ? "#fff" : "var(--fg)",
                      border: "1px solid var(--border)",
                      borderRadius: "var(--radius)",
                      padding: "6px 12px",
                      cursor: "pointer",
                      width: "100%",
                      textAlign: "left",
                      fontSize: 13,
                    }}
                  >
                    {c.clip}
                    {c.variant ? ` · ${c.variant}` : ` · ${L.mainVariant}`}
                  </button>
                </li>
              );
            })}
          </ul>
        </div>

        {playing && (
          <div style={{ flex: "1 1 auto" }}>
            <video
              key={`${playing.clip}:${playing.variant}`}
              src={api.mediaUrl(stem, playing.clip, playing.variant)}
              controls
              playsInline
              style={{
                maxHeight: "80vh",
                aspectRatio: "9/16",
                background: "#000",
                borderRadius: "var(--radius)",
                display: "block",
              }}
            />
          </div>
        )}
      </div>
    </main>
  );
}
