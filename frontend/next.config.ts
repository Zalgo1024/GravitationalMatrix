import type { NextConfig } from "next";

// Keep the hot-reload cache separate from the production build used by the
// desktop launcher. Otherwise a build can replace files that a dev server is
// still serving, leaving the browser with missing JS or CSS chunks.
const truthy = (value: string | undefined) =>
  ["1", "true", "yes", "on"].includes((value ?? "").trim().toLowerCase());

// A5/A6 —— 运营后台与工作台彻底分家（构建层 + 物理路径）：
//   - admin 页面物理放在 frontend\admin-pages\admin-console\，**不在 src\app\ 下**。
//     scripts\admin-console.ps1 会在 admin 构建时把它们临时复制进 src\app\admin-console\，
//     构建完（无论成败）再删掉。workbench 构建（default）从未执行该 swap，
//     所以 workbench 的 .next 里根本不会包含 /admin-console 任何路由。
//   - pageExtensions 防御性保留：万一有人手动把 admin 文件加进 src\app\，
//     仅当 ADMIN_UI_ENABLED=1（只有 admin 构建脚本会设）时 Next 才把它们识别为路由，
//     工作台构建时 admin 变体被天然忽略。
//   - admin 构建打开 typescript.ignoreBuildErrors：Next 15.5.20 的 LayoutProps<Route>
//     强约束 `Route extends "/"`，对子路由 layout（如 /admin-console）会报
//     `Type '"/admin-console"' is not assignable to type '"/"'` —— 这是 Next 15.5
//     已知类型生成 bug，15.6+ 才修。我们 workbench 仍保持严格检查以尽早发现真错误。
const adminUiEnabled = truthy(process.env.ADMIN_UI_ENABLED);

const nextConfig: NextConfig = {
  distDir: process.env.NEXT_DIST_DIR ?? (process.env.NODE_ENV === "development" ? ".next-dev" : ".next"),
  pageExtensions: adminUiEnabled
    ? ["tsx", "ts", "jsx", "js", "admin.tsx", "admin.ts"]
    : ["tsx", "ts", "jsx", "js"],
  typescript: adminUiEnabled
    ? { ignoreBuildErrors: true }
    : undefined,
};

export default nextConfig;
