import { useEffect, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api, type CutPreview, type CutCommand } from "../api/client";

const queryKey = ["synthetic-cut"];

const seconds = (n:number) => n.toFixed(2)+" с";
const equal = (a:number[],b:number[]) => a.length===b.length && a.every((v,i)=>v===b[i]);

function sourceTime(plan:CutPreview,t:number) {
  const pos=Math.max(0,Math.min(plan.duration,t));
  const w=plan.windows.find(w=>pos<w.output_end) ?? plan.windows[plan.windows.length-1];
  return w.source_start+Math.max(0,Math.min(w.source_end-w.source_start,pos-w.output_start));
}

export function SyntheticCutPreview() {
  const qc=useQueryClient();
  const q=useQuery({queryKey,queryFn:api.syntheticCut,retry:false,
    refetchOnWindowFocus:false,refetchOnReconnect:false});
  const [draft,setDraft]=useState<number[]|null>(null);
  const removed=q.data?.current_removed??[];
  const selected=draft??removed;
  const [busy,setBusy]=useState(false);
  const [writeError,setWriteError]=useState(false);
  const pending=useRef<CutCommand|null>(null);
  const guard=useRef(false);
  const [position,setPosition]=useState(0);
  const [ready,setReady]=useState(false);
  const [playing,setPlaying]=useState(false);
  const [error,setError]=useState(false);
  const video=useRef<HTMLVideoElement>(null);
  const plan=q.data?.plans.find(p=>equal(p.removed,removed)&&p.plan_sha256===q.data?.plan_sha256);
  const baseline=q.data?.plans.find(p=>!p.removed.length);
  const candidate=q.data?.plans.find(p=>equal(p.removed,selected));
  const locked=busy||writeError||q.isError||q.isFetching||(q.data?.revision??0)>=100;
  const usable=!!plan && !!baseline && ready && !error && !q.isError && !busy;

  function move(t:number) {
    if(!plan||!video.current||!usable)return;
    const pos=Math.max(0,Math.min(plan.duration,t));
    video.current.currentTime=sourceTime(plan,pos);
    setPosition(pos);
  }
  async function send(command:CutCommand) {
    if(guard.current)return;
    guard.current=true;pending.current=command;setBusy(true);setWriteError(false);
    video.current?.pause();setPlaying(false);
    try {
      const result=await api.saveSyntheticCut(command);
      qc.setQueryData(queryKey,result);
      pending.current=null;setDraft(null);
    } catch {setWriteError(true);}
    finally {guard.current=false;setBusy(false);}
  }
  function changePlan(next:CutPreview) {
    const state=q.data;
    if(!state||locked||pending.current||guard.current)return;
    void send({op_id:crypto.randomUUID(),base_revision:state.revision,
      base_plan_sha256:state.plan_sha256,clip_uid:state.clip_uid,
      candidate_plan_sha256:next.plan_sha256,removed:next.removed});
  }

  useEffect(()=>{
    const v=video.current;
    if(!plan||!v||!ready||error)return;
    v.pause();setPlaying(false);setPosition(0);v.currentTime=sourceTime(plan,0);
  },[plan,ready,error]);

  useEffect(()=>{
    if(!playing||!plan||!usable)return;
    let frame=0;
    const update=()=>{
      const v=video.current;
      if(!v||v.paused||v.ended)return;
      if(v.seeking) {frame=requestAnimationFrame(update);return;}
      const t=v.currentTime;
      const w=plan.windows.find(w=>t>=w.source_start-0.002 && t<w.source_end);
      if(w){
        setPosition(Math.max(w.output_start,Math.min(w.output_end,w.output_start+t-w.source_start)));
      }else{
        const next=plan.windows.find(w=>w.source_start>t);
        if(next){v.currentTime=next.source_start;setPosition(next.output_start);}
        else{v.pause();setPosition(plan.duration);return;}
      }
      frame=requestAnimationFrame(update);
    };
    frame=requestAnimationFrame(update);
    return ()=>cancelAnimationFrame(frame);
  },[playing,plan,usable]);

  if(!q.data?.enabled || !plan || !baseline)return null;
  function toggle(n:number) {
    setDraft(prev=>{const current=prev??removed;return current.includes(n)?current.filter(x=>x!==n):[...current,n].sort((a,b)=>a-b);});
  }
  const at=sourceTime(plan,position);
  const cue=q.data.sentences.find(s=>!removed.includes(s.number)&&s.start<=at&&at<s.end);
  const duration=q.data.source_duration;
  return <section className="pipeline-settings synthetic-cut" aria-label="Демонстрационная нарезка предложений">
    <h2>Удаление предложений</h2>
    <p className="secondary">Отдельное тестовое видео без речи. Выбери соседние предложения. Нарезка сохраняется только в демонстрационном проекте.</p>
    <p>Ревизия нарезки: {q.data.revision}</p>
    <div className="synthetic-word-list">
      {q.data.sentences.map(s=><button type="button" key={s.number}
        aria-pressed={selected.includes(s.number)} className={removed.includes(s.number)?"cut-removed":""}
        disabled={locked} onClick={()=>toggle(s.number)}>{s.text}</button>)}
    </div>
    <div className="synthetic-word-list">
      <button disabled={locked||!selected.length||!candidate||equal(removed,selected)} onClick={()=>candidate&&changePlan(candidate)}>Убрать выбранное</button>
      <button disabled={locked||!removed.length} onClick={()=>changePlan(baseline)}>Восстановить исходное</button>
    </div>
    {!!selected.length&&!candidate&&<p role="status">Выбери один непрерывный диапазон, оставив хотя бы одно предложение.</p>}
    {busy&&<p role="status">Сохранение нарезки…</p>}
    {writeError&&<div role="alert">
      <p>Сохранение не подтверждено или ревизия изменилась.</p>
      <button disabled={busy} onClick={()=>{if(pending.current)void send(pending.current);}}>Повторить нарезку</button>
      <button disabled={busy} onClick={()=>{pending.current=null;setDraft(null);setWriteError(false);void q.refetch();}}>Обновить нарезку</button>
    </div>}
    {q.isError&&<p role="alert">Нарезка недоступна. <button onClick={()=>void q.refetch()}>Обновить нарезку</button></p>}
    {q.data.revision>=100&&<p>Лимит демонстрационных ревизий достигнут.</p>}
    <div className="synthetic-preview">
      <video ref={video} className="cut-preview-video synthetic-preview-video" playsInline muted preload="metadata"
        src="/synthetic-editor-preview.mp4" aria-label="Предпросмотр пробной нарезки"
        onLoadedMetadata={()=>{const v=video.current;if(v&&Math.abs(v.duration-duration)<0.05){v.currentTime=sourceTime(plan,0);setReady(true);}else setError(true);}}
        onPlay={()=>setPlaying(true)} onPause={()=>setPlaying(false)}
        onEnded={()=>{setPlaying(false);setPosition(plan.duration);}}
        onError={()=>{setError(true);setPlaying(false);}} />
      {!error&&<div className="synthetic-preview-cue">{cue?.text??""}</div>}
    </div>
    <div className="cut-track-label"><strong>Исходник</strong><span>{seconds(duration)}</span></div>
    <div className="cut-track" role="img" aria-label="Сохранённые участки исходного видео">
      {plan.windows.map((w,i)=><span key={i} style={{left:(w.source_start/duration*100)+"%",width:((w.source_end-w.source_start)/duration*100)+"%"}}/>)}
    </div>
    <div className="cut-track-label"><strong>Монтаж</strong><span>{seconds(plan.duration)} · убрано {seconds(Math.max(0,baseline.duration-plan.duration))}</span></div>
    <div className="cut-track cut-output" role="img" aria-label="Последовательность фрагментов после нарезки">
      {plan.windows.map((w,i)=><span key={i} style={{left:(w.output_start/plan.duration*100)+"%",width:((w.output_end-w.output_start)/plan.duration*100)+"%"}}/>)}
    </div>
    <label>Позиция монтажа
      <input type="range" min={0} max={plan.duration} step={0.01} value={position} disabled={!usable}
        onChange={e=>{video.current?.pause();move(Number(e.target.value));}} />
    </label>
    <p className="secondary">Монтаж: {seconds(position)} / {seconds(plan.duration)}</p>
    <button disabled={!usable} onClick={()=>{
      const v=video.current;if(!v)return;
      if(!v.paused){v.pause();return;}
      if(position>=plan.duration-0.01)move(0);
      void v.play().catch(()=>{setError(true);setPlaying(false);});
    }}>{playing?"Пауза":"Смотреть нарезку"}</button>
    {error&&<p role="alert">Видео недоступно; план нарезки можно посмотреть без воспроизведения.</p>}
    <p className="secondary">Предпросмотр пропускает вырезанные интервалы на исходном видео. Стыки приблизительные, без финального рендера.</p>
    <details><summary>История нарезки ({q.data.history.length})</summary>
      {q.data.history.map(h=><p key={h.revision}>#{h.revision} · {h.removed.length?"Убраны предложения "+h.removed.join(", "):"Исходное восстановлено"}</p>)}
    </details>
  </section>;
}
