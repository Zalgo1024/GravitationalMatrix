import { describe, expect, it, vi } from "vitest";
import type { AnalysisTask } from "./domain";
import { createAnalysisTask, createReportEnrichment, fetchCurrentReport, fetchProjectMonitor, fetchWorkspaceSnapshot, runProjectMonitor, updateProjectMonitor } from "./workspace-api";

const task: AnalysisTask = {
  id: "task-1",
  projectId: "project-1",
  type: "org",
  title: "真实组织分析",
  context: "",
  engine: "llm",
  materialIds: ["material-1"],
  status: "done",
  phase: "output",
  progress: 100,
  createdAt: "2026-08-01T10:00:00",
  updatedAt: "2026-08-01T10:05:00",
};

describe("fetchCurrentReport", () => {
  it("uses the backend current version as the report content", async () => {
    const request = vi.fn(async (path: string) => {
      if (path === "/api/reports/task-1") {
        return {
          task_id: "task-1",
          title: "后端报告标题",
          current_version_id: "version-2",
          versions: [
            { id: "version-1", version_no: 1, created_at: "2026-08-01T10:05:00", is_current: false },
            { id: "version-2", version_no: 2, created_at: "2026-08-01T11:00:00", is_current: true },
          ],
        };
      }
      if (path === "/api/reports/task-1/versions/version-2") {
        return {
          id: "version-2",
          version_no: 2,
          created_at: "2026-08-01T11:00:00",
          content_markdown: "# 后端当前版本\n\n## 结论\n\n真实内容",
          research_status: "verified",
          research: {
            schema_version: "1.0",
            status: "verified",
            sources: [],
            claims: [{ id: "c1", text: "真实判断", claim_type: "inference", confidence: "medium" }],
            relations: [],
            gaps: [],
            metrics: {},
          },
        };
      }
      throw new Error(`unexpected path: ${path}`);
    });

    const report = await fetchCurrentReport(task, request);

    expect(report).toMatchObject({
      id: "task-1",
      taskId: "task-1",
      title: "后端报告标题",
      markdown: "# 后端当前版本\n\n## 结论\n\n真实内容",
      version: 2,
      currentVersionId: "version-2",
      versions: [
        { id: "version-1", version: 1, isCurrent: false },
        { id: "version-2", version: 2, isCurrent: true },
      ],
      updatedAt: "2026-08-01T11:00:00",
      researchStatus: "verified",
      research: { claims: [{ id: "c1", text: "真实判断" }] },
    });
    expect(request).toHaveBeenCalledWith("/api/reports/task-1/versions/version-2");
  });

  it("does not manufacture a report when the backend has no current version", async () => {
    const request = vi.fn(async () => ({
      task_id: "task-1",
      title: "尚未生成",
      current_version_id: null,
      versions: [],
    }));

    await expect(fetchCurrentReport(task, request)).resolves.toBeNull();
    expect(request).toHaveBeenCalledTimes(1);
  });
});

describe("fetchWorkspaceSnapshot", () => {
  it("maps backend ids, task progress and materials without local placeholders", async () => {
    const request = vi.fn(async (path: string) => {
      if (path === "/api/projects?include_archived=true") return [{ id: "project-1", name: "真实项目", description: "后端项目", status: "进行中", progress: "64", is_archived: false, updated_at: "2026-08-01T10:04:00" }];
      if (path === "/api/materials") return [{ id: "material-1", title: "真实材料.pdf", source_type: "pdf", source: "监管公告", tags: null, warnings: ["pdf_garbled"], created_at: "2026-08-01T10:01:00" }];
      if (path === "/api/tasks?status=generating&limit=200") return [{ task_id: "task-1", title: "真实组织分析", status: "generating", analysis_type: "org", project_id: "project-1", created_at: "2026-08-01T10:00:00" }];
      if (path.startsWith("/api/tasks?status=")) return [];
      if (path === "/api/analyze/task-1/poll") return { status: "generating", phase: "network", progress_pct: 64, material_ids: ["material-1"], engine_used: "llm" };
      throw new Error(`unexpected path: ${path}`);
    });

    const snapshot = await fetchWorkspaceSnapshot(request);

    expect(snapshot.projects[0]).toMatchObject({ id: "project-1", name: "真实项目", type: "org", progress: 64 });
    expect(snapshot.tasks[0]).toMatchObject({ id: "task-1", phase: "network", progress: 64, engine: "llm", materialIds: ["material-1"] });
    expect(snapshot.materials[0]).toMatchObject({ id: "material-1", name: "真实材料.pdf", kind: "file", status: "error" });
    expect(snapshot.materials[0].note).toContain("pdf_garbled");
    expect(snapshot.reports).toEqual([]);
  });

  it("keeps the workspace usable when one completed report cannot be read", async () => {
    const request = vi.fn(async (path: string) => {
      if (path === "/api/projects?include_archived=true" || path === "/api/materials") return [];
      if (path === "/api/tasks?status=done&limit=200") return [{ task_id: "task-1", title: "已完成", status: "done", analysis_type: "case", project_id: null, created_at: "2026-08-01T10:00:00" }];
      if (path.startsWith("/api/tasks?status=")) return [];
      if (path === "/api/analyze/task-1/poll") return { status: "done", phase: "output", progress_pct: 100 };
      if (path === "/api/reports/task-1") throw new Error("报告接口失败");
      throw new Error(`unexpected path: ${path}`);
    });

    await expect(fetchWorkspaceSnapshot(request)).resolves.toMatchObject({
      tasks: [expect.objectContaining({ id: "task-1", status: "done" })],
      reports: [],
    });
  });
});

