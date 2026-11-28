/** Explicit, bounded on-device codec experiment; not a renderer or target registration. */
export type CodecProbe = {status:"pass"|"unsupported"|"failed";detail:string;frames:number;elapsedMs:number};

export async function probeLocalCodec():Promise<CodecProbe>{
  const started=performance.now();
  const result=(status:CodecProbe["status"],detail:string,frames=0):CodecProbe=>
    ({status,detail,frames,elapsedMs:Math.round(performance.now()-started)});
  if(!globalThis.isSecureContext||typeof VideoEncoder==="undefined"||
     typeof VideoDecoder==="undefined"||typeof VideoFrame==="undefined"){
    return result("unsupported","WebCodecs недоступен в этом браузере или контексте.");
  }
  let encoder:VideoEncoder|undefined,decoder:VideoDecoder|undefined;
  let timer:ReturnType<typeof setTimeout>|undefined;
  let stopped=false;
  const count=6,width=96,height=160;
  const timestamps=Array.from({length:count},(_,i)=>Math.round(i*1_000_000/30));
  const deadline=new Promise<never>((_,reject)=>{
    timer=setTimeout(()=>{stopped=true;reject(new Error("timeout"));},8000);
  });
  const canvas=document.createElement("canvas");
  canvas.width=width;canvas.height=height;
  const ctx=canvas.getContext("2d",{willReadFrequently:true});
  if(!ctx){clearTimeout(timer);return result("unsupported","Canvas 2D недоступен.");}
  try{
    const experiment=async():Promise<CodecProbe>=>{
      const config:VideoEncoderConfig={codec:"avc1.42001f",width,height,framerate:30,bitrate:250_000};
      const support=await VideoEncoder.isConfigSupported(config);
      if(stopped)throw new Error("timeout");
      if(!support.supported)return result("unsupported","Кодирование H.264 не поддерживается.");
      const chunks:EncodedVideoChunk[]=[];
      let decoderConfig:VideoDecoderConfig|undefined,codecError=false;
      encoder=new VideoEncoder({output:(chunk,metadata)=>{
        if(chunks.length>=count||chunk.byteLength>1024*1024){codecError=true;return;}
        chunks.push(chunk);
        if(metadata?.decoderConfig)decoderConfig=metadata.decoderConfig;
      },error:()=>{codecError=true;}});
      encoder.configure(config);
      for(let i=0;i<count;i++){
        ctx.fillStyle=i<3?"#ff0000":"#0000ff";
        ctx.fillRect(0,0,width,height);
        const frame=new VideoFrame(canvas,{timestamp:timestamps[i],duration:33333});
        try{encoder.encode(frame,{keyFrame:i===0});}finally{frame.close();}
      }
      await encoder.flush();
      if(stopped||codecError||chunks.length!==count||!decoderConfig)throw new Error("encoder");
      const decodeSupport=await VideoDecoder.isConfigSupported(decoderConfig);
      if(stopped)throw new Error("timeout");
      if(!decodeSupport.supported)return result("unsupported","Декодирование этого профиля H.264 не поддерживается.");
      const seen=new Set<number>();
      decoder=new VideoDecoder({output:frame=>{
        try{
          const index=timestamps.indexOf(frame.timestamp);
          if(index<0||seen.has(index)||frame.displayWidth!==width||frame.displayHeight!==height){codecError=true;return;}
          ctx.drawImage(frame,0,0,width,height);
          const pixel=ctx.getImageData(width/2,height/2,1,1).data;
          if(index<3?pixel[0]-pixel[2]<100:pixel[2]-pixel[0]<100){codecError=true;return;}
          seen.add(index);
        }catch{codecError=true;}finally{frame.close();}
      },error:()=>{codecError=true;}});
      decoder.configure(decoderConfig);
      for(const chunk of chunks)decoder.decode(chunk);
      await decoder.flush();
      if(stopped||codecError||seen.size!==count)throw new Error("decoder");
      return result("pass","Локальное кодирование и декодирование H.264 подтверждено.",seen.size);
    };
    return await Promise.race([experiment(),deadline]);
  }catch{return result("failed","Кодек не завершил проверку кадров. Рендер не подтверждён.");}
  finally{
    stopped=true;clearTimeout(timer);
    if(encoder&&encoder.state!=="closed")encoder.close();
    if(decoder&&decoder.state!=="closed")decoder.close();
  }
}
