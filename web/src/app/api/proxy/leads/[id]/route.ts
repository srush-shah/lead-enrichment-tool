import { authorizeProxy, backendFetch } from "@/lib/backend";

export const dynamic = "force-dynamic";

export async function GET(_req: Request, ctx: RouteContext<"/api/proxy/leads/[id]">) {
  const { id } = await ctx.params;
  const auth = await authorizeProxy();
  if (!auth.ok) {
    return Response.json({ error: auth.message }, { status: auth.status });
  }
  const upstream = await backendFetch(`/api/v1/leads/${encodeURIComponent(id)}`, {
    method: "GET",
    token: auth.token,
  });
  const text = await upstream.text();
  return new Response(text, {
    status: upstream.status,
    headers: { "Content-Type": upstream.headers.get("Content-Type") ?? "application/json" },
  });
}
