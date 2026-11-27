// Real FastAPI + synthetic HTTPS, no network proxy, owner files, or real credentials.
const assert = require("node:assert/strict");
const { chromium } = require(process.env.ARL_PLAYWRIGHT || "playwright");
const base = "https://127.0.0.1:8766";
async function main() {
  const browser = await chromium.launch({channel:"chrome",headless:true});
  try {
    const anonymous = await browser.newContext({ignoreHTTPSErrors:true});
    const denied = await anonymous.request.get(base+"/api/media/DEMO/r01", {headers:{Range:"bytes=0-1"}});
    assert.equal(denied.status(),401);
    await anonymous.close();
    const context = await browser.newContext({ignoreHTTPSErrors:true,
      httpCredentials:{username:"owner",password:"synthetic-only-not-a-real-password"}});
    try {
      const page = await context.newPage();
      await page.goto(base+"/#/");
      await page.getByText("Защищённое подключение",{exact:true}).waitFor();
      await page.locator(".source-row").first().waitFor();
      const results = await page.evaluate(async () => {
        const get = async path => {
          const r = await fetch(path);
          if (!r.ok) throw Error("GET "+r.status);
          return r.json();
        };
        const put = async (path, body) => {
          const r = await fetch(path,{method:"PUT",headers:{"Content-Type":"application/json"},body:JSON.stringify(body)});
          if (!r.ok) throw Error("PUT "+r.status);
          return r.json();
        };
        const review = "/api/reviews/DEMO/r01";
        const s = await get(review);
        const saved = await put(review,{request_id:crypto.randomUUID(),artifact_sha256:s.artifact_sha256,
          base_revision:null,verdict:"keep",comment:"synthetic",position_s:0});
        const pair="/api/comparisons/DEMO/r01?left=&right=_gate/b";
        const p=await get(pair);
        const choice=await put(pair,{request_id:crypto.randomUUID(),left_sha256:p.left_sha256,
          right_sha256:p.right_sha256,base_revision:null,winner:"_gate/b",comment:"synthetic"});
        const media=await fetch("/api/media/DEMO/r01?artifact="+s.artifact_sha256,{headers:{Range:"bytes=2-5"}});
        return {verdict:saved.current.verdict,winner:choice.current.winner,status:media.status,bytes:await media.text(),cache:media.headers.get("cache-control")};
      });
      assert.deepEqual(results,{verdict:"keep",winner:"_gate/b",status:206,bytes:"2345",cache:"no-store, private"});
      console.log("PASS authenticated HTTPS browser, review/comparison writes and private media range");
    } finally { await context.close(); }
  } finally { await browser.close(); }
}
main().catch(e=>{console.error(e);process.exitCode=1;});
