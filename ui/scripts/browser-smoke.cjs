// One targeted layout/navigation smoke, not media playback or real device acceptance.
// The browser tool is installed in runner.temp; no app dependency or lockfile change.
const assert = require("node:assert/strict");
const { chromium } = require(process.env.ARL_PLAYWRIGHT || "playwright");
const base = "http://127.0.0.1:4173";
const stem = "DEMO";
const name = "Синтетический проект " + "длинноеНазвание".repeat(7);
const source = {stem, display_name: name, clip_count: 2, variant_names: ["_gate/variant_b"], poster_clip: "r01", poster_variant: ""};
const pending = {stem: "PENDING", display_name: "Новый исходник", clip_count: 0, variant_names: [], poster_clip: null, poster_variant: "", status: "unprocessed", detail: "input_present", can_review: false};
const projects = [{...source, status: "ready", detail: "render_present", can_review: true}, pending];
const clip = (id, variant = "") => ({clip: id, variant, size_bytes: 100, has_render_json: false, fingerprint: null, duration_s: 30, title: "Заголовок", caption: "Синтетический текст"});
const clips = [clip("r01"), clip("r01", "_gate/variant_b"), clip("r02")];
// 32x48 black synthetic H.264, two frames; generated with ffmpeg lavfi locally.
// No owner media and no new runtime asset.
const fixture = Buffer.from("AAAAIGZ0eXBpc29tAAACAGlzb21pc28yYXZjMW1wNDEAAAMxbW9vdgAAAGxtdmhkAAAAAAAAAAAAAAAAAAAD6AAAA+gAAQAAAQAAAAAAAAAAAAAAAAEAAAAAAAAAAAAAAAAAAAABAAAAAAAAAAAAAAAAAABAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAgAAAlx0cmFrAAAAXHRraGQAAAADAAAAAAAAAAAAAAABAAAAAAAAA+gAAAAAAAAAAAAAAAAAAAAAAAEAAAAAAAAAAAAAAAAAAAABAAAAAAAAAAAAAAAAAABAAAAAACAAAAAwAAAAAAAkZWR0cwAAABxlbHN0AAAAAAAAAAEAAAPoAAAAAAABAAAAAAHUbWRpYQAAACBtZGhkAAAAAAAAAAAAAAAAAABAAAAAQABVxAAAAAAALWhkbHIAAAAAAAAAAHZpZGUAAAAAAAAAAAAAAABWaWRlb0hhbmRsZXIAAAABf21pbmYAAAAUdm1oZAAAAAEAAAAAAAAAAAAAACRkaW5mAAAAHGRyZWYAAAAAAAAAAQAAAAx1cmwgAAAAAQAAAT9zdGJsAAAAv3N0c2QAAAAAAAAAAQAAAK9hdmMxAAAAAAAAAAEAAAAAAAAAAAAAAAAAAAAAACAAMABIAAAASAAAAAAAAAABFUxhdmM2MS4xOS4xMDEgbGlieDI2NAAAAAAAAAAAAAAAGP//AAAANWF2Y0MBZAAK/+EAGGdkAAqs2UnsBEAAAAMAQAAAAwEDxIllgAEABmjr48siwP34+AAAAAAQcGFzcAAAAAEAAAABAAAAFGJ0cnQAAAAAAAABSAAAAAAAAAAYc3R0cwAAAAAAAAABAAAAAgAAIAAAAAAUc3RzcwAAAAAAAAABAAAAAQAAABxzdHNjAAAAAAAAAAEAAAABAAAAAgAAAAEAAAAcc3RzegAAAAAAAAAAAAAAAgAAABwAAAANAAAAFHN0Y28AAAAAAAAAAQAAA2EAAABhdWR0YQAAAFltZXRhAAAAAAAAACFoZGxyAAAAAAAAAABtZGlyYXBwbAAAAAAAAAAAAAAAACxpbHN0AAAAJKl0b28AAAAcZGF0YQAAAAEAAAAATGF2ZjYxLjcuMTAzAAAACGZyZWUAAAAxbWRhdAAAABhliIQAFP/+98dPwKbq3CLLnEkAf2UdKeEAAAAJQZohbEEv/rVY", "base64");

