"use client";

import Link from "next/link";
import React from "react";
import { useAppStore } from "@/lib/store";
import { analysisTypes, type AnalysisType } from "@/lib/domain";
import type { AnalysisTask } from "@/lib/domain";

type TypeGroup = { label: string; tasks: AnalysisTask[] };

export function ArchiveScreen() {
  const { state } = useAppStore();
  const doneTasks = state.tasks.filter((task) => task.status === "done");
  const reportByTask = new Map(state.reports.map((report) => [report.taskId, report]));

  const groups: TypeGroup[] = analysisTypes.map(({ id, label }) => ({
    label,
    tasks: doneTasks.filter((task) => task.type === id),
  }));
  const knownTypes = new Set(analysisTypes.map(({ id }) => id));
  const orphanTasks = doneTasks.filter((task) => !knownTypes.has(task.type));
  if (orphanTasks.length > 0) {
    groups.push({ label: "其他", tasks: orphanTasks });
  }

  const empty = doneTasks.length === 0;

  return (
    <div className="wb2-page">
      <header className="wb2-header">
        <h1>事件档案</h1>
        <p className="wb2-sub">
          已完成分析按类型归档 · 条目直达报告阅读页 · 跨源关联（feed_items）为后续模块
        </p>
      </header>
      <div className="wb2-rule--accent" aria-hidden="true" />
      <div className="wb2-rule--hair" aria-hidden="true" />

      {empty ? (
        <div className="archive-empty" role="status">
          暂无已完成的分析。先在「新建分析」跑一份报告，完成后会自动归档到这里。
        </div>
      ) : (
        <div className="archive-groups">
          {groups
            .filter((group) => group.tasks.length > 0)
            .map((group) => (
              <section className="archive-group" key={group.label}>
                <h2>
                  {group.label}
                  <span className="archive-pill" style={{ marginLeft: 8 }}>
                    {group.tasks.length}
                  </span>
                </h2>
                <div className="archive-rows">
                  {group.tasks.map((task) => {
                    const report = reportByTask.get(task.id);
                    return (
                      <div className="archive-row" key={task.id}>
                        <Link
                          className="archive-row__title"
                          href={report ? `/reports/${report.id}` : `/analysis/${task.id}`}
                        >
                          {task.title}
                        </Link>
                        <time dateTime={task.updatedAt}>
                          {new Date(task.updatedAt).toLocaleDateString("zh-CN")}
                        </time>
                      </div>
                    );
                  })}
                </div>
              </section>
            ))}
        </div>
      )}
    </div>
  );
}