describe("createAnalysisTask", () => {
  it("sends the explicit freeform and requested-engine contract", async () => {
    const request = vi.fn(async () => ({ task_id: "task-new" }));

    const result = await createAnalysisTask({
      type: "case",
      title: "事件分析",
      context: "分析这个事件",
      engine: "auto",
      inputMode: "freeform",
      materialIds: [],
      web: false,
    }, request, "browser-profile-111111111111");

    expect(result).toEqual({ task_id: "task-new" });
    expect(request).toHaveBeenCalledWith("/api/analyze", expect.objectContaining({
      method: "POST",
      body: JSON.stringify({
        title: "事件分析",
        input_text: "分析这个事件",
        analysis_type: "case",
        input_mode: "freeform",
        requested_engine: "auto",
        project_id: null,
        material_ids: [],
        web: false,
        auto_collect: false,
        llm_config: { profile_id: "browser-profile-111111111111" },
      }),
    }));
  });
});

describe("createReportEnrichment", () => {
  it("binds selected materials and web search to the current report", async () => {
    const request = vi.fn(async () => ({
      job_task_id: "enrichment-1",
      target_task_id: "task-1",
      base_version_id: "version-2",
      status: "queued",
    }));

    const result = await createReportEnrichment("task-1", {
      instruction: "补齐官方公告与时间线",
      materialIds: ["material-1"],
      web: true,
    }, request, "browser-profile-111111111111");

    expect(result).toMatchObject({ jobTaskId: "enrichment-1", baseVersionId: "version-2" });
    expect(request).toHaveBeenCalledWith("/api/reports/task-1/enrichments", {
      method: "POST",
      body: JSON.stringify({
        instruction: "补齐官方公告与时间线",
        material_ids: ["material-1"],
        web: true,
        source_urls: [],
        llm_config: { profile_id: "browser-profile-111111111111" },
      }),
    });
  });
});

describe("project monitoring API", () => {
  it("loads, updates and manually runs local monitoring", async () => {
    const request = vi.fn(async (path: string, options?: RequestInit) => {
      if (path === "/api/projects/project-1/monitor" && !options) return { project_id: "project-1", configured: true, enabled: true, interval_hours: 24, seed_task_id: "task-1", next_run_at: "2026-08-17T10:00:00", latest_change: { has_changes: true, summary: ["发现 1 个新主体"] } };
      if (path === "/api/projects/project-1/monitor" && options?.method === "PUT") return { project_id: "project-1", configured: true, enabled: false, interval_hours: 72, seed_task_id: "task-1" };
      if (path === "/api/projects/project-1/monitor/run") return { task_id: "task-2" };
      throw new Error(`unexpected path: ${path}`);
    });

    await expect(fetchProjectMonitor("project-1", request)).resolves.toMatchObject({ projectId: "project-1", enabled: true, latestChange: { summary: ["发现 1 个新主体"] } });
    await expect(updateProjectMonitor("project-1", { enabled: false, intervalHours: 72, seedTaskId: "task-1" }, request)).resolves.toMatchObject({ enabled: false, intervalHours: 72 });
    await expect(runProjectMonitor("project-1", request)).resolves.toEqual({ taskId: "task-2" });
    expect(request).toHaveBeenCalledWith("/api/projects/project-1/monitor", expect.objectContaining({ method: "PUT" }));
    expect(request).toHaveBeenCalledWith("/api/projects/project-1/monitor/run", { method: "POST" });
  });
});
