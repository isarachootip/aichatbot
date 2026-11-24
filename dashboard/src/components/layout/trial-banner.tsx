"use client";

import Link from "next/link";
import { Clock, Sparkles } from "lucide-react";
import type { MeResponse } from "@/lib/types";

interface TrialBannerProps {
  me: MeResponse;
}

export function TrialBanner({ me }: TrialBannerProps) {
  if (me.status === "active") {
    return null;
  }
  const expired = me.status === "trial_expired" || me.trial_days_remaining <= 0;

  return (
    <div
      data-testid="trial-banner"
      className={
        expired
          ? "flex flex-wrap items-center justify-between gap-2 border-b border-rose-200 bg-rose-50 px-6 py-2.5 text-sm text-rose-900"
          : "flex flex-wrap items-center justify-between gap-2 border-b border-amber-200 bg-amber-50 px-6 py-2.5 text-sm text-amber-950"
      }
    >
      <div className="flex items-center gap-2">
        {expired ? <Clock className="h-4 w-4 shrink-0" /> : <Sparkles className="h-4 w-4 shrink-0" />}
        <span>
          {expired ? (
            <strong>ช่วงทดลองใช้งาน 7 วันหมดอายุแล้ว</strong>
          ) : (
            <>
              ทดลองใช้งานฟรี เหลืออีก{" "}
              <strong>{me.trial_days_remaining} วัน</strong> ({me.used_messages}/
              {me.limit_messages} ข้อความเดือนนี้)
            </>
          )}
        </span>
      </div>
      <Link
        href="/billing"
        className="rounded-md bg-slate-900 px-3 py-1 text-xs font-medium text-white hover:bg-slate-800"
      >
        ดูแพ็กเกจ
      </Link>
    </div>
  );
}
