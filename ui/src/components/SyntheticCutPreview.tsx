import { useEffect, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api, type CutPreview, type CutCommand } from "../api/client";
import type { components } from "../api/types.gen";
import { WholeSourceControls } from "./WholeSourceControls";
type Selection=components["schemas"]["CutSelectionEvent"];

const queryKey = ["synthetic-cut"];

const seconds = (n:number) => n.toFixed(2)+" с";
const equal = (a:number[],b:number[]) => a.length===b.length && a.every((v,i)=>v===b[i]);
const chronological = (order:number[]) => equal(order,[...order].sort((a,b)=>a-b));
const sameGraphic=(a:CutPreview,b:CutPreview|undefined)=>equal(a.graphic??[],b?.graphic??[]);
const sameDip=(a:CutPreview,b:CutPreview|undefined)=>(a.dip_ms??null)===(b?.dip_ms??null)&&sameGraphic(a,b);
const sameMusic=(a:CutPreview,b:CutPreview|undefined)=>equal(a.music??[],b?.music??[])&&sameDip(a,b);
const sameCrop=(a:CutPreview,b:CutPreview|undefined)=>equal(a.crop??[],b?.crop??[])&&sameMusic(a,b);
const frameNames=["Исходный кадр","Приблизить 1,6×","Сместить влево","Сместить вправо","Сместить вверх","Сместить вниз","Приблизить 2×"];
const frameCodes=[[],[18,30,60,100],[0,30,60,100],[36,30,60,100],[18,0,60,100],[18,60,60,100],[24,40,48,80]];
const rateAt=(plan:CutPreview,i:number)=>(plan.rates?.[i]??100)/100;
const windowIndexAt=(plan:CutPreview,t:number)=>{const i=plan.windows.findIndex(w=>t<w.output_end);return i<0?plan.windows.length-1:i;};

function sourceTime(plan:CutPreview,t:number) {
  const pos=Math.max(0,Math.min(plan.duration,t));
  const i=windowIndexAt(plan,pos),w=plan.windows[i];
  return w.source_start+Math.max(0,Math.min(w.source_end-w.source_start,(pos-w.output_start)*rateAt(plan,i)));
}

function BrollPreview({time,playing}:{time:number;playing:boolean}) {
  const ref=useRef<HTMLVideoElement>(null);
  const [failed,setFailed]=useState(false);
  function sync(){
    const v=ref.current;
    if(!v||v.readyState<1||failed)return;
    const target=Math.max(0,Math.min(time,v.duration-1/30));
    if(!v.seeking&&Math.abs(v.currentTime-target)>(playing?0.12:0.02))v.currentTime=target;
    if(playing&&v.paused)void v.play().catch(()=>{if(ref.current===v)setFailed(true);});
    if(!playing)v.pause();
  }
  useEffect(sync,[time,playing,failed]);
  return <>{failed?<span className="secondary">Предпросмотр недоступен</span>:
    <video ref={ref} src="/synthetic-broll.mp4" muted playsInline preload="auto" onLoadedMetadata={sync}
      onError={()=>setFailed(true)} style={{width:"100%",height:"100%",objectFit:"contain",display:"block"}}/>}</>;
}

