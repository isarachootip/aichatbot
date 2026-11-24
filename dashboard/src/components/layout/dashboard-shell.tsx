"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import {
  BarChart3,
  BookOpen,
  Bot,
  CreditCard,
  Inbox,
  LogOut,
  MessageSquareCode,
  Rocket,
  Share2,
  Users,
} from "lucide-react";
import { apiFetch } from "@/lib/api";
import { clearAccessToken, getAccessToken } from "@/lib/auth";
import type { MeResponse, UserRole } from "@/lib/types";
import { cn } from "@/lib/utils";
import { TrialBanner } from "@/components/layout/trial-banner";

interface NavItem {
  href: string;
  label: string;
  icon: React.ComponentType<{ className?: string }>;
  roles: UserRole[];
}

const NAV_ITEMS: NavItem[] = [
  { href: "/onboarding", label: "เริ่มต้นใช้งาน", icon: Rocket, roles: ["owner", "admin"] },
  { href: "/inbox", label: "กล่องข้อความ", icon: Inbox, roles: ["owner", "admin", "agent"] },
  { href: "/knowledge", label: "คลังความรู้", icon: BookOpen, roles: ["owner", "admin"] },
  { href: "/channels", label: "ช่องทาง LINE OA", icon: Share2, roles: ["owner", "admin"] },
  { href: "/playground", label: "ทดสอบบอท", icon: MessageSquareCode, roles: ["owner", "admin"] },
  { href: "/settings/bot", label: "ตั้งค่าบอท", icon: Bot, roles: ["owner", "admin"] },
  { href: "/analytics", label: "สถิติและรายงาน", icon: BarChart3, roles: ["owner", "admin"] },
  { href: "/team", label: "ทีมงาน", icon: Users, roles: ["owner"] },
  { href: "/billing", label: "แพ็กเกจและการเงิน", icon: CreditCard, roles: ["owner", "admin"] },
];

interface DashboardShellProps {
  title: string;
  subtitle?: string;
  children: (me: MeResponse) => React.ReactNode;
}

export function DashboardShell({ title, subtitle, children }: DashboardShellProps) {
  const pathname = usePathname();
  const router = useRouter();
  const [me, setMe] = useState<MeResponse | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const token = getAccessToken();
    if (!token) {
      router.replace("/login");
      return;
    }
    let active = true;
    apiFetch<MeResponse>("/me")
      .then((profile) => {
        if (active) setMe(profile);
      })
      .catch(() => {
        if (active) router.replace("/login");
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [router]);

  const handleLogout = () => {
    clearAccessToken();
    router.replace("/login");
  };

  if (loading || !me) {
    return (
      <div className="flex min-h-screen items-center justify-center text-sm text-slate-500">
        กำลังโหลดข้อมูลร้านค้า...
      </div>
    );
  }

  const visibleNav = NAV_ITEMS.filter((item) => item.roles.includes(me.role));

  return (
    <div className="flex min-h-screen bg-slate-50">
      <aside className="flex w-64 shrink-0 flex-col border-r border-slate-200 bg-white">
        <div className="border-b border-slate-100 px-5 py-4">
          <div className="text-lg font-bold text-teal-700">ShopAI</div>
          <div className="mt-0.5 truncate text-xs font-medium text-slate-700">{me.shop_name}</div>
          <div className="truncate text-xs text-slate-400">
            {me.email} ({me.role})
          </div>
        </div>
        <nav className="flex-1 space-y-1 p-3">
          {visibleNav.map((item) => {
            const Icon = item.icon;
            const isActive = pathname === item.href;
            return (
              <Link
                key={item.href}
                href={item.href}
                className={cn(
                  "flex items-center gap-2.5 rounded-lg px-3 py-2 text-sm font-medium transition-colors",
                  isActive
                    ? "bg-teal-50 text-teal-800"
                    : "text-slate-600 hover:bg-slate-100 hover:text-slate-900",
                )}
              >
                <Icon className="h-4 w-4 shrink-0" />
                <span>{item.label}</span>
              </Link>
            );
          })}
        </nav>
        <div className="border-t border-slate-100 p-3">
          <button
            type="button"
            onClick={handleLogout}
            className="flex w-full cursor-pointer items-center gap-2 rounded-lg px-3 py-2 text-sm text-slate-600 hover:bg-slate-100"
          >
            <LogOut className="h-4 w-4" />
            <span>ออกจากระบบ</span>
          </button>
        </div>
      </aside>
      <div className="flex min-w-0 flex-1 flex-col">
        <TrialBanner me={me} />
        <header className="border-b border-slate-200 bg-white px-6 py-4">
          <h1 className="text-xl font-semibold text-slate-900">{title}</h1>
          {subtitle ? <p className="mt-0.5 text-sm text-slate-500">{subtitle}</p> : null}
        </header>
        <main className="flex-1 p-6">{children(me)}</main>
      </div>
    </div>
  );
}
