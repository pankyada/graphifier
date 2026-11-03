import { NextRequest, NextResponse } from "next/server";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const LOCAL_HOSTS = new Set(["localhost", "127.0.0.1", "[::1]"]);

async function forward(request: NextRequest, context: { params: Promise<{ path: string[] }> }) {
  const origin = request.headers.get("origin");
  if (!LOCAL_HOSTS.has(request.nextUrl.hostname)) {
    return NextResponse.json({ detail: "Graphifier is a local workspace." }, { status: 403 });
  }
  if (origin) {
    try {
      if (!LOCAL_HOSTS.has(new URL(origin).hostname)) {
        return NextResponse.json({ detail: "Non-local origins are not allowed." }, { status: 403 });
      }
    } catch {
      return NextResponse.json({ detail: "Invalid origin." }, { status: 403 });
    }
  }
  const { path } = await context.params;
  const backend = process.env.GRAPHIFIER_API_URL || "http://127.0.0.1:8787";
  const url = new URL(`/api/${path.map(encodeURIComponent).join("/")}`, backend);
  url.search = request.nextUrl.search;
  const headers = new Headers({ Accept: "application/json" });
  const token = process.env.GRAPHIFIER_API_TOKEN;
  if (token) headers.set("Authorization", `Bearer ${token}`);
  const mutating = !["GET", "HEAD"].includes(request.method);
  if (mutating) headers.set("Content-Type", "application/json");
  try {
    const response = await fetch(url, {
      method: request.method,
      headers,
      body: mutating ? await request.text() : undefined,
      cache: "no-store",
      signal: AbortSignal.timeout(60_000),
    });
    return new NextResponse(await response.text(), {
      status: response.status,
      headers: { "Content-Type": "application/json", "Cache-Control": "no-store" },
    });
  } catch {
    return NextResponse.json(
      { detail: "Local API unavailable. Start it with npm run api." },
      { status: 503 },
    );
  }
}

export { forward as GET, forward as POST, forward as PUT, forward as PATCH, forward as DELETE };
