import { authorizeProxy, backendFetch } from "@/lib/backend";

export const dynamic = "force-dynamic";

export async function POST(
  request: Request,
  ctx: RouteContext<"/api/proxy/leads/[id]/regenerate">,
) {
  const { id } = await ctx.params;
  const auth = await authorizeProxy();
  if (!auth.ok) {
    return Response.json({ error: auth.message }, { status: auth.status });
  }
  const body = await request.text();
  const upstream = await backendFetch(
    `/api/v1/leads/${encodeURIComponent(id)}/regenerate`,
    { method: "POST", body: body || "{}", token: auth.token },
  );
  const text = await upstream.text();
  return new Response(text, {
    status: upstream.status,
    headers: { "Content-Type": upstream.headers.get("Content-Type") ?? "application/json" },
  });
}
