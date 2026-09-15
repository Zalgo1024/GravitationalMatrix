import Link from "next/link";
import { ArrowRight, Layers3, LayoutGrid, Plus, Settings } from "lucide-react";
import React from "react";

const utilityEntrances = [
  { label: "工作台", detail: "项目、任务与报告总览", href: "/dashboard", icon: LayoutGrid },
  { label: "新建分析", detail: "输入问题并添加材料", href: "/analysis", icon: Plus },
  { label: "设置", detail: "配置本机分析偏好", href: "/settings", icon: Settings },
];

export function PlatformHome() {
  return (
    <main className="home-page">
      <section className="home-hero home-hero--gateway" aria-labelledby="home-title">
        <div className="home-hero__image" aria-hidden="true" />

        <header className="home-nav home-nav--gateway">
          <Link className="home-brand" href="/" aria-label="引力矩阵首页">
            <span>三</span>
            <strong>引力矩阵</strong>
            <small>结构分析平台</small>
          </Link>
          <Link className="home-nav__entry" href="/dashboard">进入工作台 <ArrowRight size={15} /></Link>
        </header>

        <div className="home-hero__content home-hero__content--gateway">
          <p className="home-kicker"><Layers3 size={15} /> 把混沌，拆成可检验的结构</p>
          <h1 id="home-title">让复杂局势<br />变得可追溯</h1>
          <p className="home-hero__summary">把材料、主体、利益与推断组织成一条可复核的判断链，而不是一段无法追溯的结论。</p>
          <Link className="home-primary-action" href="/analysis">开始分析 <Plus size={16} /></Link>
          <p className="home-hero__scope">适用于 <strong>事件、案例、舆情、政策与组织</strong></p>
        </div>

        <nav className="home-utility-bar" aria-label="工作入口">
          {utilityEntrances.map((entry) => {
            const Icon = entry.icon;
            return <Link href={entry.href} key={entry.href}>
              <Icon size={18} />
              <span><strong>{entry.label}</strong><small>{entry.detail}</small></span>
              <ArrowRight size={15} />
            </Link>;
          })}
        </nav>
      </section>

      <section className="home-principles" aria-label="分析原则">
        <p>不是将信息堆叠成结论，而是让每一个判断都能回到它的材料、关系与约束条件。</p>
        <span>可追溯的诊断，而非不可解释的答案。</span>
      </section>
    </main>
  );
}
