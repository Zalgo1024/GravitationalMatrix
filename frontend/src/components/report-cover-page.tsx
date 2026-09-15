import { ArrowRight } from "lucide-react";
import React from "react";

export interface ReportCoverData {
  title: string;
  subtitle: string;
  analysisType: string;
  engineLabel: string;
  version: number;
  updatedAt: string;
  materialCount: number;
  sectionCount: number;
  wordCount: number;
  overviewLead: string;
  firstSectionId: string;
}

/** 报告封面页：把报告上方的元信息单独呈现为第一页，正文紧随其后。 */
export function ReportCoverPage({ data }: { data: ReportCoverData }) {
  const estimatedMinutes = Math.max(1, Math.round(data.wordCount / 400));
  const meta = [
    { label: "分析类型", value: data.analysisType },
    { label: "执行引擎", value: data.engineLabel },
    { label: "报告版本", value: `v${data.version}` },
    { label: "更新时间", value: data.updatedAt },
    { label: "关联材料", value: `${data.materialCount} 份` },
    { label: "正文章节", value: `${data.sectionCount} 章` },
    { label: "报告字数", value: `${data.wordCount.toLocaleString("zh-CN")} 字` },
    { label: "预计阅读", value: `~${estimatedMinutes} 分钟` },
  ];
  return (
    <div className="report-cover">
      <section className="report-cover__overview" id="report-cover">
        <span className="eyebrow">引力矩阵分析报告 · {data.analysisType}</span>
        <h2>{data.title}</h2>
        <p>{data.subtitle}</p>
      </section>
      <section className="report-cover__meta" id="cover-meta">
        <div className="section-title">
          <div><span className="eyebrow">任务元数据</span><h3>报告信息</h3></div>
        </div>
        <div className="report-cover__grid">
          {meta.map((item) => (
            <div className="report-cover__card" key={item.label}>
              <span>{item.label}</span>
              <strong>{item.value}</strong>
            </div>
          ))}
          <a className="report-cover__meta-cta" href={`#${data.firstSectionId}`}>
            <span>开始阅读正文</span>
            <ArrowRight size={16} />
          </a>
        </div>
      </section>
      <section className="report-cover__summary" id="cover-summary">
        <div className="section-title">
          <div><span className="eyebrow">内容摘要</span><h3>情况概述</h3></div>
        </div>
        <p className="report-cover__lead">
          {data.overviewLead || "报告正文从「情况概述」章节开始，后续章节逐步展开主体、利益与关系的结构化分析。"}
        </p>
      </section>
    </div>
  );
}
