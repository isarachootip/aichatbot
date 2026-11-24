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

export default function SignupPage() {
  const router = useRouter();
  const [shopName, setShopName] = useState("");
  const [email, setEmail] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      const res = await apiFetch<AuthTokenResponse>("/signup", {
        method: "POST",
        skipAuth: true,
        body: JSON.stringify({ shop_name: shopName, email }),
      });
      if (res.access_token) {
        setAccessToken(res.access_token);
      }
      router.replace("/onboarding");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "สมัครสมาชิกไม่สำเร็จ");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="flex min-h-screen items-center justify-center bg-slate-50 p-4">
      <Card className="w-full max-w-md">
        <CardHeader>
          <div className="text-lg font-bold text-teal-700">ShopAI</div>
          <CardTitle className="mt-1">เริ่มทดลองใช้งานฟรี 7 วัน</CardTitle>
          <p className="mt-1 text-xs text-slate-500">ไม่ต้องผูกบัตรเครดิต ตั้งค่าบอทเสร็จใน 5 นาที</p>
        </CardHeader>
        <CardContent>
          <form onSubmit={handleSubmit} className="space-y-4">
            <div>
              <label htmlFor="shop-name" className="mb-1.5 block text-sm font-medium text-slate-700">
                ชื่อร้านค้า
              </label>
              <Input
                id="shop-name"
                required
                placeholder="เช่น ร้านสยามคอสเมติก"
                value={shopName}
                onChange={(e) => setShopName(e.target.value)}
              />
            </div>
            <div>
              <label htmlFor="signup-email" className="mb-1.5 block text-sm font-medium text-slate-700">
                อีเมลเจ้าของร้าน
              </label>
              <Input
                id="signup-email"
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
              {submitting ? "กำลังสร้างร้านค้า..." : "สร้างบัญชีและเริ่มใช้งาน"}
            </Button>
          </form>
          <p className="mt-4 text-center text-sm text-slate-600">
            มีบัญชีอยู่แล้ว?{" "}
            <Link href="/login" className="font-medium text-teal-700 hover:underline">
              เข้าสู่ระบบ
            </Link>
          </p>
        </CardContent>
      </Card>
    </div>
  );
}
