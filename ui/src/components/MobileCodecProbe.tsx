import {useEffect,useRef,useState} from "react";
import {probeLocalCodec,type CodecProbe} from "../localCodecProbe";

export function MobileCodecProbe(){
  const [busy,setBusy]=useState(false);
  const [result,setResult]=useState<CodecProbe|null>(null);
  const alive=useRef(true);
  const guard=useRef(false);
  useEffect(()=>{alive.current=true;return()=>{alive.current=false;};},[]);
  async function run(){
    if(guard.current)return;
    guard.current=true;setBusy(true);setResult(null);
    const outcome=await probeLocalCodec();
    guard.current=false;
    if(alive.current){setResult(outcome);setBusy(false);}
  }
  return <section aria-label="Локальная проверка кодека">
    <h3>Проверка кодека на этом устройстве</h3>
    <p className="secondary">Шесть цветных кадров создаются, кодируются и декодируются прямо в браузере. Без загрузки файлов или отправки на сервер.</p>
    <button disabled={busy} onClick={()=>void run()}>{busy?"Выполняется проверка…":"Проверить локальный H.264"}</button>
    {result&&<div role="status" data-testid="local-codec-result" data-result={result.status}>
      <p>{result.detail}</p>
      <p>Проверено кадров: {result.frames} · {result.elapsedMs} мс</p>
    </div>}
    <p className="secondary">Это тест кодека, не экспорт MP4. Звук, субтитры, монтаж, потребление памяти и запуск на физическом смартфоне требуют отдельных проверок. Рендер остаётся отключён.</p>
  </section>;
}
