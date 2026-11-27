import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api, type RenderProfile, type PipelineSettings } from "../api/client";

const statusText = {
  configured: "Настроено", missing: "Конфигурация отсутствует",
  invalid: "Конфигурация невалидна", blocked: "Конфигурация недоступна",
} as const;

export function PipelineSettingsPanel() {
  const settings = useQuery({queryKey:["pipeline-settings"], queryFn:()=>api.pipelineSettings(), retry:false});
  const data = settings.data;
  const [clips, setClips] = useState("");
  const [profile, setProfile] = useState<RenderProfile | "">("");
  const [preview, setPreview] = useState<PipelineSettings | null>(null);
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState(false);
  const n = Number(clips);
  const validCount = clips === "" || (/^[0-9]+$/.test(clips) && Number.isSafeInteger(n) && n >= 1 && n <= 1000);
  const enabled = !!data && data.schema_version === 1 && !settings.isError && !settings.isFetching;
  const canCheck = enabled && validCount && (clips !== "" || profile !== "") && !busy;
  async function check() {
    if (!canCheck) return;
    setBusy(true); setFailed(false); setPreview(null);
    try {
      const result = await api.pipelineSettings(clips === "" ? undefined : n, profile || undefined);
      if (result.schema_version !== 1) throw Error("unknown schema");
      setPreview(result);
    } catch { setFailed(true); } finally { setBusy(false); }
  }
  return <section className="pipeline-settings">
    <h2>Настройки монтажа и рендера</h2>
    <p className="secondary">Значения конфигурации текущего узла. Это не готовность устройства к рендеру и не полный профиль запуска.</p>
    {settings.isLoading && <p role="status">Загрузка настроек…</p>}
    {(settings.isError || (data && data.schema_version !== 1)) && <p role="alert">Настройки недоступны. <button onClick={()=>void settings.refetch()}>Повторить</button></p>}
    {enabled && data && <>
      <h3>Автомонтаж</h3>
      <p className="secondary">{statusText[data.analysis_status]}</p>
      {data.analysis && <>
        <p>Базовое число роликов: {data.analysis.base_clips}. {data.analysis.clips_every_min > 0 ? "Без явного числа учитывается длительность исходника." : "Без явного числа используется базовое значение."}</p>
        <p>Автомонтаж: {data.analysis.min_sec}–{data.analysis.max_sec} с, цель {data.analysis.target_sec} с.</p>
        <p className="secondary">Пресет отбора: {data.analysis.label_min_sec}–{data.analysis.label_max_sec} с. Настроенный режим: {data.analysis.configured_mode === "scenario" ? "Сценарист" : "Автомонтаж"} (не подтверждает доступность модели или стоимость).</p>
        <label>Число роликов для пробной настройки
          <input type="number" min={1} max={1000} step={1} value={clips} disabled={busy}
            placeholder={String(data.analysis.base_clips)} onChange={e=>{setClips(e.target.value);setPreview(null);setFailed(false);}} />
        </label>
      </>}
      <h3>Рендер</h3>
      <p className="secondary">{statusText[data.render_status]}</p>
      {data.render && <>
        <p>{data.render.width} × {data.render.height} · {data.render.profile ?? "Нестандартный профиль"}</p>
        <p className="secondary">Нормализация: {data.render.loudnorm_enabled?"вкл.":"выкл."} · шумоподавление: {data.render.denoise_enabled?"вкл.":"выкл."} · музыка: {data.render.music_enabled?"вкл.":"выкл."}</p>
        {data.render.role === "analyze" && <p role="status">Рендер запрещён ролью текущего узла.</p>}
        <label>Профиль для пробной настройки
          <select value={profile} disabled={busy} onChange={e=>{setProfile(e.target.value as RenderProfile | "");setPreview(null);setFailed(false);}}>
            <option value="">Не менять</option>
            {data.render.profiles.map(p=><option key={p} value={p}>{p.toUpperCase()}</option>)}
          </select>
        </label>
      </>}
      {!validCount && <p role="alert">Введите целое число от 1 до 1000.</p>}
      <button disabled={!canCheck} onClick={()=>void check()}>{busy?"Проверка…":"Проверить настройки"}</button>
      {preview && <p role="status">{preview.preview_status === "valid" ? "Пробные параметры допустимы. Ничего не сохранено." : "Пробные параметры заблокированы конфигурацией."}</p>}
      {failed && <p role="alert">Не удалось проверить настройки.</p>}
      <p className="secondary">Проверка не запускает обработку, не меняет конфиг и не подтверждает возможность исполнения.</p>
    </>}
  </section>;
}
