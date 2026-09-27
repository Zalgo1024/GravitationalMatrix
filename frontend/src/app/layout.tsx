import type { Metadata } from "next";
import "./globals.css";
import { AuthProvider } from "@/lib/auth";

export const metadata: Metadata = {
  title: "引力矩阵",
  description: "引力矩阵引擎 — 把混沌事件，拆成可检验的结构"
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="zh-CN"><body><AuthProvider>{children}</AuthProvider></body></html>;
}
