// ブラウザからの /api/* を、実行時に BACKEND_URL（既定 http://127.0.0.1:8700）のバックエンドへ中継する
const DEFAULT_BACKEND_URL = "http://127.0.0.1:8700";

function backendBase(): string {
  return (process.env.BACKEND_URL ?? DEFAULT_BACKEND_URL).replace(/\/+$/, "");
}

export async function proxyToBackend(request: Request): Promise<Response> {
  const { pathname, search } = new URL(request.url);
  const hasBody = request.method !== "GET" && request.method !== "HEAD";

  const headers = new Headers();
  const contentType = request.headers.get("content-type");
  if (contentType) headers.set("content-type", contentType);
  const accept = request.headers.get("accept");
  if (accept) headers.set("accept", accept);

  let upstream: Response;
  try {
    upstream = await fetch(`${backendBase()}${pathname}${search}`, {
      method: request.method,
      headers,
      body: hasBody ? await request.arrayBuffer() : undefined,
      redirect: "manual",
      cache: "no-store",
    });
  } catch {
    return Response.json(
      {
        detail: "バックエンドに接続できません。起動しているか確認してください",
      },
      { status: 502 },
    );
  }

  const responseHeaders = new Headers();
  const upstreamType = upstream.headers.get("content-type");
  if (upstreamType) responseHeaders.set("content-type", upstreamType);
  const nullBody =
    upstream.status === 204 ||
    upstream.status === 205 ||
    upstream.status === 304;
  return new Response(nullBody ? null : upstream.body, {
    status: upstream.status,
    headers: responseHeaders,
  });
}
