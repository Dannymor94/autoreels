import { useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api, type JobCommand, type SyntheticJob } from "../api/client";

const statusNames = {queued:"В очереди",running:"Выполняется",success:"Успешно",empty:"Нет подходящих клипов",failed:"Ошибка",cancelled:"Отменено"} as const;
const stages = {queued:"Ожидание",prepare:"Подготовка",plan:"План монтажа",simulate_render:"Имитация рендера",done:"Завершено",cancelled:"Остановлено"} as const;
const targets = {desktop:"Компьютер",remote:"Сервер",mobile:"Телефон"} as const;
const outcomes = {success:"Успех",empty:"Пустой результат",failed:"Ошибка"} as const;
type Pending = {id:string, body:JobCommand};

export function Jobs() {
  const q = useQuery({queryKey:["synthetic-jobs"],queryFn:api.jobs,retry:false,
    refetchInterval:query=>query.state.data?.enabled ? 1000 : false});
  const [kind,setKind] = useState<SyntheticJob["target_kind"] | "">("");
  const [outcome,setOutcome] = useState<SyntheticJob["outcome"]>("success");
  const [busy,setBusy] = useState(false);
  const [error,setError] = useState(false);
  const pending = useRef<Pending | null>(null);
  const guard = useRef(false);
  async function send(command:Pending) {
    if (guard.current) return;
    guard.current=true; setBusy(true); setError(false); pending.current=command;
    try {
      await api.jobCommand(command.id,command.body);
      pending.current=null;
      await q.refetch();
    } catch { setError(true); }
    finally {guard.current=false;setBusy(false);}
  }
  function create() {
    if (!kind || pending.current || guard.current) return;
    void send({id:crypto.randomUUID(),body:{action:"create",target_kind:kind,outcome}});
  }
  function cancel(id:string) {
    if (pending.current || guard.current) return;
    void send({id,body:{action:"cancel",target_kind:null,outcome:null}});
  }
  const enabled=q.data?.enabled === true && !q.isError;
  const locked=busy || error || !enabled;
  return <main className="workspace jobs-screen">
    <div className="workspace-heading"><div><h1>Задания</h1><p className="secondary">Тестовая очередь — без обработки видео</p></div></div>
    {q.isLoading && <p role="status">Загрузка заданий…</p>}
    {q.isError && <p role="alert">Не удалось загрузить очередь. <button onClick={()=>void q.refetch()}>Повторить</button></p>}
    {q.data && !q.data.enabled && <p>Тестовая очередь отключена. Реальный запуск пока не подключён.</p>}
    {enabled && <><section className="pipeline-settings">
      <h2>Новое тестовое задание</h2>
      <label>Тестовый исполнитель<select value={kind} disabled={locked} onChange={e=>setKind(e.target.value as typeof kind)}>
        <option value="">Выберите устройство</option>
        {Object.entries(targets).map(([v,n])=><option key={v} value={v}>{n} (имитация)</option>)}
      </select></label>
      <label>Тестовый результат<select value={outcome} disabled={locked} onChange={e=>setOutcome(e.target.value as typeof outcome)}>
        {Object.entries(outcomes).map(([v,n])=><option key={v} value={v}>{n}</option>)}
      </select></label>
      <button disabled={locked || !kind} onClick={create}>Создать тестовое задание</button>
    </section>
    {error && <section role="alert" className="pipeline-settings"><p>Ответ не подтверждён. Повтор использует тот же идентификатор.</p>
      <button disabled={busy} onClick={()=>{if(pending.current)void send(pending.current);}}>Повторить запрос</button>
      <button disabled={busy} onClick={()=>{pending.current=null;setError(false);void q.refetch();}}>Обновить очередь без повтора</button>
    </section>}
    {!q.data?.jobs.length && <p>Заданий нет.</p>}
    {q.data?.jobs.map(j=><article key={j.job_id} className="pipeline-settings job-row">
      <h2>{targets[j.target_kind]} · {statusNames[j.status]}</h2>
      <p className="secondary">{stages[j.stage]} · {j.progress}% · тестовая версия {j.revision}</p>
      <progress max={100} value={j.progress} aria-label="Прогресс задания"/>
      <p className="secondary">Имитация · {j.job_id.slice(0,8)}</p>
      {(j.status==="queued"||j.status==="running")&&<button disabled={locked} onClick={()=>cancel(j.job_id)}>Отменить задание</button>}
    </article>)}</>}
  </main>;
}
