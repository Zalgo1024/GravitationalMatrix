import { describe, expect, it } from "vitest";
import { geoPositions, layoutPositions, ringPositions } from "./graph-layout";
import type { DiagramNode } from "./report-graph";

function node(id: string, type: string, regionCode?: string): DiagramNode {
  return { id, label: id, type, regionCode: regionCode ?? null };
}

describe("ringPositions", () => {
  it("keeps same-type nodes close and puts different types apart", () => {
    const positions = ringPositions([node("a", "material"), node("b", "material"), node("c", "legal")]);
    const a = positions.get("a")!;
    const b = positions.get("b")!;
    const c = positions.get("c")!;
    const dist = (p: typeof a, q: typeof a) => Math.hypot(p.x - q.x, p.y - q.y);
    expect(dist(a, b)).toBeLessThan(dist(a, c));
    // 两个分组都要落在大圆上，不能挤在原点
    expect(Math.hypot(c.x, c.y)).toBeGreaterThan(300);
  });

  it("returns an empty map without nodes", () => {
    expect(ringPositions([]).size).toBe(0);
  });
});

describe("geoPositions", () => {
  it("places provinces by longitude and latitude", () => {
    const positions = geoPositions([
      node("gd", "material", "440000"),
      node("sc", "material", "510000"),
    ]);
    const gd = positions.get("gd")!;
    const sc = positions.get("sc")!;
    // 广东在四川东南：x 更大（更东）、y 更大（画布 y 向下为南）
    expect(gd.x).toBeGreaterThan(sc.x);
    expect(gd.y).toBeGreaterThan(sc.y);
  });

  it("spreads same-province nodes instead of stacking them", () => {
    const positions = geoPositions([
      node("a", "material", "440000"),
      node("b", "material", "440000"),
    ]);
    expect(positions.get("a")).not.toEqual(positions.get("b"));
  });

  it("parks region-less nodes in the unknown column", () => {
    const positions = geoPositions([node("x", "actor"), node("gd", "actor", "440000")]);
    expect(positions.get("x")!.x).toBeGreaterThan(positions.get("gd")!.x);
  });
});

describe("layoutPositions", () => {
  it("returns null for the force layout so physics keeps running", () => {
    expect(layoutPositions([node("a", "material")], "force")).toBeNull();
  });
});
