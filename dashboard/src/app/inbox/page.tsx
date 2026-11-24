"use client";

import { useCallback, useEffect, useState } from "react";
import { apiFetch, ApiError } from "@/lib/api";
import type {
  ConversationMessagesResponse,
  ConversationMode,
  ConversationSummary,
} from "@/lib/types";
import { DashboardShell } from "@/components/layout/dashboard-shell";
import { ChatPane } from "@/components/inbox/chat-pane";
import { ConversationList } from "@/components/inbox/conversation-list";

function InboxContent() {
  const [filter, setFilter] = useState<"all" | ConversationMode>("all");
  const [items, setItems] = useState<ConversationSummary[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [thread, setThread] = useState<ConversationMessagesResponse | null>(null);
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadList = useCallback(async () => {
    const query = filter === "all" ? "" : `?mode=${filter}`;
    const res = await apiFetch<{ items: ConversationSummary[] }>(`/conversations${query}`);
    setItems(res.items);
  }, [filter]);

  const loadThread = useCallback(async (convId: string) => {
    const res = await apiFetch<ConversationMessagesResponse>(`/conversations/${convId}/messages`);
    setThread(res);
  }, []);

  useEffect(() => {
    void loadList().catch(() => {});
    const timer = setInterval(() => void loadList().catch(() => {}), 5000);
    return () => clearInterval(timer);
  }, [loadList]);

  useEffect(() => {
    if (!selectedId) {
      setThread(null);
      return;
    }
    void loadThread(selectedId).catch(() => {});
    const timer = setInterval(() => void loadThread(selectedId).catch(() => {}), 5000);
    return () => clearInterval(timer);
  }, [selectedId, loadThread]);

  const handleSendReply = async (content: string) => {
    if (!selectedId) return;
    setError(null);
    setSending(true);
    try {
      await apiFetch(`/conversations/${selectedId}/messages`, {
        method: "POST",
        body: JSON.stringify({ content }),
      });
      await Promise.all([loadThread(selectedId), loadList()]);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "ส่งข้อความไม่สำเร็จ");
    } finally {
      setSending(false);
    }
  };

  const handleToggleMode = async (targetMode: ConversationMode) => {
    if (!selectedId) return;
    setError(null);
    try {
      await apiFetch(`/conversations/${selectedId}/mode`, {
        method: "PATCH",
        body: JSON.stringify({ mode: targetMode }),
      });
      await Promise.all([loadThread(selectedId), loadList()]);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "สลับโหมดแชทไม่สำเร็จ");
    }
  };

  return (
    <div className="space-y-3">
      {error ? (
        <div className="rounded-lg border border-rose-200 bg-rose-50 px-4 py-2 text-sm text-rose-700">
          {error}
        </div>
      ) : null}
      <div className="grid h-[calc(100vh-230px)] min-h-[480px] overflow-hidden rounded-xl border border-slate-200 bg-white md:grid-cols-[320px_1fr]">
        <ConversationList
          items={items}
          selectedId={selectedId}
          filter={filter}
          onFilterChange={setFilter}
          onSelect={setSelectedId}
        />
        <ChatPane
          thread={thread}
          sending={sending}
          onSendReply={handleSendReply}
          onToggleMode={handleToggleMode}
        />
      </div>
    </div>
  );
}

export default function InboxPage() {
  return (
    <DashboardShell
      title="กล่องข้อความ (Inbox)"
      subtitle="อัปเดตอัตโนมัติทุก 5 วินาที — แอดมินรับช่วงต่อและคืนแชทให้บอทได้ทันที"
    >
      {() => <InboxContent />}
    </DashboardShell>
  );
}
