import { SignJWT } from "jose";
import { auth } from "@/auth";

const BACKEND_URL = process.env.BACKEND_URL ?? "http://localhost:8000";
const TOKEN_TTL_SECONDS = 60 * 60;

function secretKey(): Uint8Array {
  const secret = process.env.NEXTAUTH_SECRET;
  if (!secret) throw new Error("NEXTAUTH_SECRET is not set");
  return new TextEncoder().encode(secret);
}

export async function mintBackendJwt(email: string): Promise<string> {
  return new SignJWT({ email })
    .setProtectedHeader({ alg: "HS256" })
    .setIssuedAt()
    .setExpirationTime(`${TOKEN_TTL_SECONDS}s`)
    .sign(secretKey());
}

export type ProxyResult =
  | { ok: true; email: string; token: string }
  | { ok: false; status: number; message: string };

export async function authorizeProxy(): Promise<ProxyResult> {
  const session = await auth();
  const email = session?.user?.email;
  if (!email) return { ok: false, status: 401, message: "no session" };
  const token = await mintBackendJwt(email);
  return { ok: true, email, token };
}

export function backendUrl(path: string): string {
  return `${BACKEND_URL}${path.startsWith("/") ? path : `/${path}`}`;
}

export async function backendFetch(
  path: string,
  init: RequestInit & { token: string },
): Promise<Response> {
  const headers = new Headers(init.headers);
  headers.set("Authorization", `Bearer ${init.token}`);
  if (init.body && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  return fetch(backendUrl(path), { ...init, headers });
}
