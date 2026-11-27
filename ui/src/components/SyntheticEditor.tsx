import { useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api, type DemoCommand, type DemoEdit } from "../api/client";

const key = ["synthetic-editor"];
const labels = {edit:"Правка",undo:"Отмена",redo:"Повтор"} as const;

export function SyntheticEditor() {
  const q = useQuery({queryKey:key,queryFn:api.syntheticEditor,retry:false,
    refetchOnWindowFocus:false, refetchOnReconnect:false});
  const qc = useQueryClient();
  const [selected,setSelected] = useState<number|null>(null);
  const [replacement,setReplacement] = useState("");
  const [busy,setBusy] = useState(false);
  const [error,setError] = useState(false);
  const pending = useRef<DemoCommand|null>(null);
  const guard = useRef(false);
  const state = q.data;
  if (!state?.enabled) return null;
  const word = state.words.find(w=>w.index===selected);
  const locked = busy || error || q.isFetching || q.isError || state.revision>=100;

  async function send(command: DemoCommand) {
    if (guard.current) return;
    guard.current=true; pending.current=command; setBusy(true);setError(false);
    try {
      const next = await api.editSynthetic(command);
      qc.setQueryData(key,next);
      pending.current=null;setSelected(null);setReplacement("");
    } catch {setError(true);}
    finally {guard.current=false;setBusy(false);}
  }
  function apply(action:DemoCommand["action"], index:number, expected:string, next:string) {
    if (!state || locked || pending.current || guard.current) return;
    void send({action,op_id:crypto.randomUUID(),base_revision:state.revision,
      base_plan_sha256:state.plan_sha256,clip_uid:state.clip_uid,word_index:index,
      expected_text:expected,replacement:next});
  }
  function historyAction(action:"undo"|"redo", target:DemoEdit|null) {
    if (!target) return;
    apply(action,target.word_index,action==="undo"?target.after:target.before,
          action==="undo"?target.before:target.after);
  }
  return <section className="pipeline-settings synthetic-editor" aria-label="Демонстрационный текстовый редактор">
    <h2>Демонстрационный текстовый редактор</h2>
    <p className="secondary">Тестовый текст. Изменения сохраняются только в демонстрации; звук и рабочие проекты не меняются.</p>
    <p>Ревизия демо: {state.revision}</p>
    <div className="synthetic-word-list">
      {state.words.map(w=><button type="button" key={w.index} aria-pressed={selected===w.index}
        disabled={locked} onClick={()=>{setSelected(w.index);setReplacement(w.word);}}>{w.word}</button>)}
    </div>
    {word && <form className="synthetic-word-form" onSubmit={e=>{e.preventDefault();apply("edit",word.index,word.word,replacement);}}>
      <label>Исправить написание<input value={replacement} maxLength={128}
        disabled={locked} onChange={e=>setReplacement(e.target.value)}/></label>
      <button disabled={locked||replacement===word.word||!replacement||/\s/.test(replacement)}>Сохранить слово</button>
    </form>}
    <div className="synthetic-word-list">
      <button disabled={locked||!state.undo} onClick={()=>historyAction("undo",state.undo)}>Отменить правку</button>
      <button disabled={locked||!state.redo} onClick={()=>historyAction("redo",state.redo)}>Повторить правку</button>
    </div>
    {state.revision>=100 && <p>Лимит демонстрационных ревизий достигнут.</p>}
    {error && <div role="alert">
      <p>Ответ не подтверждён или версия изменилась.</p>
      <button disabled={busy} onClick={()=>{if(pending.current)void send(pending.current);}}>Повторить сохранение</button>
      <button disabled={busy} onClick={()=>{pending.current=null;setSelected(null);setReplacement("");setError(false);void q.refetch();}}>Обновить версию демо</button>
    </div>}
    {q.isError && <p role="alert">Демонстрация недоступна. <button onClick={()=>void q.refetch()}>Обновить версию демо</button></p>}
    <details><summary>История правок ({state.history.length})</summary>
      {state.history.map(h=><p key={h.revision}>#{h.revision} · {labels[h.action]}: {h.before} → {h.after}</p>)}
    </details>
  </section>;
}
