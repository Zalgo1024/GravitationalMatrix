"use client";

import { CheckCircle2, ChevronDown, CircleHelp, FileText, Globe2, Paperclip, Radar, Send, Sparkles, X } from "lucide-react";
import React, { useRef, useState } from "react";
import { analysisTypes, type AnalysisType, type EngineMode, type MaterialRecord, type NewAnalysisInput, type Project } from "@/lib/domain";

// 与后端 backend/app/routers/materials.py parse_uploaded_file 支持的格式保持一致；
// 图片/PPT 等二进制格式后端无法解析为文本，前端直接拒绝，避免入库乱码素材。
const acceptedFileTypes = ".pdf,.docx,.txt,.md";
const SUPPORTED_EXTENSIONS = ["pdf", "docx", "txt", "md"];

const analysisInputExamples: Record<AnalysisType, { label: string; prompt: string }> = {
  case: {
    label: "事件分析示例",
    prompt: "分析近期发生的某事件：梳理关键时间线、主要参与者及其利益关系，判断冲突为何发生、风险会如何演化，以及有哪些可验证的后续信号。",
  },
  policy: {
    label: "政策分析示例",
    prompt: "分析某项政策：说明政策要解决的问题、影响的主要群体与利益变化，评估执行约束、潜在副作用和不同情景下的结果。",
  },
  opinion: {
    label: "舆情分析示例",
    prompt: "分析某起舆情事件：还原事件与传播时间线，区分主要叙事、参与群体和沉默方，判断情绪转折点、扩散机制与后续风险。",
  },
  org: {
    label: "组织分析示例",
    prompt: "分析某个组织：梳理决策权、资源流向和正式与非正式关系，判断当前矛盾的形成机制、组织风险与可行调整方案。",
  },
  combo: {
    label: "组合分析示例",
    prompt: "综合分析某个问题：同时从事件、政策、组织和舆情角度识别关键主体、利益关系、制度约束与传播机制，并给出证据边界、情景预测和行动方案。",
  },
};

interface AnalysisCreationProps {
  onCreate: (input: NewAnalysisInput) => void | Promise<void>;
  onUpload?: (files: File[]) => Promise<MaterialRecord[]>;
  materials?: MaterialRecord[];
  projects?: Project[];
  defaultEngine?: EngineMode;
  initialType?: AnalysisType;
  initialPrompt?: string;
  reportTitle?: string;
}

