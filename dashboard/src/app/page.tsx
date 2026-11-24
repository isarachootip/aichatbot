"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { getAccessToken } from "@/lib/auth";

export default function HomePage() {
  const router = useRouter();

  useEffect(() => {
    router.replace(getAccessToken() ? "/onboarding" : "/login");
  }, [router]);

  return (
    <div className="flex min-h-screen items-center justify-center text-sm text-slate-500">
      กำลังนำทาง...
    </div>
  );
}
