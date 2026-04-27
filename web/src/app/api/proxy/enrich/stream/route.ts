import { authorizeProxy, backendFetch } from "@/lib/backend";

export const dynamic = "force-dynamic";

export async function POST(request: Request) {
  const auth = await authorizeProxy();
  if (!auth.ok) {
    return Response.json({ error: auth.message }, { status: auth.status });
  }
  const body = await request.text();
  const upstream = await backendFetch("/api/v1/enrich/stream", {
    method: "POST",
    body,
    token: auth.token,
  });

  if (!upstream.ok || !upstream.body) {
    const text = await upstream.text().catch(() => "");
    return new Response(text || "upstream error", { status: upstream.status });
  }

  return new Response(upstream.body, {
    status: 200,
    headers: {
      "Content-Type": "text/event-stream",
      "Cache-Control": "no-cache, no-transform",
      "X-Accel-Buffering": "no",
    },
  });
}
