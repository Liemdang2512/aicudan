"use client";

import { create } from "zustand";

interface User {
  id: number;
  email: string;
  full_name: string;
  role: string;
}

interface AuthState {
  user: User | null;
  token: string | null;
  isAuthenticated: boolean;
  isLoading: boolean;
  error: string | null;
  login: (email: string, password: string) => Promise<void>;
  logout: () => void;
  loadFromStorage: () => Promise<void>;
}

export const useAuthStore = create<AuthState>((set) => ({
  user: null,
  token: null,
  isAuthenticated: false,
  isLoading: true,
  error: null,

  login: async (email: string, password: string) => {
    set({ isLoading: true, error: null });
    try {
      const apiBase = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8001/api/v1";
      const response = await fetch(`${apiBase}/auth/login`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          email: email,
          password: password,
        }),
      });

      if (!response.ok) {
        const errorData = await response.json().catch(() => null);
        const message =
          errorData?.detail || "Email hoặc mật khẩu không đúng";
        throw new Error(typeof message === "string" ? message : "Email hoặc mật khẩu không đúng");
      }

      const data = await response.json();
      const token = data.access_token;
      const user = data.user;

      localStorage.setItem("token", token);
      localStorage.setItem("user", JSON.stringify(user));

      set({
        user,
        token,
        isAuthenticated: true,
        isLoading: false,
        error: null,
      });
    } catch (error) {
      set({
        isLoading: false,
        error: error instanceof Error ? error.message : "Đăng nhập thất bại",
      });
      throw error;
    }
  },

  logout: () => {
    localStorage.removeItem("token");
    localStorage.removeItem("user");
    set({
      user: null,
      token: null,
      isAuthenticated: false,
      error: null,
    });
  },

  loadFromStorage: async () => {
    if (typeof window === "undefined") return;
    const token = localStorage.getItem("token");
    if (!token) {
      set({ user: null, token: null, isAuthenticated: false, isLoading: false });
      return;
    }

    set({ isLoading: true });
    try {
      const apiBase = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8001/api/v1";
      const response = await fetch(`${apiBase}/auth/me`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!response.ok) throw new Error("Phiên đăng nhập không còn hợp lệ");

      const user = (await response.json()) as User;
      localStorage.setItem("user", JSON.stringify(user));
      set({ user, token, isAuthenticated: true, isLoading: false, error: null });
    } catch {
      localStorage.removeItem("token");
      localStorage.removeItem("user");
      set({ user: null, token: null, isAuthenticated: false, isLoading: false });
    }
  },
}));
