import { createContext, useContext, useState, useCallback } from "react";
import { login as apiLogin } from "../api/client";

const AuthContext = createContext(null);

export function AuthProvider({ children }) {
  const [auth, setAuth] = useState(() => {
    const token = localStorage.getItem("sevakai_token");
    const role = localStorage.getItem("sevakai_role");
    const workerId = localStorage.getItem("sevakai_worker_id");
    // The login response has always carried worker_name; it just wasn't
    // kept. The shell shows who is signed in, and "BMO" alone doesn't
    // answer that -- a district has one dashboard and several people
    // with the login for it.
    const workerName = localStorage.getItem("sevakai_worker_name");
    return token ? { token, role, workerId, workerName } : null;
  });

  const login = useCallback(async (phone, pin) => {
    const result = await apiLogin(phone, pin);
    localStorage.setItem("sevakai_token", result.access_token);
    localStorage.setItem("sevakai_role", result.role);
    localStorage.setItem("sevakai_worker_id", result.worker_id);
    localStorage.setItem("sevakai_worker_name", result.worker_name ?? "");
    setAuth({
      token: result.access_token,
      role: result.role,
      workerId: result.worker_id,
      workerName: result.worker_name ?? "",
    });
    return result;
  }, []);

  const logout = useCallback(() => {
    localStorage.removeItem("sevakai_token");
    localStorage.removeItem("sevakai_role");
    localStorage.removeItem("sevakai_worker_id");
    localStorage.removeItem("sevakai_worker_name");
    setAuth(null);
  }, []);

  return <AuthContext.Provider value={{ auth, login, logout }}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}
