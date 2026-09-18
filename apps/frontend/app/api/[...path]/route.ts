import { NextRequest } from "next/server";
export const dynamic = "force-dynamic";
export const runtime = "nodejs";
async function proxy(
  request: NextRequest,
  context: { params: Promise<{ path: string[] }> },
) {
  const { path } = await context.params;
  if (path.some((p) => p === ".." || p.includes("/") || p.includes("\\")))
    return new Response("Invalid path", { status: 400 });
  const backend = process.env.BACKEND_URL || "http://127.0.0.1:8000";
  const url =
    backend +
    "/api/" +
    path.map(encodeURIComponent).join("/") +
    request.nextUrl.search;
  const headers = new Headers();
  for (const name of [
    "content-type",
    "cookie",
    "origin",
    "range",
    "x-opus-signature",
    "x-opus-salt",
    "x-opus-timestamp",
  ]) {
    const value = request.headers.get(name);
    if (value) headers.set(name, value);
  }
  try {
    const response = await fetch(url, {
      method: request.method,
      headers,
      body: ["GET", "HEAD"].includes(request.method)
        ? undefined
        : await request.arrayBuffer(),
      cache: "no-store",
      redirect: "manual",
      signal: AbortSignal.timeout(30000),
    });
    const out = new Headers();
    for (const name of [
      "content-type",
      "set-cookie",
      "content-disposition",
      "content-range",
      "accept-ranges",
      "content-length",
      "x-request-id",
    ]) {
      const value = response.headers.get(name);
      if (value) out.set(name, value);
    }
    out.set("Cache-Control", "no-store");
    return new Response(response.body, {
      status: response.status,
      headers: out,
    });
  } catch {
    return Response.json(
      {
        detail:
          "The backend is unavailable. Start the backend service and refresh.",
      },
      { status: 503 },
    );
  }
}
export {
  proxy as GET,
  proxy as POST,
  proxy as PUT,
  proxy as PATCH,
  proxy as DELETE,
};
