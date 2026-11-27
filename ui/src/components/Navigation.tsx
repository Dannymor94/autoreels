import { navigate, type Route } from "../lib/route";

export function Navigation({ route }: { route: Route }) {
  const reviewing = route.name === "review";
  return (
    <nav className="app-nav" aria-label="Разделы приложения">
      <button type="button" aria-current={route.name === "sources" || route.name === "overview" ? "page" : undefined}
        onClick={() => navigate({ name: "sources" })}>Проекты</button>
      <button type="button" aria-current={reviewing ? "page" : undefined}
        disabled={!reviewing} title={!reviewing ? "Откройте клип в проекте" : undefined}
        onClick={() => { if (route.name === "review") navigate(route); }}>Редактор
        {!reviewing && <small>Выберите клип</small>}
      </button>
      <button type="button" aria-current={route.name === "jobs" ? "page" : undefined} onClick={() => navigate({ name: "jobs" })}>Задания</button>
      <button type="button" aria-current={route.name === "export" ? "page" : undefined}
        onClick={() => navigate({ name: "export" })}>Экспорт<small>Подготовка</small></button>
    </nav>
  );
}
