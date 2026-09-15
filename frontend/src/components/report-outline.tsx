"use client";

import React, { useEffect, useState } from "react";

export interface ReportOutlineSection {
  id: string;
  label: string;
}

export function ReportOutline({ sections, onItemClick }: { sections: ReportOutlineSection[]; onItemClick?: (id: string) => void }) {
  const [activeId, setActiveId] = useState(sections[0]?.id ?? "");

  useEffect(() => {
    setActiveId(sections[0]?.id ?? "");
    if (typeof IntersectionObserver === "undefined") return;
    const elements = sections.map((section) => document.getElementById(section.id)).filter((element): element is HTMLElement => Boolean(element));
    if (!elements.length) return;

    const observer = new IntersectionObserver((entries) => {
      const visible = entries
        .filter((entry) => entry.isIntersecting)
        .sort((left, right) => right.intersectionRatio - left.intersectionRatio);
      if (visible[0]?.target.id) setActiveId(visible[0].target.id);
    }, { rootMargin: "-18% 0px -68% 0px", threshold: [0, 0.25, 0.5, 0.75, 1] });

    elements.forEach((element) => observer.observe(element));
    return () => observer.disconnect();
  }, [sections]);

  return <aside className="report-outline" aria-label="报告目录">
    <span className="eyebrow">目录</span>
    {sections.map((section, index) => <a href={`#${section.id}`} aria-current={activeId === section.id ? "location" : undefined} onClick={(event) => { if (onItemClick) { event.preventDefault(); onItemClick(section.id); } setActiveId(section.id); }} key={section.id}>{String(index + 1).padStart(2, "0")} {section.label}</a>)}
  </aside>;
}
