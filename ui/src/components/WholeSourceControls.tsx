import {useRef,useState} from "react";
import {useQuery,useQueryClient} from "@tanstack/react-query";
import {api,type CutPreview} from "../api/client";
import { WholeExportControls } from "./WholeExportControls";

const queryKey=["synthetic-whole"];
const seconds=(n:number)=>n.toFixed(2)+" с";
const equal=(a:number[],b:number[])=>a.length===b.length&&a.every((n,i)=>n===b[i]);

export function WholeSourceControls(){
  const qc=useQueryClient();
  const q=useQuery({queryKey,queryFn:api.syntheticWhole,retry:false,
    refetchOnWindowFocus:false,refetchOnReconnect:false});
  const [draft,setDraft]=useState<number[]|null>(null);
  const [busy,setBusy]=useState(false);
  const [failed,setFailed]=useState(false);
  const guard=useRef(false);
  const state=q.data;
  if(q.isError)return <p role="alert">План целого видео недоступен. <button onClick={()=>void q.refetch()}>Обновить</button></p>;
  if(!state)return <p className="secondary">Загрузка плана целого видео…</p>;
  if(!state.enabled||!state.review)return null;
  const selected=draft??state.current_removed;
  const target=state.plans.find(p=>equal(p.removed,selected));
  const locked=busy||failed||q.isFetching||state.revision>=100;
  const changed=!equal(selected,state.current_removed);
  async function save(p:CutPreview,navigation?:"undo"|"redo"){
    if(!state||locked||guard.current)return;
    guard.current=true;setBusy(true);setFailed(false);
    try{
      const result=await api.saveSyntheticWhole({op_id:crypto.randomUUID(),
        base_revision:state.revision,base_plan_sha256:state.plan_sha256,clip_uid:state.clip_uid,
        candidate_plan_sha256:p.plan_sha256,removed:p.removed,navigation});
      qc.setQueryData(queryKey,result);setDraft(null);
    }catch{setFailed(true);}
    finally{guard.current=false;setBusy(false);}
  }
  async function refresh(){
    const result=await q.refetch();
    if(result.isSuccess){setDraft(null);setFailed(false);}
  }
  const last=state.review.sentences.length;
  return <section aria-label="Очистка целого видео">
    <h3>Очистка целого видео</h3>
    <p className="secondary">Тестовый проект. Выбери фразы вручную. Первая и последняя сохраняются.</p>
    <p>Ревизия целого видео: {state.revision}</p>
    {state.review.sentences.map(s=><label key={s.number}>
      <input type="checkbox" aria-label={"Убрать фразу "+s.number}
        checked={selected.includes(s.number)} disabled={locked||s.number===1||s.number===last}
        onChange={e=>setDraft(e.target.checked?[...selected,s.number].sort((a,b)=>a-b):selected.filter(n=>n!==s.number))}/>
      {" #"+s.number+" · "+s.text}
    </label>)}
    {target?<><p>Длительность плана: {seconds(target.duration)}</p>
      <p className="secondary">Убрано: {seconds(state.review.source_duration_ms/1000-target.duration)}</p>
      <div className="cut-track" role="img" aria-label="Сохраняемые интервалы целого видео">
        {target.windows.map((w,i)=><span key={i} style={{left:w.source_start/state.review!.source_duration_ms*100000+"%",
          width:(w.source_end-w.source_start)/state.review!.source_duration_ms*100000+"%"}}/>)}
      </div>
    </>:<p role="alert">Для этого выбора нет безопасного плана.</p>}
    <button disabled={locked||!target||!changed} onClick={()=>target&&void save(target)}>Сохранить очистку видео</button>
    <button disabled={locked||!changed} onClick={()=>setDraft(null)}>Сбросить выбор</button>
    <button disabled={locked||changed||!state.undo} onClick={()=>state.undo&&void save(state.undo,"undo")}>Отменить очистку</button>
    <button disabled={locked||changed||!state.redo} onClick={()=>state.redo&&void save(state.redo,"redo")}>Повторить очистку</button>
    {failed&&<p role="alert">Не удалось подтвердить сохранение. <button disabled={busy||q.isFetching} onClick={()=>void refresh()}>Обновить состояние</button></p>}
    <WholeExportControls revision={state.revision} digest={state.plan_sha256} disabled={busy||failed||q.isFetching||changed}/>
    <p className="secondary">Реальные видео не используются.</p>
  </section>;
}
