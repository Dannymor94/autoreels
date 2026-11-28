import {useRef,useState} from "react";
import {useQuery,useQueryClient} from "@tanstack/react-query";
import {api} from "../api/client";

const queryKey=["synthetic-whole-export"];

export function WholeExportControls({revision,digest,disabled}:{revision:number;digest:string;disabled:boolean}){
  const qc=useQueryClient();
  const q=useQuery({queryKey,queryFn:api.wholeExport,retry:false,
    refetchOnWindowFocus:false,refetchOnReconnect:false});
  const [busy,setBusy]=useState(false);
  const [failed,setFailed]=useState(false);
  const guard=useRef(false);
  const state=q.data;
  if(!state||!state.enabled)return null;
  const ready=state.status==="ready";
  async function launch(){
    if(!ready||disabled||guard.current||failed)return;
    guard.current=true;setBusy(true);
    try{qc.setQueryData(queryKey,await api.startWholeExport({revision,plan_sha256:digest}));}
    catch{setFailed(true);}
    finally{guard.current=false;setBusy(false);}
  }
  async function refresh(){
    const result=await q.refetch();
    if(result.isSuccess)setFailed(false);
  }
  return <section aria-label="Локальный тестовый экспорт">
    <h3>Локальный тестовый экспорт</h3>
    <p className="secondary">Один запуск в заранее подготовленной тестовой папке. Не экспорт реального видео.</p>
    {busy?<p role="status">Выполняется локальный рендер…</p>:
      state.status==="success"?<>
        <p>Экспорт готов · ревизия {state.editor_revision}</p>
        <a href="/api/synthetic-whole-export/media" target="_blank" rel="noreferrer">Открыть MP4</a>
        {state.editor_plan_sha256!==digest&&<p className="secondary">Это предыдущая сохранённая версия монтажа.</p>}
      </>:ready?<button disabled={disabled||failed||q.isFetching} onClick={()=>void launch()}>Экспортировать сохранённое видео</button>:
        <p role="status">Состояние задания: {state.status}. Повторный запуск в этой папке отключён.</p>}
    {failed&&<p role="alert">Ответ экспорта не подтверждён. Не запускай повторно без сверки.</p>}
    <button disabled={busy||q.isFetching} onClick={()=>void refresh()}>Обновить статус экспорта</button>
  </section>;
}
