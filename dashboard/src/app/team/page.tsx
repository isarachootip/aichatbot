"use client";

import { useCallback, useEffect, useState } from "react";
import { Trash2, UserPlus } from "lucide-react";
import { apiFetch, ApiError } from "@/lib/api";
import type { MeResponse, TeamMember, UserRole } from "@/lib/types";
import { DashboardShell } from "@/components/layout/dashboard-shell";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";

function TeamContent({ me }: { me: MeResponse }) {
  const [members, setMembers] = useState<TeamMember[]>([]);
  const [email, setEmail] = useState("");
  const [role, setRole] = useState<UserRole>("agent");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadMembers = useCallback(async () => {
    try {
      const res = await apiFetch<{ items: TeamMember[] }>("/team/users");
      setMembers(res.items);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "โหลดรายชื่อทีมงานไม่สำเร็จ");
    }
  }, []);

  useEffect(() => {
    void loadMembers();
  }, [loadMembers]);

  const handleInvite = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setSaving(true);
    try {
      await apiFetch<TeamMember>("/team/invite", {
        method: "POST",
        body: JSON.stringify({ email, role }),
      });
      setEmail("");
      await loadMembers();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "เชิญสมาชิกไม่สำเร็จ");
    } finally {
      setSaving(false);
    }
  };

  const handleRoleChange = async (memberId: string, nextRole: UserRole) => {
    setError(null);
    try {
      await apiFetch<TeamMember>(`/team/users/${memberId}/role`, {
        method: "PATCH",
        body: JSON.stringify({ role: nextRole }),
      });
      await loadMembers();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "เปลี่ยนสิทธิ์ไม่สำเร็จ");
    }
  };

  const handleRemove = async (memberId: string) => {
    setError(null);
    try {
      await apiFetch<void>(`/team/users/${memberId}`, { method: "DELETE" });
      await loadMembers();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "ลบสมาชิกไม่สำเร็จ");
    }
  };

  return (
    <div className="mx-auto max-w-3xl space-y-6">
      <Card>
        <CardHeader>
          <CardTitle>เชิญสมาชิกเข้าทีม</CardTitle>
        </CardHeader>
        <CardContent>
          <form onSubmit={handleInvite} className="flex flex-wrap gap-3">
            <Input
              className="min-w-[220px] flex-1"
              type="email"
              required
              placeholder="agent@yourshop.th"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
            />
            <select
              value={role}
              onChange={(e) => setRole(e.target.value as UserRole)}
              className="h-10 rounded-lg border border-slate-300 bg-white px-3 text-sm text-slate-900"
            >
              <option value="agent">Agent (ดูและตอบ Inbox)</option>
              <option value="admin">Admin (จัดการบอทและเอกสาร)</option>
              <option value="owner">Owner (สิทธิ์เต็มรูปแบบ)</option>
            </select>
            <Button type="submit" disabled={saving}>
              <UserPlus className="h-4 w-4" />
              <span>{saving ? "กำลังเพิ่ม..." : "เชิญสมาชิก"}</span>
            </Button>
          </form>
        </CardContent>
      </Card>

      {error ? (
        <div className="rounded-lg border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">
          {error}
        </div>
      ) : null}

      <Card>
        <CardHeader>
          <CardTitle>สมาชิกในร้าน ({members.length})</CardTitle>
        </CardHeader>
        <CardContent className="divide-y divide-slate-100 p-0">
          {members.map((m) => (
            <div key={m.id} className="flex flex-wrap items-center justify-between gap-3 px-5 py-3.5">
              <div>
                <div className="text-sm font-medium text-slate-900">
                  {m.email}{" "}
                  {m.id === me.user_id ? <Badge tone="info">คุณ</Badge> : null}
                </div>
                <div className="text-xs text-slate-400">สิทธิ์ปัจจุบัน: {m.role}</div>
              </div>
              <div className="flex items-center gap-2">
                <select
                  value={m.role}
                  onChange={(e) => void handleRoleChange(m.id, e.target.value as UserRole)}
                  className="h-8 rounded-md border border-slate-300 bg-white px-2 text-xs"
                >
                  <option value="agent">agent</option>
                  <option value="admin">admin</option>
                  <option value="owner">owner</option>
                </select>
                {m.id !== me.user_id ? (
                  <Button size="sm" variant="ghost" onClick={() => void handleRemove(m.id)}>
                    <Trash2 className="h-4 w-4 text-rose-600" />
                  </Button>
                ) : null}
              </div>
            </div>
          ))}
        </CardContent>
      </Card>
    </div>
  );
}

export default function TeamPage() {
  return (
    <DashboardShell
      title="จัดการทีมงาน (Team & RBAC)"
      subtitle="กำหนดสิทธิ์การเข้าถึงสำหรับแอดมินและพนักงานตอบแชท"
    >
      {(me) => <TeamContent me={me} />}
    </DashboardShell>
  );
}
