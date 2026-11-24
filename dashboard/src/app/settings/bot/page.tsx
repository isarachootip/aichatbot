"use client";

import { useEffect, useState } from "react";
import { Save } from "lucide-react";
import { apiFetch, ApiError } from "@/lib/api";
import type { BotSettings } from "@/lib/types";
import { DashboardShell } from "@/components/layout/dashboard-shell";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input, Textarea } from "@/components/ui/input";

function BotSettingsContent() {
  const [form, setForm] = useState<BotSettings | null>(null);
  const [keywordsText, setKeywordsText] = useState("");
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    apiFetch<BotSettings>("/settings/bot")
      .then((data) => {
        setForm(data);
        setKeywordsText(data.handoff_keywords.join(", "));
      })
      .catch((err) => setError(err instanceof ApiError ? err.message : "โหลดการตั้งค่าไม่สำเร็จ"));
  }, []);

  if (!form) {
    return <div className="text-sm text-slate-500">กำลังโหลดการตั้งค่าบอท...</div>;
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setMessage(null);
    setSaving(true);
    try {
      const updated = await apiFetch<BotSettings>("/settings/bot", {
        method: "PUT",
        body: JSON.stringify({
          ...form,
          handoff_keywords: keywordsText
            .split(",")
            .map((k) => k.trim())
            .filter(Boolean),
        }),
      });
      setForm(updated);
      setKeywordsText(updated.handoff_keywords.join(", "));
      setMessage("บันทึกการตั้งค่าบอทเรียบร้อยแล้ว");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "บันทึกการตั้งค่าไม่สำเร็จ");
    } finally {
      setSaving(false);
    }
  };

  return (
    <form onSubmit={handleSubmit} className="mx-auto max-w-3xl space-y-5">
      <Card>
        <CardHeader>
          <CardTitle>บุคลิกและข้อความของบอท</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid gap-4 sm:grid-cols-2">
            <div>
              <label className="mb-1 block text-xs font-medium text-slate-700">ชื่อร้านค้า</label>
              <Input
                required
                value={form.shop_name}
                onChange={(e) => setForm({ ...form, shop_name: e.target.value })}
              />
            </div>
            <div>
              <label className="mb-1 block text-xs font-medium text-slate-700">น้ำเสียง / คำลงท้าย</label>
              <Input
                required
                value={form.tone}
                onChange={(e) => setForm({ ...form, tone: e.target.value })}
              />
            </div>
          </div>
          <div>
            <label className="mb-1 block text-xs font-medium text-slate-700">ข้อความทักทาย</label>
            <Textarea
              rows={2}
              required
              value={form.greeting}
              onChange={(e) => setForm({ ...form, greeting: e.target.value })}
            />
          </div>
          <div>
            <label className="mb-1 block text-xs font-medium text-slate-700">
              ข้อความเมื่อส่งต่อแอดมิน (Fallback Message)
            </label>
            <Textarea
              rows={2}
              required
              value={form.fallback_message}
              onChange={(e) => setForm({ ...form, fallback_message: e.target.value })}
            />
          </div>
          <div>
            <label className="mb-1 block text-xs font-medium text-slate-700">
              คำสั่งเพิ่มเติมให้ AI (Extra Instructions)
            </label>
            <Textarea
              rows={3}
              value={form.extra_instructions}
              onChange={(e) => setForm({ ...form, extra_instructions: e.target.value })}
            />
          </div>
          <label className="flex items-center gap-2 text-sm text-slate-700">
            <input
              type="checkbox"
              checked={form.show_citations_to_customer}
              onChange={(e) =>
                setForm({ ...form, show_citations_to_customer: e.target.checked })
              }
            />
            <span>แสดงแหล่งอ้างอิงเอกสารท้ายคำตอบให้ลูกค้าเห็น</span>
          </label>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>การส่งต่อแอดมินและคืนแชทอัตโนมัติ</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div>
            <label className="mb-1 block text-xs font-medium text-slate-700">
              คำสำคัญส่งต่อแอดมิน (คั่นด้วยจุลภาค ,)
            </label>
            <Input value={keywordsText} onChange={(e) => setKeywordsText(e.target.value)} />
          </div>
          <div className="grid gap-4 sm:grid-cols-2">
            <div>
              <label className="mb-1 block text-xs font-medium text-slate-700">
                LINE Group / User ID แจ้งเตือนแอดมิน (ถ้ามี)
              </label>
              <Input
                placeholder="เช่น C1234567890abcdef"
                value={form.handoff_notify_target_id || ""}
                onChange={(e) =>
                  setForm({ ...form, handoff_notify_target_id: e.target.value || null })
                }
              />
            </div>
            <div>
              <label className="mb-1 block text-xs font-medium text-slate-700">
                คืนแชทให้บอทอัตโนมัติหลังแอดมินเงียบ (ชั่วโมง, 0 = ปิด)
              </label>
              <Input
                type="number"
                min={0}
                max={720}
                value={form.auto_return_hours}
                onChange={(e) =>
                  setForm({ ...form, auto_return_hours: Number(e.target.value) || 0 })
                }
              />
            </div>
          </div>
        </CardContent>
      </Card>

      {message ? (
        <div className="rounded-lg border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-800">
          {message}
        </div>
      ) : null}
      {error ? (
        <div className="rounded-lg border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">
          {error}
        </div>
      ) : null}

      <Button type="submit" disabled={saving}>
        <Save className="h-4 w-4" />
        <span>{saving ? "กำลังบันทึก..." : "บันทึกการตั้งค่า"}</span>
      </Button>
    </form>
  );
}

export default function BotSettingsPage() {
  return (
    <DashboardShell
      title="ตั้งค่าบอท (Bot Settings)"
      subtitle="กำหนดชื่อร้าน น้ำเสียง คีย์เวิร์ดส่งต่อแอดมิน และเวลาคืนแชทอัตโนมัติ"
    >
      {() => <BotSettingsContent />}
    </DashboardShell>
  );
}
