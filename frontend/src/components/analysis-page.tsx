"use client";

import { useRouter, useSearchParams } from "next/navigation";
import React from "react";
import { useAppStore } from "@/lib/store";
import { apiRequest } from "@/lib/api";
import type { MaterialRecord } from "@/lib/domain";
import { createAnalysisTask } from "@/lib/workspace-api";
import { AnalysisCreation } from "./analysis-creation";

export function AnalysisPage() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const { state, refreshWorkspace } = useAppStore();
  const reportId = searchParams.get("reportId");
  const purpose = searchParams.get("purpose");
  const sourceReport = state.reports.find((report) => report.id === reportId);
  const purposeCopy: Record<string, string> = {
    continue: "继续分析这份报告中的关键问题：",
    evidence: "请为这份报告补充可复核的证据与来源：",
    review: "请审阅这份报告中的结论、假设与待验证之处：",
    rewrite: "请基于这份报告重组表达，并保留事实与推断的边界：",
  };
  const initialPrompt = sourceReport ? `${purposeCopy[purpose ?? "continue"] ?? purposeCopy.continue}\n报告：${sourceReport.title}\n` : "";

  async function create(input: Parameters<NonNullable<React.ComponentProps<typeof AnalysisCreation>["onCreate"]>>[0]) {
    // 分析skill 后端：POST /api/analyze 自动建任务并后台运行（无需 codex 的 research/run 分步）。
    const result = await createAnalysisTask(input);
    window.location.assign(`/analysis/${result.task_id}?autorun=1`);
  }

  async function upload(files: File[]) {
    const responses = await Promise.all(files.map(async (file) => {
      const body = new FormData();
      body.append("file", file);
      const result = await apiRequest<{ id: string; title: string; source_type: string; source: string | null; warnings?: string[]; created_at: string | null }>("/api/materials/upload", { method: "POST", body });
      const kind: MaterialRecord["kind"] = result.source_type === "link" ? "link" : result.source_type === "note" ? "note" : "file";
      const warnings = result.warnings ?? [];
      return {
        id: result.id,
        name: result.title,
        kind,
        note: warnings.length ? `解析告警：${warnings.join("、")}` : result.source ?? "",
        updatedAt: result.created_at ?? new Date().toISOString(),
        status: warnings.length ? "error" as const : "ready" as const,
      };
    }));
    await refreshWorkspace();
    return responses;
  }

  return (
    <AnalysisCreation
      materials={state.materials}
      projects={state.projects}
      defaultEngine={state.settings.defaultEngine}
      initialType={sourceReport?.type}
      initialPrompt={initialPrompt}
      reportTitle={sourceReport?.title}
      onCreate={create}
      onUpload={upload}
    />
  );
}
