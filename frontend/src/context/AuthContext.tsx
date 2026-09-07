"use client";

import React, { createContext, useContext, useState, useEffect } from "react";
import { useRouter } from "next/navigation";

interface User {
  id: number;
  username: string;
  email: string;
}

interface AuthContextType {
  user: User | null;
  loading: boolean;
  login: (username: string, password: string) => Promise<{ success: boolean; error?: string }>;
  signup: (username: string, email: string, password: string) => Promise<{ success: boolean; error?: string }>;
  logout: () => void;
  apiFetch: (endpoint: string, options?: RequestInit) => Promise<Response>;
  backendUrl: string;
}

const AuthContext = createContext<AuthContextType | null>(null);

const getBackendUrl = () => {
  if (typeof window !== "undefined") {
    // If the frontend is running on port 3000 (standard dev port), assume backend is on port 8000
    if (window.location.port === "3000") {
      return `http://${window.location.hostname}:8000`;
    }
    // Otherwise, direct all requests to the current host/port or relative path
    return "";
  }
  return "http://127.0.0.1:8000";
};

const BACKEND_URL = process.env.NEXT_PUBLIC_BACKEND_URL !== undefined ? process.env.NEXT_PUBLIC_BACKEND_URL : getBackendUrl();

const parseResponseData = async (res: Response) => {
  const contentType = res.headers.get("content-type");
  if (contentType && contentType.includes("application/json")) {
    try {
      return await res.json();
    } catch {
      return null;
    }
  }
  return null;
};

export const AuthProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);
  const router = useRouter();

  useEffect(() => {
    const initAuth = async () => {
      const access = localStorage.getItem("access_token");
      if (!access) {
        setLoading(false);
        return;
      }

      try {
        const res = await fetch(`${BACKEND_URL}/api/auth/me/`, {
          headers: {
            "Authorization": `Bearer ${access}`,
          },
        });

        if (res.ok) {
          const userData = await parseResponseData(res);
          if (userData) setUser(userData);
        } else if (res.status === 401) {
          // Try to refresh
          await refreshAccessToken();
        } else {
          clearTokens();
        }
      } catch (err) {
        console.error("Auth init error:", err);
      } finally {
        setLoading(false);
      }
    };

    initAuth();
  }, []);

  const clearTokens = () => {
    localStorage.removeItem("access_token");
    localStorage.removeItem("refresh_token");
    setUser(null);
  };

  const refreshAccessToken = async () => {
    const refresh = localStorage.getItem("refresh_token");
    if (!refresh) {
      clearTokens();
      return null;
    }

    try {
      const res = await fetch(`${BACKEND_URL}/api/auth/refresh/`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ refresh }),
      });

      if (res.ok) {
        const data = await parseResponseData(res);
        if (data && data.access) {
          localStorage.setItem("access_token", data.access);
          if (data.refresh) {
            localStorage.setItem("refresh_token", data.refresh);
          }

          // Refetch user profile
          const userRes = await fetch(`${BACKEND_URL}/api/auth/me/`, {
            headers: {
              "Authorization": `Bearer ${data.access}`,
            },
          });
          if (userRes.ok) {
            const userData = await parseResponseData(userRes);
            if (userData) setUser(userData);
          }
          return data.access;
        }
      }
      clearTokens();
      return null;
    } catch (err) {
      console.error("Token refresh failed:", err);
      clearTokens();
      return null;
    }
  };

  const login = async (username: string, password: string) => {
    try {
      const res = await fetch(`${BACKEND_URL}/api/auth/login/`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ username, password }),
      });

      const data = await parseResponseData(res);

      if (res.ok && data) {
        localStorage.setItem("access_token", data.access);
        localStorage.setItem("refresh_token", data.refresh);
        
        // Fetch user data
        try {
          const userRes = await fetch(`${BACKEND_URL}/api/auth/me/`, {
            headers: {
              "Authorization": `Bearer ${data.access}`,
            },
          });
          if (userRes.ok) {
            const userData = await parseResponseData(userRes);
            if (userData) setUser(userData);
          }
        } catch (e) {
          console.error("Failed to fetch user info after login:", e);
        }
        
        router.push("/dashboard");
        return { success: true };
      } else {
        if (!data) {
          if (res.status === 404) {
            return {
              success: false,
              error: `Backend API route not found (HTTP 404). Please ensure NEXT_PUBLIC_BACKEND_URL is set in environment settings.`,
            };
          }
          return {
            success: false,
            error: `Backend server error (HTTP ${res.status} ${res.statusText || ""}). Check if backend server is online.`,
          };
        }
        return { success: false, error: data.detail || data.non_field_errors?.[0] || "Invalid username or password" };
      }
    } catch (err: any) {
      console.error("Login error:", err);
      return { success: false, error: "Network error: Cannot connect to backend server. Please verify network or NEXT_PUBLIC_BACKEND_URL." };
    }
  };

  const signup = async (username: string, email: string, password: string) => {
    try {
      const res = await fetch(`${BACKEND_URL}/api/auth/signup/`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ username, email, password }),
      });

      const data = await parseResponseData(res);

      if (res.ok && data) {
        localStorage.setItem("access_token", data.access);
        localStorage.setItem("refresh_token", data.refresh);
        setUser(data.user);
        router.push("/dashboard");
        return { success: true };
      } else {
        if (!data) {
          if (res.status === 404) {
            return {
              success: false,
              error: `Backend API route not found (HTTP 404). Please ensure NEXT_PUBLIC_BACKEND_URL is set.`,
            };
          }
          return {
            success: false,
            error: `Backend server error (HTTP ${res.status} ${res.statusText || ""}). Check if backend server is online.`,
          };
        }
        const errorMsg = data.username ? data.username[0] : (data.email ? data.email[0] : (data.password ? data.password[0] : (data.detail || "Signup failed")));
        return { success: false, error: errorMsg };
      }
    } catch (err: any) {
      console.error("Signup error:", err);
      return { success: false, error: "Network error: Cannot connect to backend server. Please verify network or NEXT_PUBLIC_BACKEND_URL." };
    }
  };

  const logout = () => {
    clearTokens();
    router.push("/login");
  };

  const apiFetch = async (endpoint: string, options: RequestInit = {}): Promise<Response> => {
    let access = localStorage.getItem("access_token");
    
    const headers = {
      ...(options.headers || {}),
    } as Record<string, string>;

    if (!(options.body instanceof FormData)) {
      headers["Content-Type"] = "application/json";
    }

    if (access) {
      headers["Authorization"] = `Bearer ${access}`;
    }

    let response = await fetch(`${BACKEND_URL}${endpoint}`, {
      ...options,
      headers,
    });

    if (response.status === 401) {
      const newAccess = await refreshAccessToken();
      if (newAccess) {
        headers["Authorization"] = `Bearer ${newAccess}`;
        response = await fetch(`${BACKEND_URL}${endpoint}`, {
          ...options,
          headers,
        });
      } else {
        logout();
      }
    }

    return response;
  };

  return (
    <AuthContext.Provider value={{ user, loading, login, signup, logout, apiFetch, backendUrl: BACKEND_URL }}>
      {children}
    </AuthContext.Provider>
  );
};

export const useAuth = () => {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error("useAuth must be used within an AuthProvider");
  }
  return context;
};
