"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { RefreshCw, Upload } from "lucide-react";
import { apiFetch, apiUpload, ApiError } from "@/lib/api";
import type { DocumentItem } from "@/lib/types";
import { DocumentTable } from "@/components/knowledge/document-table";
import { DashboardShell } from "@/components/layout/dashboard-shell";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

function KnowledgeContent() {
  const [docs, setDocs] = useState<DocumentItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const reuploadTargetRef = useRef<string | null>(null);
  const reuploadInputRef = useRef<HTMLInputElement | null>(null);

  const fetchDocs = useCallback(async () => {
    try {
      const res = await apiFetch<{ items: DocumentItem[] }>("/documents");
      setDocs(res.items);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "โหลดรายการเอกสารไม่สำเร็จ");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void fetchDocs();
  }, [fetchDocs]);

  const hasPending = docs.some((d) => d.status === "pending" || d.status === "processing");
  useEffect(() => {
    if (!hasPending) return;
    const timer = setInterval(() => void fetchDocs(), 2000);
    return () => clearInterval(timer);
  }, [hasPending, fetchDocs]);

  const handleUploadFile = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setError(null);
    setUploading(true);
    try {
      await apiUpload<DocumentItem>("/documents", file);
      await fetchDocs();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "อัปโหลดไฟล์ไม่สำเร็จ");
    } finally {
      setUploading(false);
      e.target.value = "";
    }
  };

  const handleReuploadFile = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    const targetId = reuploadTargetRef.current;
    if (!file || !targetId) return;
    setError(null);
    setUploading(true);
    try {
      await apiUpload<DocumentItem>(`/documents/${targetId}/reupload`, file);
      await fetchDocs();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "อัปโหลดไฟล์ใหม่ไม่สำเร็จ");
    } finally {
      setUploading(false);
      reuploadTargetRef.current = null;
      e.target.value = "";
    }
  };

  const handleDelete = async (id: string) => {
    setError(null);
    try {
      await apiFetch<void>(`/documents/${id}`, { method: "DELETE" });
      await fetchDocs();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "ลบเอกสารไม่สำเร็จ");
    }
  };

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader>
          <CardTitle>อัปโหลดเอกสารความรู้ (PDF, DOCX, XLSX, CSV, TXT)</CardTitle>
        </CardHeader>
        <CardContent className="flex flex-wrap items-center justify-between gap-4">
          <p className="text-sm text-slate-600">
            ระบบจะตัดคำภาษาไทยและสร้างดัชนีค้นหาอัตโนมัติ ขนาดไฟล์สูงสุด 20 MB
          </p>
          <div className="flex items-center gap-2">
            <input
              ref={fileInputRef}
              data-testid="document-file-input"
              type="file"
              accept=".pdf,.docx,.xlsx,.csv,.txt"
              onChange={handleUploadFile}
              className="hidden"
            />
            <input
              ref={reuploadInputRef}
              type="file"
              accept=".pdf,.docx,.xlsx,.csv,.txt"
              onChange={handleReuploadFile}
              className="hidden"
            />
            <Button onClick={() => fileInputRef.current?.click()} disabled={uploading}>
              <Upload className="h-4 w-4" />
              <span>{uploading ? "กำลังอัปโหลด..." : "เลือกไฟล์เพื่ออัปโหลด"}</span>
            </Button>
            <Button variant="outline" onClick={() => void fetchDocs()}>
              <RefreshCw className="h-4 w-4" />
              <span>รีเฟรช</span>
            </Button>
          </div>
        </CardContent>
      </Card>

      {error ? (
        <div className="rounded-lg border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">
          {error}
        </div>
      ) : null}

      <Card>
        <CardHeader>
          <CardTitle>รายการเอกสารทั้งหมด ({docs.length})</CardTitle>
        </CardHeader>
        <CardContent className="p-0">
          {loading ? (
            <div className="p-6 text-sm text-slate-500">กำลังโหลด...</div>
          ) : (
            <DocumentTable
              docs={docs}
              onTriggerReupload={(id) => {
                reuploadTargetRef.current = id;
                reuploadInputRef.current?.click();
              }}
              onDelete={(id) => void handleDelete(id)}
            />
          )}
        </CardContent>
      </Card>
    </div>
  );
}

export default function KnowledgePage() {
  return (
    <DashboardShell
      title="คลังความรู้ (Knowledge Base)"
      subtitle="อัปโหลดไฟล์ข้อมูลร้านค้าเพื่อให้ AI ตอบคำถามลูกค้าได้อย่างแม่นยำ"
    >
      {() => <KnowledgeContent />}
    </DashboardShell>
  );
}
