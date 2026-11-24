"use client";

import { Trash2 } from "lucide-react";
import type { DocumentItem, DocumentStatus } from "@/lib/types";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";

const STATUS_BADGE: Record<
  DocumentStatus,
  { label: string; tone: "neutral" | "info" | "success" | "danger" }
> = {
  pending: { label: "รอคิวประมวลผล", tone: "neutral" },
  processing: { label: "กำลังอ่านไฟล์", tone: "info" },
  ready: { label: "พร้อมใช้งาน", tone: "success" },
  failed: { label: "ล้มเหลว", tone: "danger" },
};

interface DocumentTableProps {
  docs: DocumentItem[];
  onTriggerReupload: (id: string) => void;
  onDelete: (id: string) => void;
}

export function DocumentTable({ docs, onTriggerReupload, onDelete }: DocumentTableProps) {
  if (docs.length === 0) {
    return (
      <div className="p-6 text-sm text-slate-500">
        ยังไม่มีเอกสารในคลังความรู้ เริ่มอัปโหลดไฟล์แรกของร้านได้เลย
      </div>
    );
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-left text-sm">
        <thead className="border-b border-slate-100 bg-slate-50 text-xs text-slate-500">
          <tr>
            <th className="px-5 py-3">ชื่อไฟล์</th>
            <th className="px-5 py-3">สถานะ</th>
            <th className="px-5 py-3">จำนวนชิ้นข้อความ</th>
            <th className="px-5 py-3 text-right">จัดการ</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100">
          {docs.map((doc) => {
            const st = STATUS_BADGE[doc.status];
            return (
              <tr key={doc.id} data-testid="document-row">
                <td className="px-5 py-3 font-medium text-slate-900">
                  <div>{doc.filename}</div>
                  {doc.error ? <div className="mt-0.5 text-xs text-rose-600">{doc.error}</div> : null}
                </td>
                <td className="px-5 py-3">
                  <Badge tone={st.tone} data-testid="document-status">
                    {st.label}
                  </Badge>
                </td>
                <td className="px-5 py-3 text-slate-600">{doc.chunk_count}</td>
                <td className="px-5 py-3 text-right">
                  <div className="inline-flex gap-2">
                    <Button size="sm" variant="outline" onClick={() => onTriggerReupload(doc.id)}>
                      อัปโหลดทับ
                    </Button>
                    <Button size="sm" variant="ghost" onClick={() => onDelete(doc.id)}>
                      <Trash2 className="h-4 w-4 text-rose-600" />
                    </Button>
                  </div>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
