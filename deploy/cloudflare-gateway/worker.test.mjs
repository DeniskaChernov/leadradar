import { test } from "node:test";
import assert from "node:assert/strict";
import { DatabaseSync } from "node:sqlite";
import { readFileSync } from "node:fs";
import worker, { handle, validOrigin } from "./worker.mjs";

const KEY = "unit-test-only-secret-".repeat(3);
const ORIGIN = "https://unit-tunnel.trycloudflare.com";
const PUBLIC = "https://leadradar-gateway.example.workers.dev";
const CONTROL = PUBLIC + "/__leadradar_gateway__/origin";

function environment() {
  const db = new DatabaseSync(":memory:");
  db.exec(readFileSync(new URL("./schema.sql", import.meta.url), "utf8"));
  return {
    ORIGIN_UPDATE_KEY: KEY, db,
    ROUTING: { prepare(sql) { return {
      first: async () => db.prepare(sql).get() || null,
      bind: (...args) => ({ run: async () => ({ meta: { changes: Number(db.prepare(sql).run(...args).changes) } }) }),
    }; } },
  };
}

function update(origin = ORIGIN, extra = {}) {
  return new Request(CONTROL, { method: "PUT", headers: { Authorization: "Bearer " + KEY }, body: JSON.stringify({ origin }), ...extra });
}

for (const value of ["http://unit.trycloudflare.com", "https://127.0.0.1", "https://unit.trycloudflare.com.evil.test", "https://user:pass@unit.trycloudflare.com", ORIGIN + "/", ORIGIN + ":443", ORIGIN + "?q=1", ORIGIN + "#x", "https://example.com", "https://UNIT.trycloudflare.com", ""]) {
  test("reject invalid origin " + value, () => assert.equal(validOrigin(value), false));
}

test("only the update key can change routing; repeated updates are idempotent in SQLite", async () => {
  const env = environment();
  const denied = await handle(update(ORIGIN, { headers: { Authorization: "Bearer wrong" } }), env);
  assert.equal(denied.status, 401);
  assert.equal(env.db.prepare("SELECT count(*) n FROM gateway_origin").get().n, 0);
  assert.deepEqual(await (await handle(update(), env)).json(), { ok: true, changed: true });
  assert.deepEqual(await (await handle(update(), env)).json(), { ok: true, changed: false });
  assert.equal((await handle(update("https://evil.test"), env)).status, 400);
  assert.equal(env.db.prepare("SELECT origin FROM gateway_origin").get().origin, ORIGIN);
  const get = new Request(CONTROL, { headers: { Authorization: "Bearer " + KEY } });
  assert.equal((await handle(get, env)).status, 405);
  env.ORIGIN_UPDATE_KEY = "";
  assert.equal((await handle(update(), env)).status, 401);
});

test("malformed and streamed oversized updates cannot modify storage", async () => {
  const env = environment();
  assert.equal((await handle(update(ORIGIN, { body: "{" }), env)).status, 400);
  const large = new ReadableStream({ start(c) { c.enqueue(new Uint8Array(2049)); c.close(); } });
  assert.equal((await handle(update(ORIGIN, { body: large, duplex: "half" }), env)).status, 413);
  assert.equal(env.db.prepare("SELECT count(*) n FROM gateway_origin").get().n, 0);
});

test("proxy preserves authentication, body and query; responses and cookies are not cached", async () => {
  const env = environment(); await handle(update(), env);
  let calls = 0;
  const proxy = async (request, options) => {
    calls++;
    assert.equal(request.url, ORIGIN + "/api/leads/17?q=%D1%86%D0%B5%D0%BD%D0%B0");
    assert.equal(request.method, "POST"); assert.equal(await request.text(), '{"status":"TAKEN"}');
    assert.equal(request.headers.get("Cookie"), "session=unit-session");
    assert.equal(request.headers.get("Origin"), PUBLIC);
    assert.equal(request.headers.get("X-Forwarded-Host"), null);
    assert.equal(request.redirect, "manual"); assert.equal(options.cf.cacheTtl, 0);
    const headers = new Headers({ "Cache-Control": "public, max-age=600" });
    headers.append("Set-Cookie", "a=1; Secure; HttpOnly"); headers.append("Set-Cookie", "b=2; Secure");
    return new Response('{"ok":true}', { headers });
  };
  const response = await handle(new Request(PUBLIC + "/api/leads/17?q=%D1%86%D0%B5%D0%BD%D0%B0", { method: "POST", headers: { Cookie: "session=unit-session", Origin: PUBLIC, "X-Forwarded-Host": "evil.test" }, body: '{"status":"TAKEN"}' }), env, proxy);
  assert.equal(response.status, 200); assert.equal(calls, 1);
  assert.equal(response.headers.get("Cache-Control"), "no-store");
  assert.equal(response.headers.getSetCookie().length, 2);
});

test("double slash paths never control upstream host or credentials", async () => {
  const env = environment(); await handle(update(), env);
  const response = await handle(new Request(PUBLIC + "//user@evil.test:8080/path"), env, async request => {
    const url = new URL(request.url);
    assert.equal(url.origin, ORIGIN); assert.equal(url.username, "");
    return new Response("safe");
  });
  assert.equal(await response.text(), "safe");
});

test("an uncertain mutating request is sent once and never retried", async () => {
  const env = environment(); await handle(update(), env);
  let calls = 0;
  const response = await handle(new Request(PUBLIC + "/api/change", { method: "POST", body: "value" }), env, async () => { calls++; throw new Error("network failed"); });
  assert.equal(calls, 1); assert.equal(response.status, 503);
  assert.equal((await response.json()).ok, false);
});

test("missing route and expired tunnel return unavailable without exposing the internal hostname", async () => {
  const env = environment();
  assert.equal((await handle(new Request(PUBLIC + "/hot"), env)).status, 503);
  await handle(update(), env);
  const response = await handle(new Request(PUBLIC + "/hot"), env, async () => new Response(ORIGIN, { status: 530 }));
  assert.equal(response.status, 503); assert.ok(!(await response.text()).includes(ORIGIN));
});

test("Cloudflare's execution context is not treated as a fetch implementation", async t => {
  const env = environment(); await handle(update(), env);
  t.mock.method(globalThis, "fetch", async () => new Response("working"));
  const response = await worker.fetch(new Request(PUBLIC + "/hot"), env, { waitUntil() {} });
  assert.equal(await response.text(), "working");
});
