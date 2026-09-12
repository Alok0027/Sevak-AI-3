import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "../context/AuthContext";

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
      setError(err.response?.data?.detail || "Login failed");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="login-page">
      <form className="login-card" onSubmit={handleSubmit}>
        {/* Same wordmark as the nav rail -- the 3px status bar stood on
            end. It is the first thing anyone sees of the product, and it
            should be the thing they keep seeing. */}
        <div className="login-brand">
          <span className="rail-mark" aria-hidden="true" />
          <h1>SevakAI</h1>
        </div>
        <p className="subtitle">District health supervision</p>

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
