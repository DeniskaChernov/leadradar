const CONTROL = "/__leadradar_gateway__/origin";
const NO_STORE = { "Cache-Control": "no-store", "CDN-Cache-Control": "no-store" };

function json(value, status = 200) {
  return Response.json(value, { status, headers: NO_STORE });
}

export function validOrigin(value) {
  if (typeof value !== "string" || !/^https:\/\/[a-z0-9-]+\.trycloudflare\.com$/.test(value)) return false;
  const url = new URL(value);
  return !url.username && !url.password && !url.port;
}

async function authorized(request, secret) {
  if (typeof secret !== "string" || secret.length < 32) return false;
  const actual = request.headers.get("Authorization") || "";
  const digest = async value => new Uint8Array(await crypto.subtle.digest("SHA-256", new TextEncoder().encode(value)));
  const [a, b] = await Promise.all([digest(actual), digest("Bearer " + secret)]);
  let different = 0;
  for (let i = 0; i < a.length; i++) different |= a[i] ^ b[i];
  return different === 0;
}

function unavailable(request) {
  if (new URL(request.url).pathname.startsWith("/api/") || request.headers.get("Accept")?.includes("json") || ["/health", "/ready"].includes(new URL(request.url).pathname)) {
    return json({ ok: false, detail: "Сервер Lead Radar недоступен. Проверьте, что компьютер включён и подключён к интернету." }, 503);
  }
  return new Response("<!doctype html><html lang=ru><meta charset=utf-8><meta name=viewport content='width=device-width, initial-scale=1'><title>Lead Radar</title><body><h1>Lead Radar временно недоступен</h1><p>Проверьте, что компьютер с программой включён и подключён к интернету. Затем обновите страницу.</p></body></html>", {
    status: 503, headers: { ...NO_STORE, "Content-Type": "text/html; charset=utf-8", "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'", "Retry-After": "60" },
  });
}

export async function handle(request, env, fetchOrigin = fetch) {
  const url = new URL(request.url);
  if (url.pathname === CONTROL) {
    if (!await authorized(request, env.ORIGIN_UPDATE_KEY)) return json({ detail: "Unauthorized" }, 401);
    if (request.method !== "PUT") return json({ detail: "Method not allowed" }, 405);
    if (Number(request.headers.get("Content-Length") || 0) > 2048) return json({ detail: "Payload too large" }, 413);
    const reader = request.body?.getReader();
    const chunks = [];
    let size = 0;
    if (reader) {
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        size += value.byteLength;
        if (size > 2048) { await reader.cancel(); return json({ detail: "Payload too large" }, 413); }
        chunks.push(value);
      }
    }
    const bytes = new Uint8Array(size);
    let offset = 0;
    for (const chunk of chunks) { bytes.set(chunk, offset); offset += chunk.byteLength; }
    const text = new TextDecoder().decode(bytes);
    let body;
    try { body = JSON.parse(text); } catch { return json({ detail: "Invalid JSON" }, 400); }
    if (!validOrigin(body?.origin)) return json({ detail: "Invalid tunnel origin" }, 400);
    try {
      const result = await env.ROUTING.prepare("INSERT INTO gateway_origin (id, origin) VALUES (1, ?) ON CONFLICT(id) DO UPDATE SET origin=excluded.origin WHERE gateway_origin.origin != excluded.origin").bind(body.origin).run();
      return json({ ok: true, changed: Boolean(result.meta?.changes) });
    } catch { return json({ detail: "Routing storage unavailable" }, 503); }
  }
  if (url.pathname.startsWith("/__leadradar_gateway__/")) return json({ detail: "Not found" }, 404);
  if (!["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"].includes(request.method)) return json({ detail: "Method not allowed" }, 405);
  try {
    const row = await env.ROUTING.prepare("SELECT origin FROM gateway_origin WHERE id=1").first();
    if (!validOrigin(row?.origin)) return unavailable(request);
    const target = new URL(row.origin);
    target.pathname = url.pathname;
    target.search = url.search;
    const headers = new Headers(request.headers);
    headers.delete("Host");
    headers.delete("X-Forwarded-Host");
    headers.delete("X-Forwarded-Proto");
    const upstream = await fetchOrigin(new Request(target, {
      method: request.method, headers,
      body: ["GET", "HEAD"].includes(request.method) ? undefined : request.body,
      redirect: "manual", duplex: "half",
    }), { cf: { cacheTtl: 0, cacheEverything: false } });
    if ([502, 522, 523, 524, 525, 530].includes(upstream.status)) return unavailable(request);
    if (upstream.status === 101) return upstream;
    const responseHeaders = new Headers(upstream.headers);
    for (const [key, value] of Object.entries(NO_STORE)) responseHeaders.set(key, value);
    responseHeaders.set("Cloudflare-CDN-Cache-Control", "no-store");
    return new Response(upstream.body, { status: upstream.status, statusText: upstream.statusText, headers: responseHeaders });
  } catch {
    // A mutating request is never replayed after an uncertain delivery.
    return unavailable(request);
  }
}

export default { fetch(request, env) { return handle(request, env); } };
