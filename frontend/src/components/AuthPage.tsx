import { FormEvent, useState } from "react";
import { login, register, storeAuth } from "../api";
import type { User } from "../types";

interface Props {
  onAuthenticated: (user: User) => void;
  onCancel: () => void;
  onContinueDemo: () => void;
}

type AuthMode = "login" | "register";

export default function AuthPage({ onAuthenticated, onCancel, onContinueDemo }: Props) {
  const [mode, setMode] = useState<AuthMode>("login");
  const [email, setEmail] = useState("demo@example.com");
  const [password, setPassword] = useState("password123");
  const [showPassword, setShowPassword] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    setLoading(true);
    setError("");
    try {
      const auth = mode === "login" ? await login(email, password) : await register(email, password);
      storeAuth(auth, "signed-in");
      onAuthenticated(auth.user);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Authentication failed.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <main className="auth-page focused-auth-page">
      <section className="panel auth-panel focused-auth-panel">
        <button className="auth-back" type="button" onClick={onCancel}>
          Back to demo workspace
        </button>

        <div className="auth-title">
          <p className="eyebrow">Optional account</p>
          <h1>Sign in to save your workspace</h1>
          <p>Demo mode is active. Sign in only if you want a private workspace.</p>
        </div>

        <div className="auth-tabs" role="tablist" aria-label="Authentication mode">
          <button className={mode === "login" ? "active" : ""} type="button" onClick={() => setMode("login")}>
            Login
          </button>
          <button className={mode === "register" ? "active" : ""} type="button" onClick={() => setMode("register")}>
            Register
          </button>
        </div>

        <form className="auth-form" onSubmit={handleSubmit}>
          <label htmlFor="auth-email">Email</label>
          <input
            id="auth-email"
            name="email"
            value={email}
            onChange={(event) => setEmail(event.target.value)}
            type="email"
            autoComplete="username"
            required
          />

          <div className="password-label-row">
            <label htmlFor={mode === "login" ? "current-password" : "new-password"}>Password</label>
            <button className="show-password-button" type="button" onClick={() => setShowPassword((value) => !value)}>
              {showPassword ? "Hide" : "Show"}
            </button>
          </div>
          <input
            id={mode === "login" ? "current-password" : "new-password"}
            name={mode === "login" ? "current-password" : "new-password"}
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            type={showPassword ? "text" : "password"}
            autoComplete={mode === "login" ? "current-password" : "new-password"}
            minLength={6}
            required
          />

          {error && <p className="error">{error}</p>}

          <button className="button primary" disabled={loading || !email.trim() || password.length < 6}>
            {loading ? "Please wait..." : mode === "login" ? "Sign in" : "Create account"}
          </button>
          <button className="button secondary" type="button" onClick={onContinueDemo}>
            Continue as demo
          </button>
        </form>
      </section>
    </main>
  );
}
