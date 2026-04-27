import type { NextRequest } from "next/server";
import { authorizeProxy, backendFetch } from "@/lib/backend";

export const dynamic = "force-dynamic";

export async function GET(request: NextRequest) {
  const auth = await authorizeProxy();
  if (!auth.ok) {
    return Response.json({ error: auth.message }, { status: auth.status });
  }
  const search = request.nextUrl.search;
  const upstream = await backendFetch(`/api/v1/leads${search}`, {
    method: "GET",
    token: auth.token,
  });
  const text = await upstream.text();
  return new Response(text, {
    status: upstream.status,
    headers: { "Content-Type": upstream.headers.get("Content-Type") ?? "application/json" },
  });
}
