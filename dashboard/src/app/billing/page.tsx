"use client";

import { CreditCard } from "lucide-react";
import type { MeResponse } from "@/lib/types";
import { DashboardShell } from "@/components/layout/dashboard-shell";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

const PLAN_OPTIONS = [
  { name: "Starter", price: "฿990 / เดือน", quota: "1,000 ข้อความ/เดือน", channels: "1 ช่องทาง", docs: "20 ไฟล์" },
  { name: "Pro", price: "฿2,490 / เดือน", quota: "5,000 ข้อความ/เดือน", channels: "3 ช่องทาง", docs: "100 ไฟล์" },
  { name: "Business", price: "฿5,990 / เดือน", quota: "20,000 ข้อความ/เดือน", channels: "10 ช่องทาง", docs: "500 ไฟล์" },
];

function BillingContent({ me }: { me: MeResponse }) {
  const pct = Math.min(100, Math.round((me.used_messages / Math.max(1, me.limit_messages)) * 100));

  return (
    <div className="mx-auto max-w-4xl space-y-6">
      <Card>
        <CardHeader>
          <div className="flex items-center justify-between">
            <CardTitle>แพ็กเกจปัจจุบัน: {me.plan.toUpperCase()}</CardTitle>
            <Badge tone={me.status === "active" ? "success" : "warning"}>{me.status}</Badge>
          </div>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="flex justify-between text-sm">
            <span className="text-slate-600">ปริมาณข้อความที่ใช้เดือนนี้</span>
            <span className="font-semibold text-slate-900">
              {me.used_messages} / {me.limit_messages} ข้อความ ({pct}%)
            </span>
          </div>
          <div className="h-2.5 w-full overflow-hidden rounded-full bg-slate-100">
            <div style={{ width: `${pct}%` }} className="h-full rounded-full bg-teal-600" />
          </div>
          <div className="flex items-center gap-2 rounded-lg bg-slate-50 p-3 text-xs text-slate-600">
            <CreditCard className="h-4 w-4 shrink-0 text-teal-700" />
            <span>
              ระบบชำระเงินผ่าน Omise (บัตรเครดิตตัดรอบรายเดือน และ PromptPay QR) จะเปิดให้ใช้งานใน Phase 6
            </span>
          </div>
        </CardContent>
      </Card>

      <div className="grid gap-4 md:grid-cols-3">
        {PLAN_OPTIONS.map((plan) => (
          <Card key={plan.name}>
            <CardHeader>
              <CardTitle>{plan.name}</CardTitle>
              <div className="mt-1 text-xl font-bold text-teal-700">{plan.price}</div>
            </CardHeader>
            <CardContent className="space-y-1.5 text-sm text-slate-600">
              <div>• {plan.quota}</div>
              <div>• {plan.channels}</div>
              <div>• คลังความรู้สูงสุด {plan.docs}</div>
            </CardContent>
          </Card>
        ))}
      </div>
    </div>
  );
}

export default function BillingPage() {
  return (
    <DashboardShell
      title="แพ็กเกจและการเงิน (Billing)"
      subtitle="ตรวจสอบโควต้าข้อความรายเดือนและแพ็กเกจสำหรับร้านค้า"
    >
      {(me) => <BillingContent me={me} />}
    </DashboardShell>
  );
}
