"use client";

import { Check, Copy, Trash2 } from "lucide-react";
import type { ChannelItem, ChannelTestResponse } from "@/lib/types";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";

interface ChannelCardProps {
  channel: ChannelItem;
  copied: boolean;
  testResult?: ChannelTestResponse;
  onCopy: (id: string, url: string) => void;
  onTest: (id: string) => void;
  onDelete: (id: string) => void;
}

export function ChannelCard({
  channel,
  copied,
  testResult,
  onCopy,
  onTest,
  onDelete,
}: ChannelCardProps) {
  return (
    <Card>
      <CardContent className="space-y-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div className="flex items-center gap-2">
            <span className="font-semibold text-slate-900">{channel.name}</span>
            <Badge tone="info">{channel.type.toUpperCase()}</Badge>
            <Badge tone={channel.active ? "success" : "neutral"}>
              {channel.active ? "เปิดใช้งาน" : "ปิดใช้งาน"}
            </Badge>
          </div>
          <div className="flex items-center gap-2">
            <Button size="sm" variant="outline" onClick={() => onTest(channel.id)}>
              ทดสอบการเชื่อมต่อ
            </Button>
            <Button size="sm" variant="ghost" onClick={() => onDelete(channel.id)}>
              <Trash2 className="h-4 w-4 text-rose-600" />
            </Button>
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-2 rounded-lg bg-slate-50 p-3 text-xs">
          <span className="font-medium text-slate-500">Webhook URL:</span>
          <code className="flex-1 break-all text-slate-800">{channel.webhook_url}</code>
          <Button size="sm" variant="outline" onClick={() => onCopy(channel.id, channel.webhook_url)}>
            {copied ? <Check className="h-3.5 w-3.5" /> : <Copy className="h-3.5 w-3.5" />}
            <span>{copied ? "คัดลอกแล้ว" : "คัดลอก"}</span>
          </Button>
        </div>
        {testResult ? (
          <div
            className={
              testResult.ok
                ? "rounded-lg bg-emerald-50 px-3 py-2 text-xs text-emerald-800"
                : "rounded-lg bg-rose-50 px-3 py-2 text-xs text-rose-700"
            }
          >
            {testResult.ok
              ? `เชื่อมต่อสำเร็จ: ${testResult.bot_name || "LINE Bot"} (${testResult.basic_id || "-"})`
              : `เชื่อมต่อไม่สำเร็จ: ${testResult.error || "Unknown error"}`}
          </div>
        ) : null}
      </CardContent>
    </Card>
  );
}
