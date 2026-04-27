import { backendUrl } from "@/lib/backend";

export const dynamic = "force-dynamic";

export async function GET() {
  try {
    const res = await fetch(backendUrl("/health"), { cache: "no-store" });
    const body = await res.text();
    return new Response(body, {
      status: res.status,
      headers: { "Content-Type": res.headers.get("Content-Type") ?? "application/json" },
    });
  } catch (err) {
    const message = err instanceof Error ? err.message : "backend unreachable";
    return Response.json({ status: "down", error: message }, { status: 503 });
  }
}
