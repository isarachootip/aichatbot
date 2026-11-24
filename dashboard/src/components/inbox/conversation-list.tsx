"use client";

import type { ConversationMode, ConversationSummary } from "@/lib/types";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";

interface ConversationListProps {
  items: ConversationSummary[];
  selectedId: string | null;
  filter: "all" | ConversationMode;
  onFilterChange: (mode: "all" | ConversationMode) => void;
  onSelect: (id: string) => void;
}

export function ConversationList({
  items,
  selectedId,
  filter,
  onFilterChange,
  onSelect,
}: ConversationListProps) {
  return (
    <div className="flex h-full flex-col border-r border-slate-200 bg-white">
      <div className="flex gap-1 border-b border-slate-100 p-3">
        {(["all", "human", "bot"] as const).map((tab) => (
          <button
            key={tab}
            type="button"
            onClick={() => onFilterChange(tab)}
            className={cn(
              "flex-1 cursor-pointer rounded-md px-2 py-1.5 text-xs font-medium",
              filter === tab ? "bg-teal-700 text-white" : "bg-slate-100 text-slate-600",
            )}
          >
            {tab === "all" ? "ทั้งหมด" : tab === "human" ? "รอแอดมิน" : "บอทดูแล"}
          </button>
        ))}
      </div>
      <div className="flex-1 divide-y divide-slate-100 overflow-y-auto">
        {items.length === 0 ? (
          <div className="p-5 text-center text-xs text-slate-400">ยังไม่มีแชทในหมวดนี้</div>
        ) : (
          items.map((conv) => (
            <button
              key={conv.id}
              type="button"
              onClick={() => onSelect(conv.id)}
              className={cn(
                "w-full cursor-pointer px-4 py-3 text-left transition-colors hover:bg-slate-50",
                selectedId === conv.id && "bg-teal-50/70",
              )}
            >
              <div className="flex items-center justify-between gap-2">
                <span className="truncate text-sm font-semibold text-slate-900">
                  {conv.customer_name || conv.external_user_id}
                </span>
                <Badge tone={conv.mode === "human" ? "warning" : "success"}>
                  {conv.mode === "human" ? "แอดมิน" : "บอท"}
                </Badge>
              </div>
              <p className="mt-1 truncate text-xs text-slate-500">
                {conv.last_message_preview || "ไม่มีข้อความ"}
              </p>
              <div className="mt-1 text-[11px] text-slate-400">{conv.channel_name}</div>
            </button>
          ))
        )}
      </div>
    </div>
  );
}
