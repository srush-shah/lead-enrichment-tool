import NextAuth from "next-auth";
import Google from "next-auth/providers/google";

function allowedEmails(): Set<string> {
  return new Set(
    (process.env.ALLOWED_EMAILS ?? "")
      .split(",")
      .map((e) => e.trim().toLowerCase())
      .filter(Boolean),
  );
}

export const { handlers, auth, signIn, signOut } = NextAuth({
  providers: [
    Google({
      clientId: process.env.GOOGLE_CLIENT_ID,
      clientSecret: process.env.GOOGLE_CLIENT_SECRET,
    }),
  ],
  pages: {
    signIn: "/login",
  },
  callbacks: {
    async signIn({ user }) {
      const allow = allowedEmails();
      if (allow.size === 0) return true;
      const email = user?.email?.toLowerCase();
      if (!email || !allow.has(email)) return "/access-denied";
      return true;
    },
    async jwt({ token, user }) {
      if (user?.email) token.email = user.email;
      return token;
    },
    async session({ session, token }) {
      if (token.email && session.user) {
        session.user.email = token.email as string;
      }
      return session;
    },
  },
});
