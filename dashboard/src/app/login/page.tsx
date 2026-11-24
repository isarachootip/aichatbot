"use client";

import { useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { apiFetch, ApiError } from "@/lib/api";
import { setAccessToken } from "@/lib/auth";
import type { AuthTokenResponse } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";

export default function LoginPage() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      const res = await apiFetch<AuthTokenResponse>("/auth/dev-login", {
        method: "POST",
        skipAuth: true,
        body: JSON.stringify({ email }),
      });
      if (!res.access_token) {
        setError("กรุณาเข้าสู่ระบบผ่าน Supabase Auth");
        return;
      }
      setAccessToken(res.access_token);
      router.replace(res.role === "agent" ? "/inbox" : "/onboarding");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "ไม่สามารถเข้าสู่ระบบได้");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="flex min-h-screen items-center justify-center bg-slate-50 p-4">
      <Card className="w-full max-w-md">
        <CardHeader>
          <div className="text-lg font-bold text-teal-700">ShopAI</div>
          <CardTitle className="mt-1">เข้าสู่ระบบแดชบอร์ดร้านค้า</CardTitle>
        </CardHeader>
        <CardContent>
          <form onSubmit={handleSubmit} className="space-y-4">
            <div>
              <label htmlFor="login-email" className="mb-1.5 block text-sm font-medium text-slate-700">
                อีเมลผู้ใช้งาน
              </label>
              <Input
                id="login-email"
                type="email"
                required
                placeholder="owner@yourshop.th"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
              />
            </div>
            {error ? (
              <p className="rounded-lg bg-rose-50 px-3 py-2 text-sm text-rose-700">{error}</p>
            ) : null}
            <Button type="submit" className="w-full" disabled={submitting}>
              {submitting ? "กำลังเข้าสู่ระบบ..." : "เข้าสู่ระบบ"}
            </Button>
          </form>
          <p className="mt-4 text-center text-sm text-slate-600">
            ยังไม่มีบัญชีร้านค้า?{" "}
            <Link href="/signup" className="font-medium text-teal-700 hover:underline">
              สมัครทดลองใช้ฟรี 7 วัน
            </Link>
          </p>
        </CardContent>
      </Card>
    </div>
  );
}
