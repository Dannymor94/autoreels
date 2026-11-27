import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import { L } from "../labels";

export function TopBar() {
  const { data, isLoading, error } = useQuery({ queryKey: ["health"], queryFn: api.health });
  const status = error ? "Нет связи" : isLoading ? "Подключение…" : data?.status === "ok" ? (data.root === "private" ? "Защищённое подключение" : "Локальный сервер") : "Статус неизвестен";

  return (
    <header className="app-header">
      <strong>{L.appTitle}</strong>
      <span className="connection-status" role="status">{status}</span>
    </header>
  );
}
