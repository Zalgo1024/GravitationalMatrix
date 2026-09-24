import { describe, expect, it } from "vitest";
import { applyPerspective, perspectiveOptions } from "./relation-perspective";
import type { DiagramDocument } from "./report-graph";

const diagram: DiagramDocument = {
  title: "测试网络",
  viz: "network",
  nodes: [
    { id: "n1", label: "本方主体", type: "actor" },
    { id: "n2", label: "监管部门", type: "political" },
    { id: "n3", label: "无关方", type: "actor" },
  ],
  edges: [
    { id: "e1", source: "n1", target: "n2", label: "监管压力", type: "power", strength: 4, polarity: "negative", direction: "mutual", relationStatus: "confirmed" },
    { id: "e2", source: "n2", target: "n3", label: "偶发接触", type: "unknown", strength: 1, polarity: "neutral", direction: "undirected", relationStatus: "inferred" },
  ],
};

describe("perspectiveOptions", () => {
  it("首项为全景，其余列出全部节点", () => {
    const options = perspectiveOptions(diagram);
    expect(options[0]).toEqual({ id: "all", label: "全景视角" });
    expect(options.map((o) => o.label)).toContain("监管部门");
    expect(options).toHaveLength(4);
  });
});

describe("applyPerspective", () => {
  it("全景视角：无淡出", () => {
    const state = applyPerspective(diagram, "all");
    expect(state.focusId).toBeNull();
    expect(state.dimmedNodeIds.size).toBe(0);
  });

  it("选定主体：与其无连线的节点被淡出，有连线的保留", () => {
    const state = applyPerspective(diagram, "n1");
    expect(state.focusId).toBe("n1");
    // n2 与 n1 直连保留；n3 与 n1 无连线 → 淡出
    expect(state.dimmedNodeIds.has("n3")).toBe(true);
    expect(state.dimmedNodeIds.has("n1")).toBe(false);
    expect(state.dimmedNodeIds.has("n2")).toBe(false);
  });

  it("不存在的 focusId 回退全景（不崩溃）", () => {
    const state = applyPerspective(diagram, "ghost");
    expect(state.focusId).toBeNull();
    expect(state.dimmedNodeIds.size).toBe(0);
  });
});
