import type { Metadata } from "next";
import { Noto_Sans_Thai } from "next/font/google";
import "./globals.css";

const notoThai = Noto_Sans_Thai({
  subsets: ["thai", "latin"],
  weight: ["400", "500", "600", "700"],
  variable: "--font-noto-thai",
});

export const metadata: Metadata = {
  title: "ShopAI — ผู้ช่วยแชท AI สำหรับร้านค้าออนไลน์ไทย",
  description: "ระบบตอบแชทอัตโนมัติจากฐานความรู้ของร้านคุณ พร้อมส่งต่อแอดมินอัจฉริยะ",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="th" className={notoThai.variable}>
      <body className="min-h-screen antialiased">{children}</body>
    </html>
  );
}