export function SyntheticCutPreview() {
  const qc=useQueryClient();
  const q=useQuery({queryKey,queryFn:api.syntheticCut,retry:false,
    refetchOnWindowFocus:false,refetchOnReconnect:false});
  const [draft,setDraft]=useState<number[]|null>(null);
  const removed=q.data?.current_removed??[];
  const selected=draft??removed;
  const [busy,setBusy]=useState(false);
  const [graphicDraft,setGraphicDraft]=useState<number[]|null>(null);
  const [graphicError,setGraphicError]=useState(false);
  const [previewBusy,setPreviewBusy]=useState(false);
  const [writeError,setWriteError]=useState(false);
  const pending=useRef<CutCommand|null>(null);
  const guard=useRef(false);
  const [position,setPosition]=useState(0);
  const [ready,setReady]=useState(false);
  const [playing,setPlaying]=useState(false);
  const [error,setError]=useState(false);
  const video=useRef<HTMLVideoElement>(null);
  const audio=useRef<HTMLAudioElement>(null);
  const audioMode=useRef<"idle"|"montage"|"audition">("idle");
  const audioEpoch=useRef(0);
  const [audioError,setAudioError]=useState(false);
  const [auditioning,setAuditioning]=useState(false);
  const activeWindow=useRef(0);
  const plan=q.data?.plans.find(p=>equal(p.removed,removed)&&p.plan_sha256===q.data?.plan_sha256);
  const baseline=q.data?.plans.find(p=>!p.removed.length&&chronological(p.order)&&!p.trim&&!p.rates&&!p.crop&&!p.music&&!p.dip_ms&&!p.graphic);
  const untrimmed=q.data?.plans.find(p=>!p.trim&&!p.rates&&plan&&sameCrop(p,plan)&&equal(p.removed,plan.removed)&&equal(p.order,plan.order));
  const normalSpeed=q.data?.plans.find(p=>!p.rates&&plan&&sameCrop(p,plan)&&equal(p.removed,plan.removed)&&equal(p.order,plan.order)&&equal(p.trim??[],plan.trim??[]));
  const kept=(q.data?.sentences??[]).map(s=>s.number).filter(n=>!selected.includes(n));
  const currentOrder=plan?.order??[];
  const wantedOrder=chronological(currentOrder)?kept:
    [...currentOrder.filter(n=>kept.includes(n)),...kept.filter(n=>!currentOrder.includes(n))];
  const candidate=q.data?.plans.find(p=>!p.trim&&!p.rates&&sameCrop(p,plan)&&equal(p.removed,selected)&&equal(p.order,wantedOrder));
  const locked=busy||previewBusy||writeError||q.isError||q.isFetching||(q.data?.revision??0)>=100;
  const usable=!!plan && !!baseline && ready && !error && !q.isError && !busy;

  // The background track lives in output time, not source time. It is
  // intentionally approximate: the demo has no speech to duck against.
  function stopMusic(){
    audioEpoch.current++;
    audioMode.current="idle";
    audio.current?.pause();
    setAuditioning(false);
  }
  function syncMusic(p:CutPreview,pos:number,force=false){
    const a=audio.current;
    if(!a||!p.music||audioMode.current!=="montage")return;
    const fade=p.music[2]?Math.max(0,Math.min(1,pos/0.5,(p.duration-pos)/0.5)):1;
    a.volume=p.music[1]/100*fade;
    const length=a.duration;
    if(Number.isFinite(length)&&length>0&&!a.seeking){
      const target=((pos%length)+length)%length;
      const diff=Math.abs(a.currentTime-target);
      if(force||Math.min(diff,Math.abs(length-diff))>0.15)a.currentTime=target;
    }
  }
  function startMusic(p:CutPreview,pos:number,mode:"montage"|"audition"){
    const a=audio.current;
    if(!a||!p.music)return;
    const epoch=++audioEpoch.current;
    audioMode.current=mode;
    setAudioError(false);
    setAuditioning(mode==="audition");
    a.pause();a.playbackRate=1;a.loop=mode==="montage";
    a.volume=p.music[1]/100;
    if(mode==="montage")syncMusic(p,pos,true);
    else a.currentTime=0;
    // Invoke from the play click itself, not a delayed effect: mobile
    // browsers may require a user activation for audible playback.
    void a.play().catch(()=>{
      if(audioEpoch.current===epoch&&audio.current===a){
        audioMode.current="idle";setAuditioning(false);setAudioError(true);
      }
    });
  }
  function move(t:number) {
    if(!plan||!video.current||!usable)return;
    const pos=Math.max(0,Math.min(plan.duration,t));
    activeWindow.current=windowIndexAt(plan,pos);
    video.current.playbackRate=rateAt(plan,activeWindow.current);
    video.current.currentTime=sourceTime(plan,pos);
    setPosition(pos);
  }
  async function send(command:CutCommand) {
    if(guard.current)return;
    guard.current=true;pending.current=command;setBusy(true);setWriteError(false);
    video.current?.pause();stopMusic();setPlaying(false);
    try {
      const result=await api.saveSyntheticCut(command);
      qc.setQueryData(queryKey,result);
      pending.current=null;setDraft(null);
    } catch {setWriteError(true);}
    finally {guard.current=false;setBusy(false);}
  }
  function changePlan(next:CutPreview) {
    const state=q.data;
    if(!state||locked||pending.current||guard.current||next.plan_sha256===state.plan_sha256)return;
    void send({op_id:crypto.randomUUID(),base_revision:state.revision,
      base_plan_sha256:state.plan_sha256,clip_uid:state.clip_uid,
      candidate_plan_sha256:next.plan_sha256,removed:next.removed,
      ...(chronological(next.order)?{}:{order:next.order}),
      ...(next.trim?{trim:next.trim}:{}),
      ...(next.rates?{rates:next.rates}:{}),
      ...(next.crop?{crop:next.crop}:{}),
      ...(next.music?{music:next.music}:{}),
      ...(next.dip_ms?{dip_ms:next.dip_ms}:{}),
      ...(next.graphic?{graphic:next.graphic}:{})});
  }

  useEffect(()=>{
    const v=video.current;
    stopMusic();setAudioError(false);setGraphicDraft(null);setGraphicError(false);
    if(!plan||!v||!ready||error)return;
    v.pause();setPlaying(false);setPosition(0);activeWindow.current=0;v.playbackRate=rateAt(plan,0);v.currentTime=sourceTime(plan,0);
    const a=audio.current;
    return ()=>{audioEpoch.current++;audioMode.current="idle";a?.pause();};
  },[plan,ready,error]);

  useEffect(()=>{
    if(!playing||!plan||!usable)return;
    let frame=0;
    const update=()=>{
      const v=video.current;
      if(!v||v.paused||v.ended)return;
      if(v.seeking) {frame=requestAnimationFrame(update);return;}
      const t=v.currentTime;
      const w=plan.windows[activeWindow.current];
      if(t>=w.source_end){
        const next=plan.windows[activeWindow.current+1];
        if(next){activeWindow.current++;v.playbackRate=rateAt(plan,activeWindow.current);v.currentTime=next.source_start;setPosition(next.output_start);syncMusic(plan,next.output_start);}
        else{v.pause();stopMusic();setPosition(plan.duration);return;}
      }else{
        const pos=Math.max(w.output_start,Math.min(w.output_end,w.output_start+(t-w.source_start)/rateAt(plan,activeWindow.current)));
        setPosition(pos);syncMusic(plan,pos);
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
  function reordered(from:number,to:number) {
    const order=[...plan!.order];
    const a=order.indexOf(from), b=order.indexOf(to);
    if(a<0||b<0||a===b)return;
    order.splice(a,1);order.splice(b,0,from);
    const next=q.data?.plans.find(p=>!p.trim&&!p.rates&&sameCrop(p,plan)&&equal(p.removed,removed)&&equal(p.order,order));
    if(next)changePlan(next);
  }
  function canMove(from:number,to:number|undefined) {
    if(to===undefined)return false;
    const order=[...plan!.order];
    const a=order.indexOf(from),b=order.indexOf(to);
    order.splice(a,1);order.splice(b,0,from);
    return !!q.data?.plans.some(p=>!p.trim&&!p.rates&&sameCrop(p,plan)&&equal(p.removed,removed)&&equal(p.order,order));
  }
  function edgeOptions(index:number,edge:number) {
    return q.data?.plans.filter(p=>!p.rates&&sameCrop(p,plan)&&p.trim&&p.trim[0]===index&&p.trim[1]===edge&&
      equal(p.removed,removed)&&equal(p.order,plan!.order))??[];
  }
  function changeRate(index:number,pct:number) {
    if(!plan)return;
    const rates=plan.rates?[...plan.rates]:plan.windows.map(()=>100);
    rates[index]=pct;
    const next=q.data?.plans.find(p=>sameCrop(p,plan)&&equal(p.removed,removed)&&equal(p.order,plan.order)&&
      equal(p.trim??[],plan.trim??[])&&equal(p.rates??p.windows.map(()=>100),rates));
    if(next)changePlan(next);
  }
  const frames=q.data.plans.filter(p=>sameMusic(p,plan)&&equal(p.removed,removed)&&equal(p.order,plan.order)&&
    equal(p.trim??[],plan.trim??[])&&equal(p.rates??[],plan.rates??[]));
  const frameIndex=frameCodes.findIndex(c=>equal(c,plan.crop??[]));
  const [cx,cy,cw,ch]=plan.crop??[0,0,96,160];
  // Replay the server-validated immutable history; navigation is itself a CAS.
  const undo:Selection[]=[{revision:0,removed:[],candidate_plan_sha256:baseline.plan_sha256}];
  const redo:Selection[]=[];
  for(const h of [...q.data.history].reverse()){
    if(h.navigation==="undo"){if(undo.length>1)redo.push(undo.pop()!);}
    else if(h.navigation==="redo"){if(redo.length)undo.push(redo.pop()!);}
    else{undo.push(h);redo.length=0;}
  }
  function navigate(kind:"undo"|"redo"){
    const state=q.data;
    const target=kind==="undo"?undo[undo.length-2]:redo[redo.length-1];
    if(!state||!target||locked||pending.current||guard.current)return;
    void send({op_id:crypto.randomUUID(),base_revision:state.revision,base_plan_sha256:state.plan_sha256,
      clip_uid:state.clip_uid,candidate_plan_sha256:target.candidate_plan_sha256,
      removed:target.removed,order:target.order,trim:target.trim,rates:target.rates,crop:target.crop,music:target.music,dip_ms:target.dip_ms,graphic:target.graphic,navigation:kind});
  }
  const tracks=q.data.plans.filter(p=>sameDip(p,plan)&&equal(p.removed,removed)&&equal(p.order,plan.order)&&
    equal(p.trim??[],plan.trim??[])&&equal(p.rates??[],plan.rates??[])&&equal(p.crop??[],plan.crop??[]));
  function changeMusic(code:number[]){
    const next=tracks.find(p=>equal(p.music??[],code));
    if(next)changePlan(next);
  }
  const transitions=q.data.plans.filter(p=>sameGraphic(p,plan)&&equal(p.removed,removed)&&equal(p.order,plan.order)&&
    equal(p.trim??[],plan.trim??[])&&equal(p.rates??[],plan.rates??[])&&equal(p.crop??[],plan.crop??[])&&equal(p.music??[],plan.music??[]));
  function changeDip(ms:number){
    const next=transitions.find(p=>(p.dip_ms??0)===ms);
    if(next)changePlan(next);
  }
  const graphics=q.data.plans.filter(p=>(p.dip_ms??0)===(plan.dip_ms??0)&&equal(p.removed,removed)&&equal(p.order,plan.order)&&
    equal(p.trim??[],plan.trim??[])&&equal(p.rates??[],plan.rates??[])&&equal(p.crop??[],plan.crop??[])&&equal(p.music??[],plan.music??[]));
  const graphic=plan.graphic;
  const customGraphic=graphicDraft??graphic;
  const splitLayers=(code:number[]|null|undefined)=>code?Array.from({length:code.length/7},(_,i)=>code.slice(i*7,i*7+7)):[];
  const layers=splitLayers(graphic);
  const draftLayers=splitLayers(customGraphic);
  function editLayers(next:number[][]){
    setGraphicDraft(next.flat());setGraphicError(false);
  }
  async function applyGraphic(){
    const state=q.data;
    if(!state||!customGraphic||locked||guard.current)return;
    guard.current=true;setPreviewBusy(true);setGraphicError(false);
    let next:CutPreview|undefined;
    try{next=await api.previewGraphic(state,customGraphic);}
    catch{setGraphicError(true);}
    finally{guard.current=false;setPreviewBusy(false);}
    if(next)changePlan(next);
  }
  const graphicNames=(code:number[]|null|undefined)=>!code?"Без графики":code.length>7?("Графические слои: "+code.length/7):
    (code[6]===4?"Тестовый B-roll":code[6]===3?"Тестовое изображение":code[6]===1?"Белый":"Синий")+" · "+code[0]+"%, "+code[1]+"% · "+code[2]+"×"+code[3]+"% · "+seconds(code[4]/1000)+" – "+seconds(code[5]/1000);
  const dip=plan.dip_ms??0;
  const opacity=dip?Math.max(0,...plan.windows.slice(0,-1).map(w=>1-Math.abs(position-w.output_end)/(dip/1000))):0;
  const music=plan.music;
  const soundtrack=q.data.soundtracks.find(asset=>asset.number===music?.[0]);
  const at=sourceTime(plan,position);
  const cue=q.data.sentences.find(s=>!removed.includes(s.number)&&s.start<=at&&at<s.end);
  const duration=q.data.source_duration;
  return <section className="pipeline-settings synthetic-cut" aria-label="Демонстрационная нарезка предложений">
    <h2>Удаление предложений</h2>
    <p className="secondary">Отдельное тестовое видео без речи. Выбери соседние предложения. Нарезка сохраняется только в демонстрационном проекте.</p>
    <p>Ревизия нарезки: {q.data.revision}</p>
    <div className="synthetic-word-list">
      <button disabled={locked||undo.length<2} onClick={()=>navigate("undo")}>Отменить монтаж</button>
      <button disabled={locked||!redo.length} onClick={()=>navigate("redo")}>Повторить монтаж</button>
    </div>
    <div className="synthetic-word-list">
      {q.data.sentences.map(s=><button type="button" key={s.number}
        aria-pressed={selected.includes(s.number)} className={removed.includes(s.number)?"cut-removed":""}
        disabled={locked||!!plan.rates||!!plan.trim} onClick={()=>toggle(s.number)}>{s.text}</button>)}
    </div>
    <div className="synthetic-word-list">
      <button disabled={locked||!!plan.rates||!!plan.trim||!selected.length||!candidate||equal(removed,selected)} onClick={()=>candidate&&changePlan(candidate)}>Убрать выбранное</button>
      <button disabled={locked||plan.plan_sha256===baseline.plan_sha256} onClick={()=>changePlan(baseline)}>Восстановить исходное</button>
    </div>
    <h3>Порядок фрагментов</h3>
    <p className="secondary">Перетащи за ручку или используй стрелки. Вырезанные предложения не возвращаются.</p>
    <div aria-label="Порядок фрагментов" role="list">
      {plan.order.map((n,i)=>{
        const previous=plan.order[i-1],next=plan.order[i+1];
        const text=q.data?.sentences.find(s=>s.number===n)?.text??String(n);
        return <div key={n} role="listitem" data-reorder-number={n} className="synthetic-word-list">
          <button type="button" aria-label={"Перетащить "+text} disabled={locked||!!plan.rates||!!plan.trim} style={{touchAction:"none"}}
            onPointerDown={e=>{if(e.isPrimary&&e.button===0)e.currentTarget.setPointerCapture(e.pointerId);}}
            onPointerUp={e=>{
              if(!e.currentTarget.hasPointerCapture(e.pointerId))return;
              e.currentTarget.releasePointerCapture(e.pointerId);
              const target=document.elementFromPoint(e.clientX,e.clientY)?.closest("[data-reorder-number]");
              if(target)reordered(n,Number(target.getAttribute("data-reorder-number")));
            }}>↕</button>
          <span>{i+1}. {text}</span>
          <button type="button" aria-label={"Выше: "+text} disabled={locked||!!plan.rates||!!plan.trim||!canMove(n,previous)} onClick={()=>reordered(n,previous)}>↑</button>
          <button type="button" aria-label={"Ниже: "+text} disabled={locked||!!plan.rates||!!plan.trim||!canMove(n,next)} onClick={()=>reordered(n,next)}>↓</button>
        </div>;
      })}
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
    <div className="synthetic-preview framing-preview">
      <video ref={video} className="cut-preview-video synthetic-preview-video" playsInline muted preload="metadata"
        style={{width:96/cw*100+"%",height:160/ch*100+"%",left:-cx/cw*100+"%",top:-cy/ch*100+"%"}}
        src="/synthetic-editor-preview.mp4" aria-label="Предпросмотр пробной нарезки"
        onLoadedMetadata={()=>{const v=video.current;if(v&&Math.abs(v.duration-duration)<0.05){v.currentTime=sourceTime(plan,0);setReady(true);}else setError(true);}}
        onPlay={()=>setPlaying(true)} onPause={()=>{setPlaying(false);if(audioMode.current==="montage")stopMusic();}}
        onEnded={()=>{
          const v=video.current,next=plan.windows[activeWindow.current+1];
          if(v&&next){activeWindow.current++;v.playbackRate=rateAt(plan,activeWindow.current);v.currentTime=next.source_start;setPosition(next.output_start);
            startMusic(plan,next.output_start,"montage");
            void v.play().catch(()=>{stopMusic();setError(true);setPlaying(false);});}
          else{stopMusic();setPlaying(false);setPosition(plan.duration);}
        }}
        onError={()=>{stopMusic();setError(true);setPlaying(false);}} />
      {dip>0&&<div className="cut-dip-overlay" aria-hidden="true" style={{opacity}}/>}
      {layers.map((graphic,i)=>position>=graphic[4]/1000&&position<graphic[5]/1000&&<div key={i} className="cut-graphic-overlay" aria-hidden="true"
        style={{position:"absolute",left:graphic[0]+"%",top:graphic[1]+"%",width:graphic[2]+"%",height:graphic[3]+"%",background:graphic[6]>=3?"black":graphic[6]===1?"white":"blue",pointerEvents:"none"}}>
        {graphic[6]===3&&<img src="/synthetic-graphic-image.png" alt="" style={{width:"100%",height:"100%",objectFit:"contain",display:"block"}}/>}
        {graphic[6]===4&&<BrollPreview time={position-graphic[4]/1000} playing={playing&&!busy}/>} 
      </div>)}
      {!error&&<div className="synthetic-preview-cue">{cue?.text??""}</div>}
    </div>
    <h3>Кадрирование</h3>
    <label>Масштаб и положение кадра
      <select aria-label="Кадрирование" value={frameIndex} disabled={locked}
        onChange={e=>{const code=frameCodes[Number(e.target.value)];const next=frames.find(p=>equal(p.crop??[],code));if(next)changePlan(next);}}>
        {frameNames.map((name,i)=><option key={i} value={i} disabled={!frames.some(p=>equal(p.crop??[],frameCodes[i]))}>{name}</option>)}
      </select>
    </label>
    <p className="secondary">Настройка кадра сохраняет нарезку, порядок, границы и скорость. Субтитры остаются поверх кадра.</p>
    <div className="cut-track-label"><strong>Исходник</strong><span>{seconds(duration)}</span></div>
    <div className="cut-track" role="img" aria-label="Сохранённые участки исходного видео">
      {plan.windows.map((w,i)=><span key={i} style={{left:(w.source_start/duration*100)+"%",width:((w.source_end-w.source_start)/duration*100)+"%"}}/>)}
    </div>
    <div className="cut-track-label"><strong>Монтаж</strong><span>{seconds(plan.duration)}{plan.rates?" · скорость изменена":" · убрано "+seconds(Math.max(0,baseline.duration-plan.duration))}</span></div>
    <div className="cut-track cut-output" role="img" aria-label="Последовательность фрагментов после нарезки">
      {plan.windows.map((w,i)=><span key={i} style={{left:(w.output_start/plan.duration*100)+"%",width:((w.output_end-w.output_start)/plan.duration*100)+"%"}}/>)}
    </div>
    <h3>Переходы</h3>
    <label>Переход на стыках
      <select aria-label="Переход на стыках" value={dip} disabled={locked||transitions.length<2}
        onChange={e=>changeDip(Number(e.target.value))}>
        <option value={0}>Без эффекта</option>
        {[100,200,300].map(ms=><option key={ms} value={ms} disabled={!transitions.some(p=>p.dip_ms===ms)}>Затемнение · {ms} мс с каждой стороны</option>)}
      </select>
    </label>
    <div className="cut-track cut-transition" role="img" aria-label="Переходы на таймлайне">
      {dip>0&&plan.windows.slice(0,-1).map((w,i)=><span key={i} style={{left:((w.output_end-dip/1000)/plan.duration*100)+"%",width:(2*dip/1000/plan.duration*100)+"%"}}/>)}
    </div>
    <p className="secondary">Затемнение не меняет длительность, звук или время субтитров. Для несовместимых коротких фрагментов сначала отключи переход.</p>
    <h3>Графический слой</h3>
    <label>Положение, цвет и интервал
      <select aria-label="Графический слой" value={JSON.stringify(graphic??[])} disabled={locked||graphics.length<2}
        onChange={e=>{const next=graphics.find(p=>JSON.stringify(p.graphic??[])===e.target.value);if(next)changePlan(next);}}>
        {graphics.map(p=><option key={p.plan_sha256} value={JSON.stringify(p.graphic??[])}>{graphicNames(p.graphic)}</option>)}
      </select>
    </label>
    {customGraphic&&<details>
      <summary>Точная настройка слоя</summary>
      {draftLayers.map((layer,index)=><fieldset key={index}>
        <legend>Слой {index+1}</legend>
        {["X, %","Y, %","Ширина, %","Высота, %","Начало, мс","Конец, мс"].map((label,i)=>
          <label key={label}>{label}<input type="number" step={1} min={i===2||i===3?5:0}
            aria-label={draftLayers.length===1?label:"Слой "+(index+1)+" "+label}
            max={i<4?100:Math.floor(plan.duration*1000)}
            value={layer[i]} disabled={locked}
            onChange={e=>editLayers(draftLayers.map((item,j)=>j===index?item.map((n,k)=>k===i?e.currentTarget.valueAsNumber||0:n):item))}/></label>)}
        {layer[6]<=2&&<label>Цвет<select aria-label={"Цвет слоя "+(index+1)} value={layer[6]} disabled={locked}
          onChange={e=>editLayers(draftLayers.map((item,j)=>j===index?item.map((n,k)=>k===6?Number(e.currentTarget.value):n):item))}>
          <option value={1}>Белый</option><option value={2}>Синий</option></select></label>}
        {draftLayers.length>1&&<>
          <button type="button" disabled={locked||index===0} onClick={()=>{const next=[...draftLayers];[next[index-1],next[index]]=[next[index],next[index-1]];editLayers(next);}}>Слой {index+1} ниже</button>
          <button type="button" disabled={locked||index===draftLayers.length-1} onClick={()=>{const next=[...draftLayers];[next[index+1],next[index]]=[next[index],next[index+1]];editLayers(next);}}>Слой {index+1} выше</button>
          <button type="button" disabled={locked} onClick={()=>editLayers(draftLayers.filter((_,j)=>j!==index))}>Удалить слой {index+1}</button>
        </>}
      </fieldset>)}
      <button type="button" disabled={locked||draftLayers.length>=4||draftLayers.some(layer=>layer[6]>2)||plan.duration<0.1}
        onClick={()=>editLayers([...draftLayers,[20,10,20,20,0,Math.min(500,Math.floor(plan.duration*1000)),2]])}>Добавить графический слой</button>
      {graphicDraft&&<button type="button" disabled={locked} onClick={()=>{setGraphicDraft(null);setGraphicError(false);}}>Отменить настройку слоёв</button>}
      <button type="button" disabled={locked||!graphicDraft} onClick={()=>void applyGraphic()}>Применить параметры</button>
      {graphicError&&<p role="alert">Проверь положение, размеры и интервал слоя.</p>}
    </details>}
    <div className="cut-track cut-music" role="img" aria-label="Графический слой на таймлайне">
      {layers.map((layer,i)=><span key={i} style={{left:layer[4]/1000/plan.duration*100+"%",width:(layer[5]-layer[4])/1000/plan.duration*100+"%"}}/>)}
    </div>
    <p className="secondary">До четырёх одноцветных слоёв, снизу вверх. Фото и видео пока по одному. Для других изменений монтажа сначала убери слои. Отмена и повтор сохраняют набор.</p>
    <h3>Звуковые дорожки</h3>
    <div className="cut-track-label"><strong>Фоновая дорожка</strong><span>{music?seconds(plan.duration):"Нет"}</span></div>
    <div className="cut-track cut-music" role="img" aria-label="Фоновая дорожка на таймлайне">
      {music&&<span style={{left:0,width:"100%"}}/>}
    </div>
    <label>Фоновый звук
      <select aria-label="Фоновый звук" value={music?.[0]??0} disabled={locked}
        onChange={e=>{const n=Number(e.target.value);changeMusic(n?[n,...(music?.slice(1)??[20,1,1])]:[]);}}>
        <option value={0}>Без фонового звука</option>
        {q.data.soundtracks.map(asset=><option key={asset.number} value={asset.number}>{asset.label}</option>)}
      </select>
    </label>
    <details>
      <summary>Библиотека звуков ({q.data.soundtracks.length})</summary>
      {q.data.soundtracks.map(asset=><div key={asset.number}>
        <strong>{asset.label}</strong>
        <p className="secondary">Формат: {asset.format.toUpperCase()} · {asset.rights==="synthetic"?"Синтетический ассет":asset.rights}</p>
        <p className="secondary">{asset.rights_note}</p>
        <p className="secondary">SHA-256: <code style={{overflowWrap:"anywhere"}}>{asset.sha256}</code></p>
      </div>)}
      <p className="secondary">Только встроенные тестовые файлы; импорт пользовательских медиа отключён.</p>
    </details>
    {music&&soundtrack&&<>
      <label>Громкость фона
        <select aria-label="Громкость фона" value={music[1]} disabled={locked}
          onChange={e=>changeMusic([music[0],Number(e.target.value),music[2],music[3]])}>
          {[10,20,30].map(n=><option key={n} value={n}>{n}%</option>)}
        </select>
      </label>
      <label><input type="checkbox" checked={!!music[2]} disabled={locked}
        onChange={e=>changeMusic([music[0],music[1],Number(e.target.checked),music[3]])}/> Плавное появление и затухание (0,5 с)</label>
      <label><input type="checkbox" checked={!!music[3]} disabled={locked}
        onChange={e=>changeMusic([music[0],music[1],music[2],Number(e.target.checked)])}/> Приглушать фон под голос</label>
      <audio key={music[0]} ref={audio} preload="metadata" src={"/synthetic-soundtrack-"+music[0]+".wav"}
        aria-label="Тестовая звуковая дорожка" onLoadedMetadata={()=>syncMusic(plan,position,true)}
        onEnded={()=>{if(audioMode.current==="audition")stopMusic();}}
        onError={()=>{stopMusic();setAudioError(true);}}/>
      <button disabled={locked||playing} onClick={()=>{
        if(auditioning)stopMusic();else startMusic(plan,0,"audition");
      }}>{auditioning?"Остановить фон":"Прослушать фон"}</button>
      {audioError&&<p role="status">Фон не воспроизводится в этом браузере. Настройки монтажа сохранены.</p>}
      <p className="secondary">«Смотреть нарезку» воспроизводит видео и фон вместе. Громкость и фейды приблизительные; приглушение под реальную речь и нормализация выполняются при рендере.</p>
    </>}
    <h3>Границы фрагментов</h3>
    <p className="secondary">Выбирай безопасные границы по карте речи. Пока можно изменять одну границу за раз; для другой границы, удаления или перестановки сначала сбрось это изменение.</p>
    {plan.windows.map((w,index)=><div key={index} className="synthetic-word-list">
      <strong>Фрагмент {index+1}</strong>
      {[1,2].map(edge=>{
        const options=edgeOptions(index,edge);
        const active=plan.trim?.[0]===index&&plan.trim?.[1]===edge;
        const label=(edge===1?"Начало":"Конец")+" фрагмента "+(index+1);
        const original=untrimmed?.windows[index];
        return <label key={edge}>{label}
          <select aria-label={label} value={active?plan.plan_sha256:untrimmed?.plan_sha256??""}
            disabled={locked||!!plan.rates||!untrimmed||!options.length||!!plan.trim&&!active}
            onChange={e=>{const next=[untrimmed,...options].find(p=>p?.plan_sha256===e.target.value);if(next)changePlan(next);}}>
            <option value={untrimmed?.plan_sha256??""}>{seconds((edge===1?original?.source_start:original?.source_end)??(edge===1?w.source_start:w.source_end))} · исходная</option>
            {options.map(p=><option key={p.plan_sha256} value={p.plan_sha256}>{seconds(p.trim![2]/1000)}</option>)}
          </select>
        </label>;
      })}
    </div>)}
    {plan.trim&&<button disabled={locked||!!plan.rates||!untrimmed} onClick={()=>untrimmed&&changePlan(untrimmed)}>Сбросить изменение границы</button>}
    <h3>Скорость фрагментов</h3>
    <p className="secondary">Скорость сохраняется вместе с монтажом. Для изменения границ, удаления или перестановки сначала сбрось скорость. Предпросмотр приблизительный.</p>
    {plan.windows.map((_,index)=><label key={index}>Скорость фрагмента {index+1}
      <select aria-label={"Скорость фрагмента "+(index+1)} value={plan.rates?.[index]??100}
        disabled={locked||!normalSpeed||!q.data?.plans.some(p=>p.rates&&sameCrop(p,plan)&&equal(p.removed,removed)&&equal(p.order,plan.order)&&equal(p.trim??[],plan.trim??[]))}
        onChange={e=>changeRate(index,Number(e.target.value))}>
        {[50,100,200].map(n=>{
          const rates=plan.rates?[...plan.rates]:plan.windows.map(()=>100);rates[index]=n;
          const available=q.data?.plans.some(p=>sameCrop(p,plan)&&equal(p.removed,removed)&&equal(p.order,plan.order)&&
            equal(p.trim??[],plan.trim??[])&&equal(p.rates??p.windows.map(()=>100),rates));
          return <option key={n} value={n} disabled={!available}>{n/100}×</option>;
        })}
      </select>
    </label>)}
    {plan.rates&&<button disabled={locked||!normalSpeed} onClick={()=>normalSpeed&&changePlan(normalSpeed)}>Сбросить скорость</button>}
    <label>Позиция монтажа
      <input type="range" min={0} max={plan.duration} step={0.01} value={position} disabled={!usable}
        onChange={e=>{video.current?.pause();stopMusic();move(Number(e.target.value));}} />
    </label>
    <p className="secondary">Монтаж: {seconds(position)} / {seconds(plan.duration)}</p>
    <button disabled={!usable} onClick={()=>{
      const v=video.current;if(!v)return;
      if(!v.paused){v.pause();stopMusic();return;}
      const start=position>=plan.duration-0.01?0:position;
      if(start===0)move(0);
      startMusic(plan,start,"montage");
      void v.play().catch(()=>{stopMusic();setError(true);setPlaying(false);});
    }}>{playing?"Пауза":"Смотреть нарезку"}</button>
    {error&&<p role="alert">Видео недоступно; план нарезки можно посмотреть без воспроизведения.</p>}
    <p className="secondary">Предпросмотр пропускает вырезанные интервалы на исходном видео. Стыки приблизительные, без финального рендера.</p>
    {q.data.longform_review&&<details>
      <summary>Длинное видео: пример поиска дублей</summary>
      <p className="secondary">Отдельный синтетический текст без видео. Длительность исходника: {seconds(q.data.longform_review.source_duration_ms/1000)}. Ничего не удаляется автоматически.</p>
      <p>Возможные повторы: {q.data.longform_review.candidates.length}</p>
      {q.data.longform_review.candidates.map(candidate=><div key={candidate.earlier+":"+candidate.later}>
        <strong>{candidate.kind==="exact_text"?"Повтор текста":"Возможный повторный дубль"}</strong>
        {[candidate.earlier,candidate.later].map(n=>{
          const s=q.data?.longform_review?.sentences.find(item=>item.number===n);
          return s?<p key={n}>#{n} · {seconds(s.start_ms/1000)} – {seconds(s.end_ms/1000)} · {s.text}</p>:null;
        })}
        <p className="secondary">Совпавших слов: {candidate.matched_tokens}. Проверь смысл обеих фраз перед удалением.</p>
      </div>)}
      <p className="secondary">Таймкоды транскрипта, не границы вырезания.</p>
      <WholeSourceControls/>
    </details>}
    <details><summary>История нарезки ({q.data.history.length})</summary>
      {q.data.history.map(h=><p key={h.revision}>#{h.revision} · {(h.navigation==="undo"?"Отмена · ":h.navigation==="redo"?"Повтор · ":"")+(h.crop?"Кадрирование · ":"")+(h.music?"Фон "+h.music[0]+" · "+h.music[1]+"% · ":"")+(h.dip_ms?"Переход "+h.dip_ms+" мс · ":"")+(h.graphic?"Графический слой · ":"")+(h.rates?"Скорость: "+h.rates.map(n=>n/100+"×").join(" / "):h.trim?"Граница фрагмента "+(h.trim[0]+1)+" · "+(h.trim[1]===1?"начало":"конец")+" "+seconds(h.trim[2]/1000):h.order?.length?"Порядок: "+h.order.join(" → ")+(h.removed.length?" · убраны "+h.removed.join(", "):""):h.removed.length?"Убраны предложения "+h.removed.join(", "):"Исходное восстановлено")}</p>)}
    </details>
  </section>;
}
