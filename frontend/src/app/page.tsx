"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/context/AuthContext";
import { Loader2 } from "lucide-react";

export default function RootPage() {
  const { user, loading } = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (!loading) {
      if (user) {
        router.replace("/dashboard");
      } else {
        router.replace("/login");
      }
    }
  }, [user, loading, router]);

  return (
    <div className="flex h-screen w-screen items-center justify-center bg-zinc-950">
      <div className="flex flex-col items-center gap-4">
        <div className="relative flex h-16 w-16 items-center justify-center rounded-full bg-indigo-500/10 text-indigo-400">
          <Loader2 className="h-8 w-8 animate-spin" />
        </div>
        <h1 className="text-xl font-bold tracking-wider text-zinc-100">DocMind</h1>
        <p className="text-sm text-zinc-400">Preparing your space...</p>
      </div>
    </div>
  );
}