export function AnalysisCreation({
  onCreate,
  onUpload,
  defaultEngine = "auto",
  initialType = "case",
  initialPrompt = "",
  reportTitle,
}: AnalysisCreationProps) {
  const [message, setMessage] = useState(initialPrompt);
  const [type, setType] = useState<AnalysisType>(initialType);
  // 自由输入的默认工作流是“先检索，再分析”；用户仍可主动关闭联网检索。
  const [useWeb, setUseWeb] = useState(true);
  // F2 自动取证：提交分析时同步跑多平台采集，采集结果自动入库材料库。
  const [autoCollect, setAutoCollect] = useState(false);
  const [attachments, setAttachments] = useState<MaterialRecord[]>([]);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const inputExample = analysisInputExamples[type];

  async function upload(files: FileList | null) {
    if (!files?.length) return;
    const selected = Array.from(files);
    // 双保险：绕过 input accept 拖入的文件也要按扩展名拦截（后端只支持文本类格式）
    const unsupported = selected.find((file) => {
      const ext = (file.name.split(".").pop() ?? "").toLowerCase();
      return !SUPPORTED_EXTENSIONS.includes(ext);
    });
    if (unsupported) { setError(`"${unsupported.name}" 格式暂不支持，请上传 txt / md / docx / pdf 文件。`); return; }
    const oversized = selected.find((file) => file.size > 50 * 1024 * 1024);
    if (oversized) { setError(`"${oversized.name}"超过 50MB 限制。`); return; }
    if (!onUpload) { setError("材料上传功能暂不可用，请稍后重试。"); return; }
    setBusy(true); setError("");
    try {
      const uploaded = await onUpload(selected);
      setAttachments((current) => [...current, ...uploaded.filter((item) => !current.some((existing) => existing.id === item.id))]);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "材料上传失败，请稍后重试。");
    } finally {
      setBusy(false);
      if (fileInputRef.current) fileInputRef.current.value = "";
    }
  }

  async function submit() {
    const input = message.trim();
    if (!input) { setError("请先输入你想分析的问题、线索或链接。"); return; }
    setBusy(true); setError("");
    try {
      const title = `${analysisTypes.find((item) => item.id === type)?.label ?? "结构分析"}：${input.slice(0, 42)}`;
      await onCreate({
        type,
        title,
        context: input,
        engine: defaultEngine,
        inputMode: "freeform",
        materialIds: attachments.map((item) => item.id),
        web: useWeb,
        autoCollect,
      });
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "创建分析失败，请稍后重试。");
    } finally { setBusy(false); }
  }

  return <section className="conversation-entry" aria-labelledby="analysis-create-title">
    <header className="conversation-entry__heading">
      <span className="eyebrow">新的分析对话</span>
      <h1 id="analysis-create-title">从你的问题开始</h1>
      <p>{reportTitle ? `这段新对话将关联报告「${reportTitle}」。` : "描述事件、粘贴链接，或直接提出你希望验证的判断。"}</p>
    </header>
    <details className="analysis-tutorial">
      <summary>
        <CircleHelp size={18} />
        <span><strong>查看输入教程</strong><small>不知道怎么写时，从这里开始</small></span>
        <ChevronDown className="analysis-tutorial__chevron" size={18} />
      </summary>
      <div className="analysis-tutorial__content">
        <section>
          <span className="eyebrow">有效输入</span>
          <h2>最少写清两件事</h2>
          <ol>
            <li><strong>分析对象</strong><span>事件、政策、组织、舆情，或一条需要验证的判断。</span></li>
            <li><strong>希望回答的问题</strong><span>你想看清哪些主体、关系、原因、风险或决策选项。</span></li>
          </ol>
          <p>时间范围、你的决策身份、重点主体和已知线索属于增强项；没有也可以先开始。</p>
        </section>
        <section className="analysis-tutorial__example">
          <div>
            <span className="eyebrow">{inputExample.label}</span>
            <button type="button" aria-label={`填入${inputExample.label}`} onClick={() => { setMessage(inputExample.prompt); setError(""); }}>填入示例</button>
          </div>
          <p>{inputExample.prompt}</p>
        </section>
        <div className="analysis-tutorial__materials">
          <strong>材料怎么用</strong>
          <span>有原文、公告或访谈时用“添加材料”；默认会联网检索公开来源并与输入一起分析。只想基于已提供材料工作时，再关闭“联网检索”。</span>
        </div>
      </div>
    </details>
    <div className="conversation-entry__body">
      <section className="conversation-composer" aria-label="新建分析对话">
        {reportTitle && <div className="conversation-context"><FileText size={15} /><span>关联报告：{reportTitle}</span></div>}
        <textarea aria-label="分析输入" value={message} onChange={(event) => setMessage(event.target.value)} placeholder="例如：港口扩建听证会正在引发哪些利益冲突？需要重点关注哪些主体与风险？" rows={7} />
        {attachments.length > 0 && <div className="conversation-attachments" aria-label="已附加材料">{attachments.map((item) => <span key={item.id}><FileText size={14} />{item.name}<button type="button" onClick={() => setAttachments((current) => current.filter((attachment) => attachment.id !== item.id))} aria-label={`移除 ${item.name}`}><X size={13} /></button></span>)}</div>}
        <div className="conversation-composer__footer">
          <div className="conversation-tools">
            <input ref={fileInputRef} className="visually-hidden" type="file" multiple accept={acceptedFileTypes} onChange={(event) => void upload(event.target.files)} />
            <button className="composer-tool" type="button" onClick={() => fileInputRef.current?.click()} disabled={busy} title="添加材料"><Paperclip size={17} /><span>添加材料</span></button>
            <button className={useWeb ? "composer-tool composer-tool--active" : "composer-tool"} type="button" onClick={() => setUseWeb((current) => !current)} disabled={busy} title="联网检索"><Globe2 size={17} /><span>联网检索</span></button>
            <label className="composer-purpose"><Sparkles size={16} /><span>分析用途</span><select aria-label="分析用途" value={type} onChange={(event) => setType(event.target.value as AnalysisType)}>{analysisTypes.map((item) => <option value={item.id} key={item.id}>{item.label}</option>)}</select></label>
          </div>
          <button className="composer-send" type="button" onClick={() => void submit()} disabled={busy}>{busy ? "处理中" : "开始分析"}<Send size={16} /></button>
        </div>
      </section>
      <aside className="conversation-entry__aside">
        <strong>提交前检查</strong>
        <ul>
          <li><CheckCircle2 size={16} /><span><b>对象</b>：要分析的事件、政策或组织是否明确</span></li>
          <li><CheckCircle2 size={16} /><span><b>问题</b>：希望系统最终回答什么</span></li>
          <li><CheckCircle2 size={16} /><span><b>范围</b>：有时间、地区或主体边界时一并写入</span></li>
        </ul>
        <div><Globe2 size={17} /><span>没有现成材料时，可开启联网检索补充公开证据。</span></div>
      </aside>
    </div>
    {error && <p className="form-error conversation-entry__error" role="alert">{error}</p>}
  </section>;
}
