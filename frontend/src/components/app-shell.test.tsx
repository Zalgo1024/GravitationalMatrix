import { fireEvent, render, screen } from "@testing-library/react";
import React from "react";
import { describe, expect, it, vi } from "vitest";
import { AppShell } from "./app-shell";

const storeMocks = vi.hoisted(() => ({
  refreshWorkspace: vi.fn(async () => undefined),
}));

vi.mock("next/navigation", () => ({
  usePathname: () => "/dashboard",
  useRouter: () => ({ back: vi.fn() }),
}));

vi.mock("@/lib/store", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/store")>();
  return {
    ...actual,
    useAppStore: () => ({
      state: actual.createEmptyState(),
      hydrated: true,
      connection: "offline",
      connectionError: "连接被拒绝",
      refreshWorkspace: storeMocks.refreshWorkspace,
    }),
  };
});

describe("AppShell backend status", () => {
  it("shows an explicit offline warning and retry action", () => {
    render(<AppShell><div>工作区内容</div></AppShell>);

    expect(screen.getByText("本地后端未连接")).toBeInTheDocument();
    expect(screen.getByText(/连接被拒绝/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "重新连接" }));
    expect(storeMocks.refreshWorkspace).toHaveBeenCalledTimes(1);
  });

  it("keeps only the consolidated primary navigation", () => {
    render(<AppShell><div>工作区内容</div></AppShell>);

    const navigation = screen.getByRole("navigation", { name: "主导航" });
    expect(navigation).toHaveTextContent("工作台");
    expect(navigation).toHaveTextContent("新建分析");
    expect(navigation).toHaveTextContent("设置");
    expect(navigation).not.toHaveTextContent("项目");
    expect(navigation).not.toHaveTextContent("材料库");
    expect(navigation).not.toHaveTextContent("报告");
    expect(navigation).not.toHaveTextContent("利益拆解");
  });
});
