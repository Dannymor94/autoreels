import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import { L } from "../labels";

export function TopBar() {
  const { data } = useQuery({ queryKey: ["health"], queryFn: api.health });

  return (
    <header style={{
      background: "var(--bg2)",
      borderBottom: "1px solid var(--border)",
      padding: "8px 16px",
      display: "flex",
      alignItems: "center",
      gap: 12,
    }}>
      <strong>{L.appTitle}</strong>
      {data && (
        <span style={{ color: "var(--fg2)", fontSize: 13 }}>
          {L.root}: {data.root}
        </span>
      )}
    </header>
  );
}
