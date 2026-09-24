"use client";

import Link from "next/link";
import React, { useMemo, useState } from "react";
import { GraphCanvas } from "./graph-canvas";
import type { DiagramDocument } from "@/lib/report-graph";
import { applyPerspective } from "@/lib/relation-perspective";

/**
 * RelationGraph v3（画布「主体关系 RelationGraph · v3」落地的最小增量版）：
 * - 图形编码沿用既有 GraphCanvas（线宽=强度、色=极性、箭头=方向、虚线=推断、力导向）；
 * - 新增「视角切换」：选定主体后，与其无连线的部分淡出，聚焦其舆情辐射范围；
 * - 「打开完整关系网络」入口跳转既有交互页（拖拽/缩放/逐边证据）。
 * 不改动 analysis-network / graph-canvas 任何行为（报告页零回归）。
 */
export function RelationGraphV3({
  diagram,
  reportId,
}: {
  diagram: DiagramDocument;
  reportId?: string;
}) {
  const [focusId, setFocusId] = useState<string | null>(null);
  const perspective = useMemo(() => applyPerspective(diagram, focusId), [diagram, focusId]);

  return (
    <section className="relation-v3" aria-label="主体关系图 v3">
      <header className="relation-v3__head">
        <div>
          <strong>{diagram.title || "主体关系"}</strong>
          <span className="spec-badge" style={{ background: "var(--accent-soft)", color: "var(--accent)" }}>
            模型推断
          </span>
        </div>
        <label className="relation-v3__perspective">
          视角
          <select
            aria-label="选择视角主体"
            value={perspective.focusId ?? "all"}
            onChange={(event) => setFocusId(event.target.value === "all" ? null : event.target.value)}
          >
            {perspective.options.map((option) => (
              <option key={option.id} value={option.id}>{option.label}</option>
            ))}
          </select>
        </label>
      </header>
      <GraphCanvas
        diagram={diagram}
        layout="force"
        dimmedNodeIds={perspective.dimmedNodeIds}
        onSelectionChange={() => undefined}
      />
      <p className="relation-v3__footnote">
        力导向自动布局 · 虚线＝模型推断 · 共现与引用由模型抽取，强度需人工校准
      </p>
      {reportId && (
        <p className="relation-v3__open">
          <Link href={`/interest-analysis/${reportId}`}>打开完整关系网络 ›</Link>
          <span> 可拖拽节点、缩放、点任意连线查看关系证据 [n]</span>
        </p>
      )}
    </section>
  );
}
