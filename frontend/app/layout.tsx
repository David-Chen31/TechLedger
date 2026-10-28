import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "TechLedger · 技术决策账本",
  description: "有证据、能复核的技术选型工作台",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="zh-CN">
      <body>{children}</body>
    </html>
  );
}
