import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api, type RenderMode } from "../api/client";
import { PipelineSettingsPanel } from "../components/PipelineSettingsPanel";
import { ModuleSettingsPanel } from "../components/ModuleSettingsPanel";

const descriptions = {
  desktop: { name: "Мой компьютер", detail: "Обработка на компьютере владельца, без обязательного сервера." },
  remote: { name: "Удалённый сервер", detail: "Выбранный доверенный вычислительный узел. Передача файлов только с разрешения." },
  mobile: { name: "На телефоне", detail: "Обработка непосредственно на смартфоне, без обязательного ПК или сервера." },
} as const;

export function ExportSetup() {
  const { data, isLoading, error, refetch } = useQuery({
    queryKey: ["render-targets"], queryFn: api.renderTargets, retry: false,
  });
  const [kind, setKind] = useState<RenderMode["kind"] | null>(null);
  const supported = data?.schema_version === 1 && Array.isArray(data.modes) && Array.isArray(data.targets);
  const modes = supported ? data.modes.filter(m => Object.prototype.hasOwnProperty.call(descriptions, m.kind)) : [];
  const selected = modes.find(m => m.kind === kind);
  const nodes = supported && selected ? data.targets.filter(t => t.kind === selected.kind) : [];
  return <main className="workspace export-setup">
    <div className="workspace-heading"><div><h1>Экспорт</h1>
      <p className="secondary">Подготовка места исполнения</p></div></div>
    <p>Выберите предпочтительный режим. Это не запускает обработку и не передаёт файлы.</p>
    {isLoading && <p role="status">Загрузка возможностей…</p>}
    {(error || (data && !supported)) && <p role="alert">Возможности недоступны. <button onClick={() => void refetch()}>Повторить</button></p>}
    {supported && <fieldset className="target-modes">
      <legend>Где выполнять рендер?</legend>
      {modes.map(m => <label key={m.kind} className="target-option">
        <input type="radio" name="render-mode" checked={kind === m.kind} onChange={() => setKind(m.kind)} />
        <span><strong>{descriptions[m.kind].name}</strong>
          <span className="secondary">{descriptions[m.kind].detail}</span>
          <span className="secondary">{m.integration === "device_spike_pending" ? "Нужна проверка рендера на устройстве" : "Подключение исполнителя запланировано"}</span>
        </span>
      </label>)}
    </fieldset>}
    {selected && <section className="target-detail">
      <h2>{descriptions[selected.kind].name}</h2>
      <p role="status">{nodes.length === 0 ? "Подключённых исполнителей нет" : "Зарегистрировано исполнителей: " + nodes.length}</p>
      {nodes.map(t => <p key={t.target_id} className="secondary">{t.platform} · {t.authorized && t.availability === "ready" ? "Готовность подтверждена" : "Недоступен для запуска"}</p>)}
    </section>}
    <PipelineSettingsPanel />
    <ModuleSettingsPanel />
    <button className="render-start" disabled>Запустить рендер</button>
    <p className="secondary">Запуск ещё не подключён. Автоматического переключения на другой узел нет.</p>
  </main>;
}
