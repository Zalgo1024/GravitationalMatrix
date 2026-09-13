"use client";

// 主体视角（F-actor）：把研究账本里的主体摊开成「一个人一张卡」——
// 所作所为（时间线事件）、行为逻辑（behavior 摘要）、核心利益与诉求（interests）、
// 立场及其演变（stance + stance_history）。全部数据来自账本，纯展示零推理：
// 卡上没有的字段如实留白，不编。账本 1.5 起才有 behavior，旧报告该栏为空。

import { GitBranch, Landmark, ListChecks, Scale } from "lucide-react";
import React from "react";
import type { ResearchBundle, ResearchTimelineEvent } from "@/lib/domain";

const stanceLabels: Record<string, string> = {
  supportive: "支持",
  opposing: "反对",
  neutral: "中立",
  mixed: "矛盾",
  unknown: "立场未明",
};

const MAX_EVENTS_PER_ACTOR = 6;

export function ActorPerspectives({ research }: { research?: ResearchBundle }) {
  const nodes = [...(research?.nodes ?? [])].sort((a, b) => (b.weight ?? 0) - (a.weight ?? 0));
  const timeline = research?.timeline ?? [];
  if (!nodes.length) return null;
  const hasBehavior = nodes.some((node) => node.behavior);

  return <section className="actor-perspectives" aria-label="主体视角">
    <header>
      <div>
        <span className="eyebrow">主体视角</span>
        <h2>各方所作所为与行为逻辑</h2>
        <p>按主体摊开：核心利益、关键行为、立场演变。全部内容来自研究账本可支撑的事实，账本没写到的如实留白。</p>
      </div>
      <Scale size={21} />
    </header>
    <div className="actor-perspectives__grid">
      {nodes.map((node) => {
        const events: ResearchTimelineEvent[] = timeline
          .filter((event) => event.actorIds.includes(node.id))
          .sort((a, b) => (a.date ?? "9999").localeCompare(b.date ?? "9999"));
        const shown = events.slice(0, MAX_EVENTS_PER_ACTOR);
        return <article key={node.id}>
          <header>
            <div>
              <small>{[node.role, node.regionName].filter(Boolean).join(" · ") || "身份待补"}</small>
              <h3>{node.label}</h3>
            </div>
            <span className={node.stance === "opposing" ? "actor-perspectives__stance actor-perspectives__stance--against" : "actor-perspectives__stance"}>
              {stanceLabels[node.stance] ?? node.stance}
            </span>
          </header>
          {node.interests.length > 0 && <div className="actor-perspectives__block">
            <strong><Landmark size={12} />核心利益与诉求</strong>
            <div className="actor-perspectives__interests">
              {node.interests.map((interest) => <span key={interest}>{interest}</span>)}
            </div>
          </div>}
          {node.behavior && <div className="actor-perspectives__block">
            <strong><GitBranch size={12} />行为逻辑</strong>
            <p>{node.behavior}</p>
          </div>}
          {shown.length > 0 && <div className="actor-perspectives__block">
            <strong><ListChecks size={12} />所作所为{events.length > shown.length ? `（前 ${shown.length} 件 / 共 ${events.length} 件）` : ""}</strong>
            <ol>
              {shown.map((event) => <li key={event.id}>
                <small>{[event.date || "时间未知", event.turningPoint ? "转折点" : ""].filter(Boolean).join(" · ")}</small>
                <span>{event.title}</span>
              </li>)}
            </ol>
          </div>}
          {node.stanceHistory.length > 1 && <div className="actor-perspectives__block">
            <strong><Scale size={12} />立场演变</strong>
            <ul className="actor-perspectives__shift">
              {node.stanceHistory.map((point, index) => <li key={`${point.at}-${index}`}>
                <small>{point.at}</small><span>{point.stance}</span>
              </li>)}
            </ul>
          </div>}
          <footer>证据 {node.evidenceIds.length} 条 · 置信度 {node.confidence}</footer>
        </article>;
      })}
    </div>
    {!hasBehavior && <p className="actor-perspectives__note">当前版本的研究账本未生成「行为逻辑」摘要；对报告执行一次「补充信息与证据」重建账本即可补上。</p>}
  </section>;
}
