"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { apiFetch, storeSession } from "@/lib/api";
import { GradientBackground } from "@/components/ui/pipo";

type TokenResponse = { access_token: string; refresh_token: string };

export default function LoginPage() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [name, setName] = useState("");
  const [isSignUp, setIsSignUp] = useState(false);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      let data: TokenResponse;
      if (isSignUp) {
        data = await apiFetch<TokenResponse>("/api/auth/register", {
          method: "POST",
          body: JSON.stringify({ email, password, name }),
        });
      } else {
        data = await apiFetch<TokenResponse>("/api/auth/login", {
          method: "POST",
          body: JSON.stringify({ email, password }),
        });
      }
      storeSession(data);
      router.push("/dashboard");
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Authentication failed";
      setError(msg);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="relative flex min-h-screen items-center justify-center overflow-hidden bg-[#faf9ef] px-4">
      <GradientBackground className="fixed inset-0" />
      <div className="relative z-10 w-full max-w-md">
        <div className="text-center mb-8">
          <h1 className="text-2xl font-bold">Emmaus AI</h1>
          <p className="text-text-muted mt-2 text-sm">
            {isSignUp ? "Create your account" : "Sign in to your account"}
          </p>
        </div>
        <form onSubmit={handleSubmit} className="glass-panel space-y-4 rounded-2xl border p-6">
          {isSignUp && (
            <div>
              <label htmlFor="login-name" className="block text-sm text-text-muted mb-1">Name</label>
              <input
                id="login-name"
                type="text"
                value={name}
                onChange={(e) => setName(e.target.value)}
                className="w-full px-3 py-2 glass-input rounded-lg text-text text-sm focus:outline-none focus:border-primary"
                required
              />
            </div>
          )}
          <div>
            <label htmlFor="login-email" className="block text-sm text-text-muted mb-1">Email</label>
              <input
                id="login-email"
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                className="w-full px-3 py-2 glass-input rounded-lg text-text text-sm focus:outline-none focus:border-primary"
                required
              />
          </div>
          <div>
            <label htmlFor="login-password" className="block text-sm text-text-muted mb-1">Password</label>
              <input
                id="login-password"
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                className="w-full px-3 py-2 glass-input rounded-lg text-text text-sm focus:outline-none focus:border-primary"
                required
              />
          </div>
          {error && <div className="text-error text-sm">{error}</div>}
          <button
            type="submit"
            disabled={loading}
            className="w-full py-2.5 bg-primary text-white rounded-lg hover:bg-primary-hover transition-colors text-sm font-medium disabled:opacity-50"
          >
            {loading ? "Loading..." : isSignUp ? "Create account" : "Sign in"}
          </button>
        </form>
        <div className="text-center mt-4">
          <button
            onClick={() => { setIsSignUp(!isSignUp); setError(""); }}
            className="text-sm text-text-muted hover:text-text transition-colors"
          >
            {isSignUp ? "Already have an account? Sign in" : "Don't have an account? Sign up"}
          </button>
        </div>
      </div>
    </div>
  );
}
