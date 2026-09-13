import { render, screen } from "@testing-library/react";
import React from "react";
import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { ActorPerspectives } from "./actor-perspectives";
import type { ResearchBundle } from "@/lib/domain";

function bundle(overrides: Partial<ResearchBundle> = {}): ResearchBundle {
  return {
    status: "verified",
    sources: [],
    claims: [],
    nodes: [
      {
        id: "n1",
        label: "惠州市工信局",
        aliases: [],
        role: "政策供给方",
        interests: ["产业升级", "招商指标"],
        stance: "supportive",
        weight: 0.8,
        confidence: "high",
        evidenceIds: ["s1", "s2"],
        stanceHistory: [
          { at: "2026-08-01", stance: "观望", evidenceIds: ["s1"] },
          { at: "2026-09-01", stance: "公开支持", evidenceIds: ["s2"] },
        ],
        behavior: "先印发奖补再配套申报指引，行为逻辑是吃透政策窗口期。",
        regionCode: "440000",
        regionName: "广东省",
        regionSource: "model",
      },
      {
        id: "n2",
        label: "本地小企业",
        aliases: [],
        role: "政策接收方",
        interests: ["降成本"],
        stance: "neutral",
        weight: 0.4,
        confidence: "medium",
        evidenceIds: ["s1"],
        stanceHistory: [],
      },
    ],
    relations: [],
    timeline: [
      { id: "t1", date: "2026-08-12", title: "印发奖补措施", detail: "", eventType: "policy", actorIds: ["n1"], claimIds: [], evidenceIds: ["s1"], confidence: "high", turningPoint: false },
      { id: "t2", date: "2026-09-02", title: "企业连夜准备材料", detail: "", eventType: "action", actorIds: ["n2"], claimIds: [], evidenceIds: ["s1"], confidence: "medium", turningPoint: false },
    ],
    gaps: [],
    ...overrides,
  } as ResearchBundle;
}

describe("ActorPerspectives", () => {
  it("renders each actor with interests, behavior and matched events", () => {
    render(<ActorPerspectives research={bundle()} />);
    expect(screen.getByText("惠州市工信局")).toBeTruthy();
    expect(screen.getByText("本地小企业")).toBeTruthy();
    expect(screen.getByText("先印发奖补再配套申报指引，行为逻辑是吃透政策窗口期。")).toBeTruthy();
    expect(screen.getByText("印发奖补措施")).toBeTruthy();
    expect(screen.getByText("企业连夜准备材料")).toBeTruthy();
    expect(screen.getByText("产业升级")).toBeTruthy();
  });

  it("shows the rebuild hint when no actor carries behavior", () => {
    const research = bundle();
    research.nodes = research.nodes.map((node) => ({ ...node, behavior: null }));
    render(<ActorPerspectives research={research} />);
    expect(screen.getByText(/未生成「行为逻辑」/)).toBeTruthy();
  });

  it("renders nothing without research nodes", () => {
    const { container } = render(<ActorPerspectives research={undefined} />);
    expect(container.textContent).toBe("");
  });
});
