"use client";

import { useCallback, useEffect, useState } from "react";
import { Plug } from "lucide-react";
import { apiFetch, ApiError } from "@/lib/api";
import type { ChannelItem, ChannelTestResponse } from "@/lib/types";
import { ChannelCard } from "@/components/channels/channel-card";
import { DashboardShell } from "@/components/layout/dashboard-shell";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";

function ChannelsContent() {
  const [channels, setChannels] = useState<ChannelItem[]>([]);
  const [name, setName] = useState("");
  const [token, setToken] = useState("");
  const [secret, setSecret] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [copiedId, setCopiedId] = useState<string | null>(null);
  const [testResults, setTestResults] = useState<Record<string, ChannelTestResponse>>({});

  const loadChannels = useCallback(async () => {
    try {
      const res = await apiFetch<{ items: ChannelItem[] }>("/channels");
      setChannels(res.items);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "โหลดช่องทางไม่สำเร็จ");
    }
  }, []);

  useEffect(() => {
    void loadChannels();
  }, [loadChannels]);

  const handleCreate = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setSaving(true);
    try {
      await apiFetch<ChannelItem>("/channels", {
        method: "POST",
        body: JSON.stringify({
          name,
          channel_access_token: token,
          webhook_secret: secret,
        }),
      });
      setName("");
      setToken("");
      setSecret("");
      await loadChannels();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "เพิ่มช่องทางไม่สำเร็จ");
    } finally {
      setSaving(false);
    }
  };

  const handleCopy = async (id: string, url: string) => {
    await navigator.clipboard.writeText(url);
    setCopiedId(id);
    setTimeout(() => setCopiedId(null), 2000);
  };

  const handleTest = async (id: string) => {
    setError(null);
    try {
      const res = await apiFetch<ChannelTestResponse>(`/channels/${id}/test`, { method: "POST" });
      setTestResults((prev) => ({ ...prev, [id]: res }));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "ทดสอบการเชื่อมต่อไม่สำเร็จ");
    }
  };

  const handleDelete = async (id: string) => {
    await apiFetch<void>(`/channels/${id}`, { method: "DELETE" });
    await loadChannels();
  };

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader>
          <CardTitle>เชื่อมต่อ LINE Official Account ใหม่</CardTitle>
        </CardHeader>
        <CardContent>
          <form onSubmit={handleCreate} className="grid gap-4 md:grid-cols-3">
            <div>
              <label className="mb-1 block text-xs font-medium text-slate-700">ชื่อช่องทาง</label>
              <Input
                required
                placeholder="เช่น LINE ร้านหลัก"
                value={name}
                onChange={(e) => setName(e.target.value)}
              />
            </div>
            <div>
              <label className="mb-1 block text-xs font-medium text-slate-700">
                Channel Access Token
              </label>
              <Input
                required
                type="password"
                placeholder="Long-lived token จาก LINE Developers"
                value={token}
                onChange={(e) => setToken(e.target.value)}
              />
            </div>
            <div>
              <label className="mb-1 block text-xs font-medium text-slate-700">
                Channel Secret
              </label>
              <Input
                required
                type="password"
                placeholder="Channel secret สำหรับตรวจลายเซ็น"
                value={secret}
                onChange={(e) => setSecret(e.target.value)}
              />
            </div>
            <div className="md:col-span-3">
              <Button type="submit" disabled={saving}>
                <Plug className="h-4 w-4" />
                <span>{saving ? "กำลังบันทึก..." : "เชื่อมต่อ LINE OA"}</span>
              </Button>
            </div>
          </form>
        </CardContent>
      </Card>

      {error ? (
        <div className="rounded-lg border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">
          {error}
        </div>
      ) : null}

      <div className="space-y-3">
        {channels.map((ch) => (
          <ChannelCard
            key={ch.id}
            channel={ch}
            copied={copiedId === ch.id}
            testResult={testResults[ch.id]}
            onCopy={(id, url) => void handleCopy(id, url)}
            onTest={(id) => void handleTest(id)}
            onDelete={(id) => void handleDelete(id)}
          />
        ))}
        {channels.length === 0 ? (
          <Card>
            <CardContent className="text-sm text-slate-500">
              ยังไม่มีช่องทาง LINE OA ที่เชื่อมต่อไว้
            </CardContent>
          </Card>
        ) : null}
      </div>
    </div>
  );
}

export default function ChannelsPage() {
  return (
    <DashboardShell
      title="ช่องทางแชท (Channels)"
      subtitle="จัดการ LINE Official Account และคัดลอก Webhook URL ไปตั้งค่าใน LINE Developers"
    >
      {() => <ChannelsContent />}
    </DashboardShell>
  );
}
