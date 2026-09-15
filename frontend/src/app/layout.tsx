import type { Metadata } from "next";
import "./globals.css";
import { AuthProvider } from "@/lib/auth";

export const metadata: Metadata = {
  title: "引力力矩",
  description: "引力力矩 — 以三元结构理论为内核的结构化分析平台"
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="zh-CN"><body><AuthProvider>{children}</AuthProvider></body></html>;
}
