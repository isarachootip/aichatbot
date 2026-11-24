"use client";

import { useEffect, useState } from "react";
import { apiFetch, ApiError } from "@/lib/api";
import type { AnalyticsSummary } from "@/lib/types";
import { DashboardShell } from "@/components/layout/dashboard-shell";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

function AnalyticsContent() {
  const [data, setData] = useState<AnalyticsSummary | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    apiFetch<AnalyticsSummary>("/analytics/summary?days=14")
      .then(setData)
      .catch((err) => setError(err instanceof ApiError ? err.message : "โหลดสถิติไม่สำเร็จ"));
  }, []);

  if (error) {
    return (
      <div className="rounded-lg border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">
        {error}
      </div>
    );
  }
  if (!data) {
    return <div className="text-sm text-slate-500">กำลังโหลดรายงาน...</div>;
  }

  const maxDaily = Math.max(
    1,
    ...data.messages_per_day.map((d) => d.customer_messages + d.bot_messages + d.agent_messages),
  );

  const kpis = [
    { label: "แชททั้งหมด", value: `${data.total_conversations}` },
    { label: "ตอบอัตโนมัติสำเร็จ", value: `${data.auto_resolved_rate}%` },
    { label: "อัตราการส่งต่อแอดมิน", value: `${data.handoff_rate}%` },
    {
      label: "โควต้าข้อความเดือนนี้",
      value: `${data.used_messages_this_month} / ${data.limit_messages_this_month}`,
    },
  ];

  return (
    <div className="space-y-6">
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {kpis.map((kpi) => (
          <Card key={kpi.label}>
            <CardContent>
              <div className="text-xs font-medium text-slate-500">{kpi.label}</div>
              <div className="mt-2 text-2xl font-bold text-slate-900">{kpi.value}</div>
            </CardContent>
          </Card>
        ))}
      </div>

      <Card>
        <CardHeader>
          <CardTitle>จำนวนข้อความรายวัน (14 วันล่าสุด)</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="flex h-48 items-end gap-2">
            {data.messages_per_day.map((day) => {
              const total = day.customer_messages + day.bot_messages + day.agent_messages;
              const pct = Math.max(4, Math.round((total / maxDaily) * 100));
              return (
                <div key={day.date} className="flex flex-1 flex-col items-center gap-1">
                  <div className="text-[10px] text-slate-500">{total}</div>
                  <div className="flex h-32 w-full items-end rounded-md bg-slate-100 p-0.5">
                    <div
                      style={{ height: `${total === 0 ? 2 : pct}%` }}
                      className="w-full rounded-sm bg-teal-600 transition-all"
                      title={`${day.date}: ลูกค้า ${day.customer_messages}, บอท ${day.bot_messages}, แอดมิน ${day.agent_messages}`}
                    />
                  </div>
                  <div className="text-[10px] text-slate-400">{day.date.slice(5)}</div>
                </div>
              );
            })}
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>คำถามที่บอทยังตอบไม่ได้บ่อยที่สุด</CardTitle>
        </CardHeader>
        <CardContent>
          {data.top_unanswered_questions.length === 0 ? (
            <p className="text-sm text-slate-500">ยังไม่มีคำถามที่ต้องส่งต่อแอดมินในช่วงนี้</p>
          ) : (
            <ul className="divide-y divide-slate-100 text-sm">
              {data.top_unanswered_questions.map((item) => (
                <li key={item.question} className="flex items-center justify-between py-2.5">
                  <span className="text-slate-800">{item.question}</span>
                  <span className="rounded-full bg-amber-50 px-2.5 py-0.5 text-xs font-semibold text-amber-800">
                    {item.count} ครั้ง
                  </span>
                </li>
              ))}
            </ul>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

export default function AnalyticsPage() {
  return (
    <DashboardShell
      title="สถิติและรายงาน (Analytics)"
      subtitle="ติดตามอัตราการตอบอัตโนมัติ การส่งต่อแอดมิน และช่องว่างในคลังความรู้"
    >
      {() => <AnalyticsContent />}
    </DashboardShell>
  );
}
