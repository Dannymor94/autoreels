import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api, type PresetLayer, type PresetPreview } from "../api/client";

const scopeLabels = {global_layer:"Глобальный",project_layer:"Проект",clip_layer:"Ролик"} as const;
type Scope = keyof typeof scopeLabels;
const labels = {
  hook_rescue:"Поиск хука внутри фразы",
  filler_word_cut:"Кандидаты слов-паразитов",
  zoom:"Автоматический зум",
  loudnorm:"Нормализация громкости",
  denoise:"Шумоподавление",
  two_shot:"Два плана",
  two_shot_auto:"Автосмена планов",
} as const;
type Toggle = keyof typeof labels;
const names = {selection:"Отбор",plan:"План монтажа",render:"Рендер"} as const;
type Layers = Record<Scope, PresetLayer>;
const blank = ():Layers => ({global_layer:{},project_layer:{},clip_layer:{}});

export function PresetPanel() {
  const q = useQuery({queryKey:["preset-preview"],queryFn:api.presetDefaults,retry:false,
    refetchOnWindowFocus:false});
  const [scope,setScope] = useState<Scope>("global_layer");
  const [layers,setLayers] = useState<Layers>(blank);
  const [result,setResult] = useState<PresetPreview|null>(null);
  const [busy,setBusy] = useState(false);
  const [failed,setFailed] = useState(false);
  const data = q.data;
  const usable = !!data && data.schema_version === 1 && !q.isError && !q.isFetching;
  const selected = layers[scope];
  const edit = (value:PresetLayer) => {
    setLayers(old=>({...old,[scope]:{...old[scope],...value}}));
    setResult(null);setFailed(false);
  };
  async function check() {
    if (!usable || !data || busy) return;
    setBusy(true);setFailed(false);setResult(null);
    try {
      const next = await api.presetPreview({base_revision:data.base_revision,...layers});
      if(next.schema_version!==1 || next.base_revision!==data.base_revision) throw Error("stale");
      setResult(next);
    } catch {setFailed(true);} finally {setBusy(false);}
  }
  const visible = result && result.base_revision===data?.base_revision ? result : null;
  return <section className="pipeline-settings preset-panel">
    <h2>Пресеты и автоматические инструменты</h2>
    <p className="secondary">Пробные уровни настроек: глобальный → проект → ролик. Не сохраняются и не меняют принятый монтаж.</p>
    {q.isLoading && <p role="status">Загрузка пресетов…</p>}
    {(q.isError || (data && !usable && !q.isFetching)) && <p role="alert">Пресеты недоступны. <button onClick={()=>void q.refetch()}>Обновить пресеты</button></p>}
    {usable && data && <>
      <label>Уровень пробных настроек
        <select value={scope} disabled={busy} onChange={e=>setScope(e.target.value as Scope)}>
          {Object.entries(scopeLabels).map(([k,n])=><option key={k} value={k}>{n}</option>)}
        </select>
      </label>
      <label>Пресет длительности отбора
        <select value={selected.duration_preset??""} disabled={busy} onChange={e=>edit({duration_preset:e.target.value ? e.target.value as NonNullable<PresetLayer["duration_preset"]>:null})}>
          <option value="">Наследовать</option>
          {data.presets.map(p=><option key={p.name} value={p.name}>{p.name} · {p.min_sec}–{p.max_sec} с</option>)}
        </select>
      </label>
      {(Object.keys(labels) as Toggle[]).map(key=><label key={key}>{labels[key]}
        <span className="secondary">В конфигурации: {data.base[key]?"включено":"выключено"}</span>
        <select value={selected[key]===true?"on":selected[key]===false?"off":""} disabled={busy}
          onChange={e=>edit({[key]:e.target.value===""?null:e.target.value==="on"})}>
          <option value="">Наследовать</option><option value="on">Включить</option><option value="off">Выключить</option>
        </select>
      </label>)}
      <p className="secondary">Автосмена действует только при включённых двух планах; остальные условия проверяются при будущем запуске. Настройки не удаляют ручные правки.</p>
      <button disabled={busy} onClick={()=>{setLayers(old=>({...old,[scope]:{}}));setResult(null);setFailed(false);}}>Сбросить этот уровень</button>
      <button disabled={busy} onClick={()=>void check()}>Сравнить пресет</button>
      {failed && <p role="alert">Не удалось проверить пресет. Обновите базовую конфигурацию. <button disabled={busy} onClick={()=>{setResult(null);setFailed(false);void q.refetch();}}>Обновить базу</button></p>}
      {visible && <section aria-label="Итог пробных настроек" className="target-detail">
        <h3>Итог пробных настроек</h3>
        <p>Пресет: {visible.effective.duration_preset}</p>
        {(Object.keys(labels) as Toggle[]).map(k=><p key={k}>{labels[k]}: {visible.effective[k]?"включено":"выключено"}{visible.changed_fields.includes(k)?" (изменено)":""}</p>)}
        {visible.effective.two_shot_auto && !visible.two_shot_auto_active && <p role="status">Автосмена неактивна: два плана выключены.</p>}
        <p role="status">{visible.changed_fields.length===0?"Изменений нет.":"Затронутые стадии: "+visible.invalidates.map(s=>names[s]).join(", ")}</p>
        <p className="secondary">Ничего не сохранено и не запущено.</p>
      </section>}
    </>}
  </section>;
}
