"use client";

import { useState } from "react";
import { useAppStore } from "@/lib/store";
import { ResearchBenchmark } from "@/components/research-benchmark";

export default function BenchmarkPageRoute() {
  const { state } = useAppStore();
  const doneTasks = state.tasks.filter((task) => task.status === "done");
  const [taskId, setTaskId] = useState(doneTasks[0]?.id ?? "");

  return (
    <div className="wb2-page benchmark-shell">
      <header className="wb2-header">
        <h1>对标分析</h1>
        <p className="wb2-sub">
          同题对照测试：本系统 / 通用 AI / 人工分析 · 不合成总分，不让系统自己宣布胜者
        </p>
      </header>
      <div className="wb2-rule--accent" aria-hidden="true" />
      <div className="wb2-rule--hair" aria-hidden="true" />

      {doneTasks.length === 0 ? (
        <div className="archive-empty" role="status">
          暂无已完成的分析任务。先在「新建分析」产出一份报告，再回到这里建立对照基线。
        </div>
      ) : (
        <>
          <div className="benchmark-picker">
            <label htmlFor="benchmark-task-select">选择分析任务</label>
            <select
              id="benchmark-task-select"
              value={taskId}
              onChange={(event) => setTaskId(event.target.value)}
            >
              {doneTasks.map((task) => (
                <option key={task.id} value={task.id}>{task.title}</option>
              ))}
            </select>
          </div>
          {taskId && <ResearchBenchmark taskId={taskId} />}
        </>
      )}
    </div>
  );
}
