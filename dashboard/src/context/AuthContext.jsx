import { createContext, useContext, useState, useCallback } from "react";
import { login as apiLogin } from "../api/client";

const AuthContext = createContext(null);

export function AuthProvider({ children }) {
  const [auth, setAuth] = useState(() => {
    const token = localStorage.getItem("sevakai_token");
    const role = localStorage.getItem("sevakai_role");
    const workerId = localStorage.getItem("sevakai_worker_id");
    return token ? { token, role, workerId } : null;
  });

  const login = useCallback(async (phone, pin) => {
    const result = await apiLogin(phone, pin);
    localStorage.setItem("sevakai_token", result.access_token);
    localStorage.setItem("sevakai_role", result.role);
    localStorage.setItem("sevakai_worker_id", result.worker_id);
    setAuth({ token: result.access_token, role: result.role, workerId: result.worker_id });
    return result;
  }, []);

  const logout = useCallback(() => {
    localStorage.removeItem("sevakai_token");
    localStorage.removeItem("sevakai_role");
    localStorage.removeItem("sevakai_worker_id");
    setAuth(null);
  }, []);

  return <AuthContext.Provider value={{ auth, login, logout }}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}
