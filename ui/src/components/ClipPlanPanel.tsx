import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";

function sec(n: number) { return n.toFixed(2) + " с"; }

export function ClipPlanPanel({stem, clip}: {stem:string; clip:string}) {
  const [opened,setOpened] = useState(false);
  const plan = useQuery({queryKey:["base-clip-plan",stem,clip], queryFn:()=>api.clipPlan(stem,clip),
    enabled:opened, retry:false, staleTime:0});
  const data = plan.data;
  return <section className="clip-plan-panel" aria-label="Текст монтажного плана">
    <button type="button" aria-expanded={opened} onClick={()=>setOpened(!opened)}>
      {opened?"Скрыть текст плана":"Открыть текст плана"}
    </button>
    {opened && <>
      <p>Базовый манифест, не точная расшифровка выбранного видео. Таймкоды плана приблизительные; редактирование и переход по слову пока отключены.</p>
      {plan.isFetching && <p role="status">Загрузка плана…</p>}
      {plan.isError && <p role="alert">План недоступен или неоднозначен. <button onClick={()=>void plan.refetch()}>Повторить</button></p>}
      {!plan.isError && !plan.isFetching && data && <>
        <p>Ревизия: <code>{data.revision_sha256.slice(0,12)}</code> · {sec(data.planned_duration_s)} · скорость ×{data.speed}</p>
        <button type="button" onClick={()=>void plan.refetch()}>Обновить план</button>
        {!data.words.length && <p>В этом плане нет субтитров.</p>}
        {data.windows.map(w=><div className="plan-window" key={w.index}>
          <strong>{w.kind==="hook"?"Хук":"Фрагмент "+(w.index+1)}</strong>
          <small>Исходник {sec(w.source_start)} – {sec(w.source_end)} · план {sec(w.plan_start)} – {sec(w.plan_end)}</small>
          <p>{data.words.filter(word=>word.window_index===w.index).map(word=>
            <span className="plan-word" key={word.occurrence_id} title={"Исходник: "+sec(word.source_start)+"; план: "+sec(word.plan_start)}>{word.word} </span>)}</p>
        </div>)}
      </>}
    </>}
  </section>;
}
