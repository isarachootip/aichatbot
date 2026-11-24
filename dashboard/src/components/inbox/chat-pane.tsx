"use client";

import { useState } from "react";
import { Bot, Send, UserRound } from "lucide-react";
import type { ConversationMessagesResponse } from "@/lib/types";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

interface ChatPaneProps {
  thread: ConversationMessagesResponse | null;
  sending: boolean;
  onSendReply: (content: string) => Promise<void>;
  onToggleMode: (targetMode: "bot" | "human") => Promise<void>;
}

export function ChatPane({ thread, sending, onSendReply, onToggleMode }: ChatPaneProps) {
  const [reply, setReply] = useState("");

  if (!thread) {
    return (
      <div className="flex h-full items-center justify-center text-sm text-slate-400">
        เลือกห้องแชทจากแถบซ้ายเพื่อดูข้อความและตอบลูกค้า
      </div>
    );
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    const content = reply.trim();
    if (!content) return;
    setReply("");
    await onSendReply(content);
  };

  return (
    <div className="flex h-full flex-col bg-slate-50">
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-slate-200 bg-white px-5 py-3">
        <div>
          <div className="font-semibold text-slate-900">
            {thread.customer_name || thread.external_user_id}
          </div>
          <div className="text-xs text-slate-400">ID: {thread.external_user_id}</div>
        </div>
        <div className="flex items-center gap-2">
          <Badge tone={thread.mode === "human" ? "warning" : "success"}>
            {thread.mode === "human" ? "โหมดแอดมิน (บอทเงียบ)" : "โหมดบอทอัตโนมัติ"}
          </Badge>
          {thread.mode === "human" ? (
            <Button size="sm" variant="primary" onClick={() => void onToggleMode("bot")}>
              <Bot className="h-3.5 w-3.5" />
              <span>คืนแชทให้บอท</span>
            </Button>
          ) : (
            <Button size="sm" variant="outline" onClick={() => void onToggleMode("human")}>
              <UserRound className="h-3.5 w-3.5" />
              <span>แอดมินรับช่วงต่อ</span>
            </Button>
          )}
        </div>
      </div>

      <div className="flex-1 space-y-3 overflow-y-auto p-5">
        {thread.items.map((msg) => {
          const isCustomer = msg.role === "customer";
          return (
            <div key={msg.id} className={isCustomer ? "flex justify-start" : "flex justify-end"}>
              <div
                className={
                  isCustomer
                    ? "max-w-[75%] rounded-2xl border border-slate-200 bg-white px-4 py-2.5 text-sm text-slate-900"
                    : msg.role === "agent"
                      ? "max-w-[75%] rounded-2xl bg-slate-900 px-4 py-2.5 text-sm text-white"
                      : "max-w-[75%] rounded-2xl bg-teal-700 px-4 py-2.5 text-sm text-white"
                }
              >
                <div className="mb-1 text-[10px] opacity-75">
                  {msg.role === "customer" ? "ลูกค้า" : msg.role === "agent" ? "แอดมิน" : "AI บอท"}
                </div>
                <p className="whitespace-pre-wrap">{msg.content}</p>
              </div>
            </div>
          );
        })}
      </div>

      <form onSubmit={handleSubmit} className="flex gap-2 border-t border-slate-200 bg-white p-4">
        <Input
          placeholder="พิมพ์ข้อความตอบกลับลูกค้าในฐานะแอดมิน..."
          value={reply}
          onChange={(e) => setReply(e.target.value)}
          disabled={sending}
        />
        <Button type="submit" disabled={sending || !reply.trim()}>
          <Send className="h-4 w-4" />
          <span>ส่งข้อความ</span>
        </Button>
      </form>
    </div>
  );
}
