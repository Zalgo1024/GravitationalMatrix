import React from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { RelationGraphV3 } from "./relation-graph-v3";
import type { DiagramDocument } from "@/lib/report-graph";

vi.mock("./graph-canvas", () => ({
  GraphCanvas: vi.fn((props: { diagram: DiagramDocument; dimmedNodeIds?: ReadonlySet<string> }) => (
    <div
      data-testid="graph-canvas-mock"
      data-dimmed={[...(props.dimmedNodeIds ?? [])].sort().join(",")}
      data-viz={props.diagram.viz}
    />
  )),
}));

const diagram: DiagramDocument = {
  title: "主体关系",
  viz: "network",
  nodes: [
    { id: "n1", label: "本方主体", type: "actor" },
    { id: "n2", label: "监管部门", type: "political" },
    { id: "n3", label: "无关方", type: "actor" },
  ],
  edges: [
    { id: "e1", source: "n1", target: "n2", label: "监管压力", type: "power", strength: 4, polarity: "negative", direction: "mutual", relationStatus: "confirmed" },
  ],
};

describe("RelationGraphV3", () => {
  it("渲染图区、脚注与完整网络入口", () => {
    render(<RelationGraphV3 diagram={diagram} reportId="rep1" />);
    expect(screen.getByTestId("graph-canvas-mock")).toHaveAttribute("data-viz", "network");
    expect(screen.getByText(/力导向自动布局/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /打开完整关系网络/ })).toHaveAttribute(
      "href",
      "/interest-analysis/rep1",
    );
  });

  it("视角切换后非关联节点被淡出", () => {
    render(<RelationGraphV3 diagram={diagram} />);
    const canvas = screen.getByTestId("graph-canvas-mock");
    expect(canvas).toHaveAttribute("data-dimmed", "");
    fireEvent.change(screen.getByRole("combobox", { name: "选择视角主体" }), {
      target: { value: "n1" },
    });
    expect(canvas).toHaveAttribute("data-dimmed", "n3");
  });

  it("切回全景清空淡出", () => {
    render(<RelationGraphV3 diagram={diagram} />);
    const select = screen.getByRole("combobox", { name: "选择视角主体" });
    fireEvent.change(select, { target: { value: "n1" } });
    fireEvent.change(select, { target: { value: "all" } });
    expect(screen.getByTestId("graph-canvas-mock")).toHaveAttribute("data-dimmed", "");
  });
});
