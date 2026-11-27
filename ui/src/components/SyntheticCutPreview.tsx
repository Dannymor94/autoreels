import { useEffect, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api, type CutPreview } from "../api/client";

const seconds = (n:number) => n.toFixed(2)+" с";
const equal = (a:number[],b:number[]) => a.length===b.length && a.every((v,i)=>v===b[i]);

function sourceTime(plan:CutPreview,t:number) {
  const pos=Math.max(0,Math.min(plan.duration,t));
  const w=plan.windows.find(w=>pos<w.output_end) ?? plan.windows[plan.windows.length-1];
  return w.source_start+Math.max(0,Math.min(w.source_end-w.source_start,pos-w.output_start));
}

export function SyntheticCutPreview() {
  const q=useQuery({queryKey:["synthetic-cut"],queryFn:api.syntheticCut,retry:false,
    refetchOnWindowFocus:false,refetchOnReconnect:false});
  const [selected,setSelected]=useState<number[]>([]);
  const [removed,setRemoved]=useState<number[]>([]);
  const [position,setPosition]=useState(0);
  const [ready,setReady]=useState(false);
  const [playing,setPlaying]=useState(false);
  const [error,setError]=useState(false);
  const video=useRef<HTMLVideoElement>(null);
  const plan=q.data?.plans.find(p=>equal(p.removed,removed));
  const baseline=q.data?.plans.find(p=>!p.removed.length);
  const candidate=q.data?.plans.find(p=>equal(p.removed,selected));
  const usable=!!plan && !!baseline && ready && !error && !q.isError;

  function move(t:number) {
    if(!plan||!video.current||!usable)return;
    const pos=Math.max(0,Math.min(plan.duration,t));
    video.current.currentTime=sourceTime(plan,pos);
    setPosition(pos);
  }
  function changePlan(next:CutPreview) {
    const v=video.current;
    v?.pause();
    setPlaying(false);setRemoved(next.removed);setSelected([]);setPosition(0);
    if(v && ready && !error)v.currentTime=sourceTime(next,0);
  }

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
    setSelected(prev=>prev.includes(n)?prev.filter(x=>x!==n):[...prev,n].sort((a,b)=>a-b));
  }
  const cue=q.data.sentences.find(s=>!removed.includes(s.number)&&
    video.current && s.start<=video.current.currentTime && video.current.currentTime<s.end);
  const duration=q.data.source_duration;
  return <section className="pipeline-settings synthetic-cut" aria-label="Демонстрационная нарезка предложений">
    <h2>Удаление предложений</h2>
    <p className="secondary">Отдельное тестовое видео без речи. Выбери соседние предложения и проверь нарезку. Это черновик предпросмотра, не сохранение в проект.</p>
    <div className="synthetic-word-list">
      {q.data.sentences.map(s=><button type="button" key={s.number}
        aria-pressed={selected.includes(s.number)} className={removed.includes(s.number)?"cut-removed":""}
        onClick={()=>toggle(s.number)}>{s.text}</button>)}
    </div>
    <div className="synthetic-word-list">
      <button disabled={!selected.length||!candidate||equal(removed,selected)} onClick={()=>candidate&&changePlan(candidate)}>Убрать выбранное</button>
      <button disabled={!removed.length} onClick={()=>changePlan(baseline)}>Восстановить исходное</button>
    </div>
    {!!selected.length&&!candidate&&<p role="status">Выбери один непрерывный диапазон, оставив хотя бы одно предложение.</p>}
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
  </section>;
}
