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
  await page.route("**/api/**", async route => {
    const url = new URL(route.request().url());
    const path = url.pathname;
    const method = route.request().method();
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
        assert.equal(await page.getByRole("button", {name: /Задания/}).isDisabled(), true);
        assert.equal(await page.getByRole("button", {name: /Экспорт/}).isDisabled(), true);
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