async function layout(page, label) {
  const size = await page.evaluate(() => ({width: document.documentElement.clientWidth, scroll: document.documentElement.scrollWidth}));
  assert.ok(size.scroll <= size.width + 1, label + ": page overflow " + JSON.stringify(size));
}
async function mock(page, mode = "normal") {
  const reviews = new Map();
  const comparisons = new Map();
  const jobs = new Map();
  let cutRevision=0,cutRemoved=[],cutHistory=[];
  let editor = {enabled:mode==="normal",revision:0,plan_sha256:"a".repeat(64),clip_uid:"b".repeat(64),
    words:[{index:0,word:"Превет",start:0.1,end:0.8},{index:1,word:"друзья!",start:1,end:2}],
    history:[],undo:null,redo:null};
  await page.route("**/api/**", async route => {
    const url = new URL(route.request().url());
    const path = url.pathname;
    const method = route.request().method();
    if(path==="/api/synthetic-cut"){
      const baseline={removed:[],duration:3,plan_sha256:"a".repeat(64),windows:[{source_start:0,source_end:3,output_start:0,output_end:3}]};
      const candidate={removed:[2],duration:1.8,plan_sha256:"b".repeat(64),windows:[{source_start:0,source_end:0.9,output_start:0,output_end:0.9},{source_start:2.1,source_end:3,output_start:0.9,output_end:1.8}]};
      if(method==="PUT"){
        const input=route.request().postDataJSON();
        assert.equal(input.base_revision,cutRevision);
        assert.equal(input.base_plan_sha256,cutRemoved.length?candidate.plan_sha256:baseline.plan_sha256);
        assert.equal(input.clip_uid,"c".repeat(64));
        assert.equal(input.candidate_plan_sha256,input.removed.length?candidate.plan_sha256:baseline.plan_sha256);
        cutRemoved=input.removed;cutRevision++;
        cutHistory.unshift({revision:cutRevision,removed:cutRemoved});
      }
      return route.fulfill({json:{enabled:mode==="normal",source_duration:3,revision:cutRevision,clip_uid:"c".repeat(64),
        current_removed:cutRemoved,history:cutHistory,plan_sha256:cutRemoved.length?candidate.plan_sha256:baseline.plan_sha256,
        sentences:[{number:1,text:"Начало.",start:0.2,end:0.8},{number:2,text:"Лишнее.",start:1.2,end:1.8},{number:3,text:"Продолжение.",start:2.2,end:2.8}],
        plans:[baseline,candidate]}});
    }
    if (path === "/api/synthetic-editor") {
      if(method==="PUT") {
        const input=route.request().postDataJSON();
        assert.equal(input.base_revision,editor.revision);
        assert.equal(input.base_plan_sha256,editor.plan_sha256);
        assert.equal(input.expected_text,editor.words[input.word_index].word);
        const event={revision:editor.revision+1,action:input.action,word_index:input.word_index,before:input.expected_text,after:input.replacement};
        editor={...editor,revision:event.revision,plan_sha256:String(event.revision).repeat(64),
          words:editor.words.map(w=>w.index===input.word_index?{...w,word:input.replacement}:w),
          history:[event,...editor.history],
          undo:input.action==="undo"?null:input.action==="redo"?editor.redo:event,
          redo:input.action==="undo"?editor.undo:null};
      }
      return route.fulfill({json:editor});
    }
    if (path === "/api/jobs") return route.fulfill({json:{enabled:true,jobs:[...jobs.values()]}});
    if (path.startsWith("/api/jobs/") && method === "PUT") {
      const job_id=path.split("/").pop(), input=route.request().postDataJSON();
      if(input.action==="create") {
        assert.equal(input.target_kind,"mobile");
        if(!jobs.has(job_id)) jobs.set(job_id,{job_id,target_kind:input.target_kind,outcome:input.outcome,status:"queued",stage:"queued",progress:0,revision:0});
      } else {
        const job=jobs.get(job_id); Object.assign(job,{status:"cancelled",stage:"cancelled",revision:job.revision+1});
      }
      return route.fulfill({json:jobs.get(job_id)});
    }
    if (path.startsWith("/api/comparisons/")) {
      const pair = [url.searchParams.get("left"), url.searchParams.get("right")].sort();
      const left_variant = pair[0], right_variant = pair[1];
      const key = path + JSON.stringify(pair);
      const state = comparisons.get(key) || {left_variant, right_variant, left_sha256: "a".repeat(64), right_sha256: "b".repeat(64), current: null, history: []};
      if (method === "PUT") {
        const input = route.request().postDataJSON();
        const {base_revision, ...event} = input;
        state.current = {...event,left_variant,right_variant,created_at:"2026-11-26T20:00:00Z"};
        state.history.unshift(state.current);
        comparisons.set(key,state);
      }
      return route.fulfill({json:state});
    }
    if (path.startsWith("/api/reviews/")) {
      const variant = url.searchParams.get("variant") || "";
      const artifact_sha256 = (variant ? "b" : "a").repeat(64);
      const key = path + variant;
      const state = reviews.get(key) || {artifact_sha256, current: null, history: [], legacy: []};
      if (method === "PUT") {
        const input = route.request().postDataJSON();
        assert.equal(input.artifact_sha256, artifact_sha256);
        assert.equal(input.base_revision, state.current?.request_id ?? null);
        const {base_revision, ...event} = input;
        state.current = {...event, created_at: "2026-11-26T20:00:00Z"};
        state.history.unshift(state.current);
        reviews.set(key, state);
      } else assert.equal(method, "GET");
      return route.fulfill({json: state});
    }
    if (method !== "GET") throw new Error("Unexpected write: " + path);
    if (path.startsWith("/api/media/")) {
      const range = route.request().headers().range;
      const match = range && /^bytes=(\d+)-(\d*)$/.exec(range);
      if (match) {
        const start = Number(match[1]);
        const end = match[2] ? Math.min(Number(match[2]), fixture.length - 1) : fixture.length - 1;
        if (start > end) return route.fulfill({status:416,headers:{"Content-Range":"bytes */"+fixture.length}});
        return route.fulfill({status:206,contentType:"video/mp4",body:fixture.subarray(start,end+1),headers:{"Accept-Ranges":"bytes","Content-Range":"bytes "+start+"-"+end+"/"+fixture.length}});
      }
      return route.fulfill({status:200,contentType:"video/mp4",body:fixture,headers:{"Accept-Ranges":"bytes"}});
    }
    if (path === "/api/clip-plan/DEMO/r01") return route.fulfill({json:{
      revision_sha256:"d".repeat(64),recorded_source_id:"full:"+"a".repeat(64),clip_ref:"e".repeat(64),speed:1,planned_duration_s:3,
      windows:[{index:0,kind:"hook",source_start:5,source_end:6,plan_start:0,plan_end:1},{index:1,kind:"body",source_start:5,source_end:7,plan_start:1,plan_end:3}],
      words:[{occurrence_id:"a",window_index:0,word:"Привет",source_start:5.2,source_end:5.5,plan_start:0.2,plan_end:0.5},{occurrence_id:"b",window_index:1,word:"Привет",source_start:5.2,source_end:5.5,plan_start:1.2,plan_end:1.5}]
    }});
    if (path === "/api/module-settings") {
      const names=["hook_rescue","filler_cut","two_shot","loudnorm","denoise","music"];
      const modules=names.map(module=>{
        const configured=module==="loudnorm", choice=url.searchParams.get(module);
        return {module,kind:module==="hook_rescue"?"automation":"output",configured,proposed:choice===null?configured:choice==="on",available:false};
      });
      const changed=modules.filter(m=>m.proposed!==m.configured).map(m=>m.module);
      const invalidates=[...(changed.includes("hook_rescue")?["proposals"]:[]),...(changed.includes("filler_cut")?["plan"]:[]),...(changed.some(n=>n!=="hook_rescue")?["render"]:[])];
      return route.fulfill({json:{schema_version:1,status:"configured",modules,invalidates,base_sha256:"d".repeat(64),apply_enabled:false}});
    }
    if (path === "/api/pipeline-settings") {
      const clips=url.searchParams.get("clips"), profile=url.searchParams.get("profile");
      return route.fulfill({json:{schema_version:1,analysis_status:"configured",render_status:"configured",
        analysis:{base_clips:5,clips_every_min:2,min_sec:25,target_sec:55,max_sec:90,configured_mode:"autocut",label_min_sec:30,label_max_sec:60},
        render:{width:1080,height:1920,profile:"h264",profiles:["h264","hevc"],role:"both",loudnorm_enabled:true,denoise_enabled:false,music_enabled:false},
        draft_clips:clips?Number(clips):null,draft_profile:profile,preview_status:clips||profile?"valid":"not_requested",execution_enabled:false}});
    }
    if (path === "/api/render-targets") return route.fulfill({json: {
      schema_version:1, modes:[{kind:"desktop",integration:"cli_adapter_pending"},{kind:"remote",integration:"cli_adapter_pending"},{kind:"mobile",integration:"device_spike_pending"}],
      targets:[],execution_enabled:false
    }});
    if (path === "/api/health") return route.fulfill({json: {status: "ok", root: "/synthetic", schema_version: 1}});
    if (path === "/api/sources" || path === "/api/projects") {
      if (mode === "error") return route.fulfill({status: 503, body: "Synthetic failure"});
      return route.fulfill({json: mode === "empty" ? [] : path === "/api/projects" ? projects : [source]});
    }
    if (path === "/api/sources/DEMO/clips") return route.fulfill({json: clips});
    return route.fulfill({status: 404, body: ""}); // media decoding is deliberately not tested
  });
}
async function main() {
  const browser = await chromium.launch({channel: "chrome", headless: true});
  try {
    for (const width of [360, 390, 430, 1280]) {
      const ctx = await browser.newContext({viewport: {width, height: 850}, hasTouch: width < 701});
      try {
        const page = await ctx.newPage();
        const errors = [];
        page.on("pageerror", e => errors.push(e.message));
        await mock(page);
        await page.goto(base + "/#/");
        await page.locator(".source-row").first().waitFor();
        assert.equal(await page.getByRole("button", {name: /Задания/}).isDisabled(), false);
        assert.equal(await page.getByRole("button", {name: /Экспорт/}).isDisabled(), false);
        if (width === 390) {
          const demo=page.getByRole("region",{name:"Демонстрационный текстовый редактор"});
          await demo.locator("video").waitFor();
          await page.waitForFunction(()=>document.querySelector(".synthetic-preview-video")?.readyState>=1);
          await demo.getByRole("button",{name:"друзья!",exact:true}).click();
          await page.waitForFunction(()=>Math.abs(document.querySelector(".synthetic-preview-video")?.currentTime-1.02)<0.08);
          await demo.getByLabel("Текущий субтитр демо").getByText("друзья!",{exact:true}).waitFor();
          await demo.getByRole("button",{name:"Превет",exact:true}).click();
          await page.waitForFunction(()=>Math.abs(document.querySelector(".synthetic-preview-video")?.currentTime-0.12)<0.08);
          await demo.getByLabel("Исправить написание").fill("Привет");
          await demo.getByRole("button",{name:"Сохранить слово",exact:true}).click();
          await demo.getByRole("button",{name:"Привет",exact:true}).waitFor();
          await demo.getByLabel("Текущий субтитр демо").getByText("Привет",{exact:true}).waitFor();
          await demo.getByRole("button",{name:"Отменить правку",exact:true}).click();
          await demo.getByRole("button",{name:"Превет",exact:true}).waitFor();
          await demo.getByRole("button",{name:"Повторить правку",exact:true}).click();
          await demo.getByRole("button",{name:"Привет",exact:true}).waitFor();
          await page.reload();
          await demo.getByRole("button",{name:"Привет",exact:true}).waitFor();
          await demo.getByText("История правок (3)",{exact:true}).click();
          await demo.getByText("#3 · Повтор: Превет → Привет",{exact:true}).waitFor();
          await layout(page,"390 synthetic editor");
          console.log("PASS synthetic editor word seek, corrected cue, undo/redo, reload and history");
          const cut=page.getByRole("region",{name:"Демонстрационная нарезка предложений"});
          await page.waitForFunction(()=>document.querySelector(".cut-preview-video")?.readyState>=1);
          await cut.getByRole("button",{name:"Лишнее.",exact:true}).click();
          await cut.getByRole("button",{name:"Убрать выбранное",exact:true}).click();
          await cut.getByText("1.80 с · убрано 1.20 с",{exact:true}).waitFor();
          await cut.getByRole("button",{name:"Смотреть нарезку",exact:true}).click();
          await page.waitForFunction(()=>{const v=document.querySelector(".cut-preview-video");return v && v.currentTime>=2.1 && v.currentTime<2.8;});
          await page.reload();
          await cut.getByText("Ревизия нарезки: 1",{exact:true}).waitFor();
          await cut.getByText("1.80 с · убрано 1.20 с",{exact:true}).waitFor();
          await cut.getByRole("button",{name:"Восстановить исходное",exact:true}).click();
          await cut.getByText("3.00 с · убрано 0.00 с",{exact:true}).waitFor();
          await page.waitForFunction(()=>document.querySelector(".cut-preview-video")?.currentTime<0.08);
          await layout(page,"390 cut timeline");
          await cut.getByText("История нарезки (2)",{exact:true}).click();
          await cut.getByText("#2 · Исходное восстановлено",{exact:true}).waitFor();
          console.log("PASS synthetic sentence cut persistence, playback skip, restore, history and timeline");
          await page.getByRole("button",{name:"Задания",exact:true}).click();
          await page.getByLabel("Тестовый исполнитель").selectOption("mobile");
          await page.getByRole("button",{name:"Создать тестовое задание",exact:true}).click();
          await page.getByText("Телефон · В очереди",{exact:true}).waitFor();
          await page.getByRole("button",{name:"Отменить задание",exact:true}).click();
          await page.getByText("Телефон · Отменено",{exact:true}).waitFor();
          await page.reload();
          await page.getByText("Телефон · Отменено",{exact:true}).waitFor();
          await layout(page,"390 jobs");
          console.log("PASS synthetic job creation, cancellation and reload");
          await page.getByRole("button",{name:/Экспорт/}).click();
          await page.getByRole("radio",{name:/На телефоне/}).waitFor();
          assert.equal(await page.getByRole("radio",{name:/Мой компьютер/}).isChecked(),false);
          await page.getByRole("radio",{name:/На телефоне/}).check();
          await page.getByText("Подключённых исполнителей нет",{exact:true}).waitFor();
          assert.equal(await page.getByRole("button",{name:"Запустить рендер",exact:true}).isDisabled(),true);
          await page.getByLabel("Число роликов для пробной настройки").fill("7");
          await page.getByLabel("Профиль для пробной настройки").selectOption("hevc");
          const previewRequest=page.waitForRequest(req=>req.url().includes("/api/pipeline-settings?"));
          await page.getByRole("button",{name:"Проверить настройки",exact:true}).click();
          const previewUrl=new URL((await previewRequest).url());
          assert.equal(previewUrl.searchParams.get("clips"),"7");
          assert.equal(previewUrl.searchParams.get("profile"),"hevc");
          await page.getByText("Пробные параметры допустимы. Ничего не сохранено.",{exact:true}).waitFor();
          await page.getByLabel("Подбор хуков (резервный поиск)",{exact:true}).selectOption("on");
          await page.getByLabel("Фоновая музыка",{exact:true}).selectOption("on");
          await page.getByRole("button",{name:"Показать изменения",exact:true}).click();
          await page.getByText("Потребуется пересчитать: новые предложения, рендер",{exact:true}).waitFor();
          await page.getByRole("button",{name:"Сбросить пробные изменения",exact:true}).click();
          await page.getByLabel("Фоновая музыка",{exact:true}).waitFor();
          assert.equal(await page.getByLabel("Фоновая музыка",{exact:true}).inputValue(),"");
          console.log("PASS independent module draft preview and reset");
          await layout(page,"390 render modes/settings");
          console.log("PASS read-only configured settings and typed override preview");
          await page.getByRole("button",{name:"Проекты",exact:true}).click();
          await page.locator(".source-row").first().waitFor();
          console.log("PASS explicit render mode, no fake ready target or launch");
        }
        await page.getByRole("button", {name: "L", exact: true}).click();
        await layout(page, width + " projects");
        assert.equal(await page.getByText("Не обработан", {exact: true}).count(), 1);
        assert.equal(await page.getByRole("button", {name: "Новый исходник", exact: true}).last().isDisabled(), true);
        const project = page.locator(".source-name button").first();
        if (width < 701) await project.tap(); else await project.click();
        await page.getByRole("button", {name: "Смотреть по порядку"}).waitFor();
        await layout(page, width + " grid");
        await page.getByRole("button", {name: "Список", exact: true}).click();
        await page.getByRole("button", {name: "Открыть r01", exact: true}).focus();
        await layout(page, width + " table");
        await page.keyboard.press("Enter");
        await page.locator(".review-video").waitFor();
        await layout(page, width + " player");
        if (width === 390) {
          await page.getByRole("button",{name:"Открыть текст плана",exact:true}).click();
          await page.getByText("Хук",{exact:true}).waitFor();
          assert.equal(await page.locator(".plan-word").count(),2);
          await layout(page,"390 text plan");
          await page.getByRole("button",{name:"Скрыть текст плана",exact:true}).click();
          console.log("PASS revision-bound text plan, repeated hook occurrence and mobile layout");
          await page.getByLabel("Комментарий (необязательно)").fill("Синтетическая оценка");
          await page.getByRole("button", {name: "Оставить", exact: true}).click();
          await page.getByText("Сохранено: Оставить", {exact:true}).waitFor();
          await page.reload();
          await page.getByText("Сохранено: Оставить", {exact:true}).waitFor();
          assert.equal(await page.getByLabel("Комментарий (необязательно)").inputValue(), "Синтетическая оценка");
          console.log("PASS review save and reload (mock API, synthetic video)");
          await page.getByRole("button",{name:"Сравнить варианты",exact:true}).click();
          await page.getByRole("button",{name:"Выбрать Б",exact:true}).waitFor();
          await layout(page, "390 comparison");
          await page.getByLabel("Звук",{exact:true}).selectOption("b");
          assert.deepEqual(await page.locator(".comparison-video").evaluateAll(vs=>vs.map(v=>v.muted)), [true,false]);
          await page.getByLabel("Общая позиция").focus();
          await page.keyboard.press("Home");
          await page.keyboard.press("ArrowRight");
          await page.waitForFunction(()=> {
            const vs=[...document.querySelectorAll(".comparison-video")];
            return vs.length===2 && vs.every(v=>Math.abs(v.currentTime-0.05)<0.04);
          });
          console.log("PASS common seek and single audio selection");
          await page.getByLabel("Комментарий к выбору").fill("Сравнение");
          await page.getByRole("button",{name:"Выбрать Б",exact:true}).click();
          await page.getByText("Выбран: variant_b",{exact:true}).waitFor();
          await page.getByRole("button",{name:"Закрыть сравнение",exact:true}).click();
          await page.getByRole("button",{name:"Сравнить варианты",exact:true}).click();
          await page.getByText("Выбран: variant_b",{exact:true}).waitFor();
          await page.getByRole("button",{name:"Закрыть сравнение",exact:true}).click();
          console.log("PASS comparison choice and reopen (mock API)");
        }
        await page.getByRole("button", {name: "variant_b", exact: true}).click();
        await page.waitForURL(/v=_gate%2Fvariant_b/);
        await page.locator(".review-video").waitFor();
        assert.match(await page.locator(".review-video").getAttribute("src"), /variant=_gate%2Fvariant_b/);
        if (width === 390) await page.getByText("Не оценён", {exact:true}).waitFor();
        await page.reload();
        await page.locator(".review-video").waitFor();
        assert.match(await page.locator(".review-video").getAttribute("src"), /variant=_gate%2Fvariant_b/);
        await page.goBack();
        await page.getByRole("button", {name: "Смотреть по порядку"}).waitFor();
        await page.getByRole("button", {name: "Проекты", exact: true}).click();
        await page.locator(".source-row").first().waitFor();
        assert.deepEqual(errors, []);
        console.log("PASS responsive project/overview/review/navigation " + width + "px");
      } finally { await ctx.close(); }
    }
    for (const mode of ["empty", "error"]) {
      const page = await browser.newPage({viewport: {width: 390, height: 850}});
      try {
        await mock(page, mode);
        await page.goto(base + "/#/");
        await page.getByText(mode === "empty" ? "Источников нет" : /Ошибка:/).waitFor({timeout: 20000});
        await layout(page, mode);
        console.log("PASS " + mode);
      } finally { await page.close(); }
    }
  } finally { await browser.close(); }
}
main().catch(e => { console.error(e); process.exitCode = 1; });
