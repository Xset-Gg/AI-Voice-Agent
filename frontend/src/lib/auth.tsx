"use client";

import { createContext, useCallback, useContext, useEffect, useState } from "react";
import { api, getToken, setToken } from "./api";
import type { Me, Role } from "./types";

const RANK: Record<Role, number> = { viewer: 0, member: 1, admin: 2, owner: 3 };

interface AuthState {
  me: Me | null;
  loading: boolean;
  login: (email: string, password: string) => Promise<void>;
  register: (data: { organization_name: string; full_name: string; email: string; password: string; timezone: string }) => Promise<void>;
  logout: () => void;
  refresh: () => Promise<void>;
  can: (role: Role) => boolean;
}

const AuthContext = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [me, setMe] = useState<Me | null>(null);
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    if (!getToken()) {
      setMe(null);
      setLoading(false);
      return;
    }
    try {
      setMe(await api<Me>("/auth/me"));
    } catch {
      setMe(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const login = async (email: string, password: string) => {
    const { access_token } = await api<{ access_token: string }>("/auth/login", { body: { email, password } });
    setToken(access_token);
    await refresh();
  };

  const register: AuthState["register"] = async (data) => {
    const { access_token } = await api<{ access_token: string }>("/auth/register", { body: data });
    setToken(access_token);
    await refresh();
  };

  const logout = () => {
    setToken(null);
    setMe(null);
    window.location.href = "/login";
  };

  const can = (role: Role) => !!me && RANK[me.user.role] >= RANK[role];

  return <AuthContext.Provider value={{ me, loading, login, register, logout, refresh, can }}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth outside AuthProvider");
  return ctx;
}
