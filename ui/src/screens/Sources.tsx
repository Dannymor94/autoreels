import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import { L } from "../labels";

interface Props {
  onSelect: (stem: string) => void;
}

export function Sources({ onSelect }: Props) {
  const { data, isLoading, error } = useQuery({ queryKey: ["sources"], queryFn: api.sources });

  if (isLoading) return <p style={{ padding: 16 }}>{L.loading}</p>;
  if (error) return <p style={{ padding: 16, color: "red" }}>{L.error}: {String(error)}</p>;
  if (!data?.length) return <p style={{ padding: 16 }}>{L.noSources}</p>;

  return (
    <main style={{ padding: 16 }}>
      <h2 style={{ marginBottom: 12 }}>{L.sources}</h2>
      <ul style={{ listStyle: "none", display: "flex", flexDirection: "column", gap: 8 }}>
        {data.map((s) => (
          <li key={s.stem}>
            <button
              onClick={() => onSelect(s.stem)}
              style={{
                background: "var(--bg2)",
                border: "1px solid var(--border)",
                borderRadius: "var(--radius)",
                padding: "10px 16px",
                cursor: "pointer",
                width: "100%",
                textAlign: "left",
                display: "flex",
                justifyContent: "space-between",
                color: "var(--fg)",
              }}
            >
              <span>{s.stem}</span>
              <span style={{ color: "var(--fg2)", fontSize: 13 }}>{L.clipCount(s.clip_count)}</span>
            </button>
          </li>
        ))}
      </ul>
    </main>
  );
}
