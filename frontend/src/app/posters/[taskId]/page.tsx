"use client";

// 地域画报页（F-poster）：/posters/[taskId]——报告的独立海报路由。
// 从报告阅读页顶部「地域画报」按钮进入；数据与 /geo 同源。

import { useParams } from "next/navigation";
import React from "react";
import { PosterGeo } from "@/components/poster-geo";

export default function PosterPage() {
  const params = useParams<{ taskId: string }>();
  const taskId = typeof params?.taskId === "string" ? params.taskId : "";
  return <main className="poster-page">
    <PosterGeo taskId={taskId} />
  </main>;
}
