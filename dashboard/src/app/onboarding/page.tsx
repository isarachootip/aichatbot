"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { CheckCircle2, Circle, ArrowRight } from "lucide-react";
import { apiFetch } from "@/lib/api";
import type { ChannelItem, DocumentItem } from "@/lib/types";
import { DashboardShell } from "@/components/layout/dashboard-shell";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";

function OnboardingSteps() {
  const [docsCount, setDocsCount] = useState(0);
  const [readyDocs, setReadyDocs] = useState(0);
  const [channelsCount, setChannelsCount] = useState(0);

  useEffect(() => {
    apiFetch<{ items: DocumentItem[] }>("/documents")
      .then((res) => {
        setDocsCount(res.items.length);
        setReadyDocs(res.items.filter((d) => d.status === "ready").length);
      })
      .catch(() => {});
    apiFetch<{ items: ChannelItem[] }>("/channels")
      .then((res) => setChannelsCount(res.items.length))
      .catch(() => {});
  }, []);

  const steps = [
    {
      num: 1,
      title: "อัปโหลดเอกสารความรู้ของร้าน",
      desc: "รองรับ PDF, DOCX, XLSX, CSV, TXT เช่น นโยบายร้าน ราคาสินค้า ค่าจัดส่ง",
      done: readyDocs > 0,
      statusText:
        readyDocs > 0
          ? `พร้อมใช้งานแล้ว ${readyDocs} ไฟล์`
          : docsCount > 0
            ? `กำลังประมวลผล ${docsCount} ไฟล์`
            : "ยังไม่มีเอกสาร",
      href: "/knowledge",
      cta: "ไปที่คลังความรู้",
    },
    {
      num: 2,
      title: "เชื่อมต่อ LINE Official Account",
      desc: "ใส่ Channel Access Token และ Channel Secret แล้วนำ Webhook URL ไปวางใน LINE Developers",
      done: channelsCount > 0,
      statusText: channelsCount > 0 ? `เชื่อมต่อแล้ว ${channelsCount} ช่องทาง` : "ยังไม่ได้เชื่อมต่อ",
      href: "/channels",
      cta: "เชื่อมต่อ LINE OA",
    },
    {
      num: 3,
      title: "ทดสอบถาม-ตอบบอทใน Playground",
      desc: "ลองพิมพ์คำถามลูกค้าเพื่อตรวจความถูกต้องและแหล่งอ้างอิง (ไม่หักโควต้าข้อความ)",
      done: false,
      statusText: "ทดสอบได้ไม่จำกัด",
      href: "/playground",
      cta: "เปิด Playground",
    },
  ];

  return (
    <div className="mx-auto max-w-3xl space-y-4">
      {steps.map((step) => (
        <Card key={step.num}>
          <CardContent className="flex flex-col justify-between gap-4 sm:flex-row sm:items-center">
            <div className="flex items-start gap-3">
              {step.done ? (
                <CheckCircle2 className="mt-0.5 h-6 w-6 shrink-0 text-emerald-600" />
              ) : (
                <Circle className="mt-0.5 h-6 w-6 shrink-0 text-slate-300" />
              )}
              <div>
                <div className="text-xs font-semibold text-teal-700">ขั้นตอนที่ {step.num}</div>
                <h3 className="text-base font-semibold text-slate-900">{step.title}</h3>
                <p className="mt-1 text-sm text-slate-600">{step.desc}</p>
                <p className="mt-1 text-xs font-medium text-slate-500">{step.statusText}</p>
              </div>
            </div>
            <Link href={step.href} className="shrink-0">
              <Button variant={step.done ? "outline" : "primary"}>
                <span>{step.cta}</span>
                <ArrowRight className="h-4 w-4" />
              </Button>
            </Link>
          </CardContent>
        </Card>
      ))}
    </div>
  );
}

export default function OnboardingPage() {
  return (
    <DashboardShell
      title="เริ่มต้นตั้งค่าผู้ช่วย AI ของร้านคุณ"
      subtitle="ทำตาม 3 ขั้นตอนง่าย ๆ เพื่อให้บอทพร้อมตอบแชทลูกค้าอัตโนมัติ"
    >
      {() => <OnboardingSteps />}
    </DashboardShell>
  );
}
