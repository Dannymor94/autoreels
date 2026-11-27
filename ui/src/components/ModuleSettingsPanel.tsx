import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api, type ModuleDraft, type ModuleSettingsView } from "../api/client";

const labels = {
  hook_rescue:"Подбор хуков (резервный поиск)",
  filler_cut:"Удаление слов-паразитов и пауз",
  two_shot:"Переключение крупности кадра",
  loudnorm:"Нормализация громкости",
  denoise:"Шумоподавление",
  music:"Фоновая музыка",
} as const;
const stages = {proposals:"новые предложения",plan:"план монтажа",render:"рендер"} as const;
const status = {missing:"Конфигурация отсутствует",invalid:"Конфигурация невалидна",blocked:"Конфигурация недоступна"} as const;
const word = (value:boolean) => value ? "вкл." : "выкл.";

export function ModuleSettingsPanel() {
  const q = useQuery({queryKey:["module-settings"],queryFn:()=>api.moduleSettings(),retry:false});
  const data = q.data;
  const [draft,setDraft] = useState<ModuleDraft>({});
  const [result,setResult] = useState<ModuleSettingsView|null>(null);
  const [busy,setBusy] = useState(false);
  const [error,setError] = useState(false);
  const changed=Object.keys(draft).length>0;
  const ready=data?.schema_version===1 && data.status==="configured" && !q.isError && !q.isFetching;
  const stale=!!result && result.base_sha256!==data?.base_sha256;
  async function check(){
    if(!ready||busy||!changed)return;
    setBusy(true);setError(false);setResult(null);
    try {
      const next=await api.moduleSettings(draft);
      if(next.schema_version!==1||next.status!=="configured")throw Error("configuration unavailable");
      setResult(next);
    } catch {setError(true);}
    finally{setBusy(false);}
  }
  function reset(){
    setDraft({});setResult(null);setError(false);void q.refetch();
  }
  return <section className="pipeline-settings module-settings">
    <h2>Модули автомонтажа</h2>
    <p className="secondary">Пробные параметры на основе текущей конфигурации узла. Это не настройки сохранённого проекта.</p>
    {q.isLoading&&<p role="status">Загрузка модулей…</p>}
    {(q.isError||(data&&data.schema_version!==1))&&<p role="alert">Модули недоступны. <button onClick={()=>void q.refetch()}>Повторить</button></p>}
    {data?.schema_version===1&&data.status!=="configured"&&<p role="status">{status[data.status]}.</p>}
    {ready&&data&&<>
      {data.modules.map(m=><div key={m.module} className="module-setting">
        <label>{labels[m.module]}<select aria-label={labels[m.module]} value={draft[m.module]??""} disabled={busy}
          onChange={e=>{
            const value=e.target.value;
            setDraft(old=>{const next={...old};if(value==="on"||value==="off")next[m.module]=value;else delete next[m.module];return next;});
            setResult(null);setError(false);
          }}>
          <option value="">Не менять ({word(m.configured)})</option>
          <option value="on">Включить</option><option value="off">Выключить</option>
        </select></label>
        <p className="secondary">{m.kind==="automation"?"Только новые предложения, не принятые правки.":"Влияет на будущий результат."} {!m.available?"Исполнение пока недоступно.":""}</p>
      </div>)}
      <button disabled={!changed||busy} onClick={()=>void check()}> {busy?"Проверка…":"Показать изменения"}</button>
      <button disabled={busy||!changed&&!result} onClick={reset}>Сбросить пробные изменения</button>
      {error&&<p role="alert">Не удалось проверить изменения.</p>}
      {stale&&<p role="alert">Исходная конфигурация изменилась. Сбросьте пробные изменения.</p>}
      {result&&!stale&&<section aria-label="Предварительный результат">
        <p role="status">{result.invalidates.length?"Потребуется пересчитать: "+result.invalidates.map(s=>stages[s]).join(", "):"Изменений нет."}</p>
        {result.modules.filter(m=>m.configured!==m.proposed).map(m=><p key={m.module}>{labels[m.module]}: {word(m.configured)} → {word(m.proposed)}</p>)}
      </section>}
    </>}
    <p className="secondary">Применение не подключено. Защита принятых правок будет проверяться на ревизии проекта; сейчас ничего не сохраняется и не запускается.</p>
  </section>;
}
