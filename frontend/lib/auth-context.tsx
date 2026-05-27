"use client";

import React, { createContext, useContext, useState, useEffect, useCallback } from "react";
import api from "./api";
import type { UserResponse, TokenResponse, UserLogin, UserRegister } from "@/types/api";

interface AuthContextType {
  user: UserResponse | null;
  token: string | null;
  isLoading: boolean;
  login: (data: UserLogin) => Promise<void>;
  register: (data: UserRegister) => Promise<void>;
  logout: () => void;
  isAuthenticated: boolean;
}

const AuthContext = createContext<AuthContextType | null>(null);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<UserResponse | null>(null);
  const [token, setToken] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    const storedToken = localStorage.getItem("access_token");
    const storedUser = localStorage.getItem("user");
    if (storedToken && storedUser) {
      setToken(storedToken);
      try {
        setUser(JSON.parse(storedUser));
      } catch {
        localStorage.removeItem("user");
      }
    }
    setIsLoading(false);
  }, []);

  const login = useCallback(async (data: UserLogin) => {
    const res = await api.post<TokenResponse>("/auth/login", data);
    const { access_token } = res.data;
    localStorage.setItem("access_token", access_token);
    setToken(access_token);

    const meRes = await api.get<UserResponse>("/auth/me");
    localStorage.setItem("user", JSON.stringify(meRes.data));
    setUser(meRes.data);
  }, []);

  const register = useCallback(async (data: UserRegister) => {
    await api.post("/auth/register", data);
  }, []);

  const logout = useCallback(() => {
    localStorage.removeItem("access_token");
    localStorage.removeItem("user");
    setToken(null);
    setUser(null);
  }, []);

  return (
    <AuthContext.Provider
      value={{ user, token, isLoading, login, register, logout, isAuthenticated: !!token }}
    >
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}
