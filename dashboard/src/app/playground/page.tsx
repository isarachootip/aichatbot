"use client";

import { useState } from "react";
import { Send, FileText, AlertTriangle } from "lucide-react";
import { apiFetch, ApiError } from "@/lib/api";
import type { PlaygroundAskResponse, PlaygroundSource } from "@/lib/types";
import { DashboardShell } from "@/components/layout/dashboard-shell";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";

interface Turn {
  id: string;
  role: "user" | "bot";
  text: string;
  sources?: PlaygroundSource[];
  handoff?: boolean;
  meta?: string;
}

function PlaygroundContent() {
  const [turns, setTurns] = useState<Turn[]>([]);
  const [question, setQuestion] = useState("");
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleAsk = async (e: React.FormEvent) => {
    e.preventDefault();
    const q = question.trim();
    if (!q || sending) return;

    setError(null);
    setQuestion("");
    setTurns((prev) => [...prev, { id: `u-${Date.now()}`, role: "user", text: q }]);
    setSending(true);

    try {
      const res = await apiFetch<PlaygroundAskResponse>("/playground/ask", {
        method: "POST",
        body: JSON.stringify({ question: q }),
      });
      setTurns((prev) => [
        ...prev,
        {
          id: `b-${Date.now()}`,
          role: "bot",
          text: res.answer,
          sources: res.sources,
          handoff: res.handoff,
          meta: `${res.model} • in:${res.input_tokens} / out:${res.output_tokens} tokens`,
        },
      ]);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "เรียกคำตอบจากบอทไม่สำเร็จ");
    } finally {
      setSending(false);
    }
  };

  return (
    <div className="mx-auto flex max-w-3xl flex-col gap-4">
      <div className="flex items-center justify-between rounded-lg border border-teal-200 bg-teal-50 px-4 py-2.5 text-xs text-teal-900">
        <span>โหมดทดสอบ Playground ใช้ฐานความรู้จริงของร้านคุณและไม่หักโควต้าข้อความรายเดือน</span>
        <Badge tone="info">ฟรี ไม่หักโควต้า</Badge>
      </div>

      <Card className="flex min-h-[420px] flex-col">
        <CardContent className="flex-1 space-y-4 overflow-y-auto p-5">
          {turns.length === 0 ? (
            <div className="py-16 text-center text-sm text-slate-400">
              ลองพิมพ์คำถามลูกค้า เช่น &quot;ค่าจัดส่งกี่บาทคะ&quot; หรือ &quot;นโยบายคืนสินค้าเป็นอย่างไร&quot;
            </div>
          ) : (
            turns.map((turn) => (
              <div
                key={turn.id}
                className={turn.role === "user" ? "flex justify-end" : "flex justify-start"}
              >
                <div
                  data-testid={turn.role === "bot" ? "playground-bot-reply" : "playground-user-msg"}
                  className={
                    turn.role === "user"
                      ? "max-w-[80%] rounded-2xl bg-teal-700 px-4 py-2.5 text-sm text-white"
                      : "max-w-[85%] space-y-2 rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3 text-sm text-slate-900"
                  }
                >
                  <p className="whitespace-pre-wrap">{turn.text}</p>
                  {turn.handoff ? (
                    <div className="flex items-center gap-1.5 text-xs font-medium text-amber-700">
                      <AlertTriangle className="h-3.5 w-3.5" />
                      <span>ระบบแนะนำให้ส่งต่อแอดมิน (Handoff)</span>
                    </div>
                  ) : null}
                  {turn.sources && turn.sources.length > 0 ? (
                    <div className="flex flex-wrap gap-1.5 pt-1">
                      {turn.sources.map((src, idx) => (
                        <Badge key={`${src.document_id}-${idx}`} tone="neutral">
                          <FileText className="mr-1 h-3 w-3" />
                          {src.filename} (หน้า {src.page})
                        </Badge>
                      ))}
                    </div>
                  ) : null}
                  {turn.meta ? <div className="text-[11px] text-slate-400">{turn.meta}</div> : null}
                </div>
              </div>
            ))
          )}
        </CardContent>
        <form onSubmit={handleAsk} className="flex gap-2 border-t border-slate-100 p-4">
          <Input
            data-testid="playground-input"
            placeholder="พิมพ์คำถามลูกค้าเพื่อทดสอบบอท..."
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            disabled={sending}
          />
          <Button type="submit" data-testid="playground-submit" disabled={sending || !question.trim()}>
            <Send className="h-4 w-4" />
            <span>{sending ? "กำลังคิด..." : "ส่งคำถาม"}</span>
          </Button>
        </form>
      </Card>

      {error ? (
        <div className="rounded-lg border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">
          {error}
        </div>
      ) : null}
    </div>
  );
}

export default function PlaygroundPage() {
  return (
    <DashboardShell
      title="ทดสอบบอท (Playground)"
      subtitle="จำลองการถาม-ตอบกับ AI จากไฟล์เอกสารที่คุณอัปโหลด พร้อมแสดงแหล่งอ้างอิง"
    >
      {() => <PlaygroundContent />}
    </DashboardShell>
  );
}
