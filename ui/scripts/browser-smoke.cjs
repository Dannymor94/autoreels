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

async function layout(page, label) {
  const size = await page.evaluate(() => ({width: document.documentElement.clientWidth, scroll: document.documentElement.scrollWidth}));
  assert.ok(size.scroll <= size.width + 1, label + ": page overflow " + JSON.stringify(size));
}
async function mock(page, mode = "normal") {
  await page.route("**/api/**", async route => {
    const path = new URL(route.request().url()).pathname;
    if (route.request().method() !== "GET") throw new Error("Unexpected write: " + path);
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
        await page.getByRole("button", {name: "variant_b", exact: true}).click();
        await page.waitForURL(/v=_gate%2Fvariant_b/);
        assert.match(await page.locator(".review-video").getAttribute("src"), /variant=_gate%2Fvariant_b/);
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
