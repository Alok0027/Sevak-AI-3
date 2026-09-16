import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "../context/AuthContext";
import { apiConfigProblem } from "../api/client";

export default function LoginPage() {
  const [phone, setPhone] = useState("9999999901"); // demo ANM account
  const [pin, setPin] = useState("1234");
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(false);
  const { login } = useAuth();
  const navigate = useNavigate();

  async function handleSubmit(e) {
    e.preventDefault();
    setLoading(true);
    setError(null);
    try {
      await login(phone, pin);
      navigate("/");
    } catch (err) {
      // err.message carries the configuration problem when there is one;
      // "Login failed" is only honest when the server actually answered.
      setError(err.response?.data?.detail || err.message || "Login failed");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="login-page">
      <form className="login-card" onSubmit={handleSubmit}>
        {/* The one screen with room for the emblem at a size where its
            motto is legible. Everywhere behind this, the rail shows it
            small and the page belongs to the work. */}
        <div className="login-brand">
          <img className="login-logo" src="/sevakai-emblem.png" alt="SevakAI" />
          <h1>SevakAI</h1>
        </div>
        <p className="subtitle">District health supervision</p>

        {/* Shown before she types anything: if the build cannot reach an
            API at all, every PIN she tries will look wrong. */}
        {apiConfigProblem && <p className="error">{apiConfigProblem}</p>}

        {new URLSearchParams(window.location.search).has("expired") && (
          <p className="notice">Your session timed out after 8 hours. Sign in to pick up where you left off.</p>
        )}

        <label>
          Phone
          <input value={phone} onChange={(e) => setPhone(e.target.value)} inputMode="numeric" />
        </label>
        <label>
          PIN
          <input type="password" value={pin} onChange={(e) => setPin(e.target.value)} inputMode="numeric" />
        </label>

        {error && <p className="error">{error}</p>}

        <button type="submit" disabled={loading}>
          {loading ? "Signing in…" : "Sign in"}
        </button>

        <div className="hint">
          <span className="hint-title">Demo accounts</span>
          ANM 9999999901 · BMO 9999999902 · Admin 9999999903 — PIN 1234
        </div>
      </form>
    </div>
  );
}
