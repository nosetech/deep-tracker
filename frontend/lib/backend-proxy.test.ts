import assert from "node:assert/strict";
import { createServer, type IncomingMessage } from "node:http";
import type { AddressInfo } from "node:net";
import { after, before, test } from "node:test";

import { proxyToBackend } from "./backend-proxy.ts";

type Seen = {
  method?: string;
  url?: string;
  body: string;
  contentType?: string;
};

let seen: Seen;
const server = createServer(async (req: IncomingMessage, res) => {
  const chunks: Buffer[] = [];
  for await (const c of req) chunks.push(c as Buffer);
  seen = {
    method: req.method,
    url: req.url,
    body: Buffer.concat(chunks).toString(),
    contentType: req.headers["content-type"],
  };
  if (req.url?.startsWith("/api/missing")) {
    res.writeHead(404, { "content-type": "application/json" });
    res.end('{"detail":"not found"}');
  } else if (req.method === "DELETE") {
    res.writeHead(204).end();
  } else {
    res.writeHead(200, { "content-type": "application/json" });
    res.end('{"ok":true}');
  }
});

before(async () => {
  await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
  process.env.BACKEND_URL = `http://127.0.0.1:${(server.address() as AddressInfo).port}`;
});
after(() => server.close());

test("GET はパスとクエリ文字列を素通しする", async () => {
  const res = await proxyToBackend(
    new Request("http://app/api/articles?feed_id=3&q=a%20b"),
  );
  assert.equal(res.status, 200);
  assert.equal(res.headers.get("content-type"), "application/json");
  assert.deepEqual(await res.json(), { ok: true });
  assert.equal(seen.method, "GET");
  assert.equal(seen.url, "/api/articles?feed_id=3&q=a%20b");
});

test("POST / PATCH はボディと Content-Type を素通しする", async () => {
  for (const method of ["POST", "PATCH"]) {
    const body = JSON.stringify({ url: "https://example.com/feed" });
    const res = await proxyToBackend(
      new Request("http://app/api/feeds", {
        method,
        headers: { "content-type": "application/json" },
        body,
      }),
    );
    assert.equal(res.status, 200);
    assert.equal(seen.method, method);
    assert.equal(seen.body, body);
    assert.equal(seen.contentType, "application/json");
  }
});

test("DELETE の 204 とバックエンドのエラーステータスを返す", async () => {
  const del = await proxyToBackend(
    new Request("http://app/api/feeds/1", { method: "DELETE" }),
  );
  assert.equal(del.status, 204);
  assert.equal(seen.method, "DELETE");

  const missing = await proxyToBackend(new Request("http://app/api/missing"));
  assert.equal(missing.status, 404);
  assert.deepEqual(await missing.json(), { detail: "not found" });
});

test("BACKEND_URL は呼び出しごとに実行時に読まれる", async () => {
  const original = process.env.BACKEND_URL;
  process.env.BACKEND_URL = "http://127.0.0.1:1";
  const res = await proxyToBackend(new Request("http://app/api/health"));
  assert.equal(res.status, 502);
  process.env.BACKEND_URL = original;
  assert.equal(
    (await proxyToBackend(new Request("http://app/api/health"))).status,
    200,
  );
});

test("バックエンドが落ちていれば 502 を返す", async () => {
  const original = process.env.BACKEND_URL;
  process.env.BACKEND_URL = "http://127.0.0.1:1";
  try {
    const res = await proxyToBackend(new Request("http://app/api/health"));
    assert.equal(res.status, 502);
    assert.match(
      ((await res.json()) as { detail: string }).detail,
      /バックエンド/,
    );
  } finally {
    process.env.BACKEND_URL = original;
  }
});
