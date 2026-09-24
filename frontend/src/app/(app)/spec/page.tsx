import type { Metadata } from "next";

export const metadata: Metadata = { title: "分析件规范 · 引力矩阵" };

const dataPieces = [
  ["趋势曲线", "TrendLine · v3 · 数据确定", "多主体声量 24h 对比，事件点可点击回溯原文"],
  ["情感堆叠条", "StackedBar · v2 · 模型推断", "单议题情感构成：正 / 中 / 负三段占比，附置信区间与样本量"],
  ["时段热力", "HeatMatrix · v1 · 数据确定", "平台 × 时段声量热力，定位首发平台与发酵窗口"],
  ["排行条", "RankBar · v2 · 数据确定", "TOP N 议题/主体，带环比升降与占比，点击下钻"],
  ["关键词权重", "TermWeight · v1 · 模型推断", "替代词云：词条 + 权重条 + 环比升降箭头，已剔除停用词"],
  ["地域下钻", "GeoDrill · v1 · 数据确定", "省→市→县三级下钻，县域为最细粒度；行政边界取自官方底图服务，禁止手绘"],
] as const;

const structurePieces = [
  ["主体关系", "RelationGraph · v3 · 模型推断", "力导向布局；虚线＝模型推断；共现与引用由模型抽取，强度需人工校准"],
  ["立场坐标", "StanceAxis · v1 · 推测", "立场四象限：支持/反对/中立/未表态；横轴表态倾向、纵轴影响力；须抽样人工复核"],
  ["利益矩阵", "InterestMatrix · v1 · 推测", "相关方 × 诉求 × 影响力，一格一结论；诉求为归纳结果，每格至少引 1 条信源"],
  ["终局预判", "OutcomeFan · v1 · 推测", "五走向概率条 + 触发条件 + 失效条件；概率为主观赋值，必写失效条件与观察窗口"],
  ["脉络时间线", "Timeline · v2 · 数据确定", "事件脉络按时间轴串起关键节点；节点须对应原文，带 [n] 与平台名"],
  ["证据链", "EvidenceChain · v1 · 数据确定", "数据 → 规则 → 结论三级逐级可回溯；任一级缺失则该结论自动降级为推测"],
] as const;

export default function SpecPageRoute() {
  return (
    <div className="wb2-page">
      <header className="wb2-header">
        <h1>分析件规范</h1>
        <p className="wb2-sub">
          报告与日报中的一切图表与结论都按本规范渲染：确定性四阶、信源脚注、套话拦截，缺一不生成
        </p>
      </header>
      <div className="wb2-rule--accent" aria-hidden="true" />
      <div className="wb2-rule--hair" aria-hidden="true" />

      <div className="spec-cols">
        <section className="spec-card">
          <h2>甲 · 数据篇（6 件）</h2>
          <ul>
            {dataPieces.map(([name, code, usage]) => (
              <li key={code}>
                <strong>{name}</strong> · {code}
                <br />
                {usage}
              </li>
            ))}
          </ul>
        </section>

        <section className="spec-card">
          <h2>乙 · 结构篇（6 件）</h2>
          <ul>
            {structurePieces.map(([name, code, usage]) => (
              <li key={code}>
                <strong>{name}</strong> · {code}
                <br />
                {usage}
              </li>
            ))}
          </ul>
        </section>

        <section className="spec-card">
          <h2>丙 · 全局契约</h2>
          <h3>确定性四阶</h3>
          <ul>
            <li><strong>数据确定</strong>：统计口径可复算</li>
            <li><strong>模型推断</strong>：附样本量与置信</li>
            <li><strong>推测</strong>：虚线框纸底，必注前提</li>
            <li><strong>未知</strong>：不渲染结论，写证据不足</li>
          </ul>
          <h3>三条铁律</h3>
          <ul>
            <li>一 · 下游确定性不得高于上游</li>
            <li>二 · 无 [n] 信源不生成结论</li>
            <li>三 · 预警分级由数据层判定，AI 只研判</li>
          </ul>
          <h3>色彩语义</h3>
          <ul>
            <li>朱砂 · 负面 / 风险 / 预警</li>
            <li>数据蓝 · 中性 / 官方口径</li>
            <li>青绿 · 正面 / 已处置</li>
            <li>金 · 事件节点 / 预判</li>
          </ul>
          <h3>排版基线</h3>
          <ul>
            <li>标题 15 / 13 · 正文 11 · 注 10 / 9</li>
            <li>刊头朱砂线 3px · 边线 1px · 圆角 6 / 3</li>
            <li>数字统一等宽字体</li>
          </ul>
        </section>

        <section className="spec-card">
          <h2>组件契约 Block</h2>
          <pre className="spec-code">{`{
  type: "TrendLine",
  payload: { series, range },
  certainty: "confirmed",
  sources: [1, 2],
  engine_version: "v3.2"
}`}</pre>
          <h3>渲染规则</h3>
          <ul>
            <li>未知 type → 渲染占位卡，不白屏</li>
            <li>certainty 缺失 → 按推测处理</li>
            <li>上游 unknown → 下游禁止渲染结论</li>
          </ul>
          <h3>渲染前拦截（正则折叠）</h3>
          <ul>
            <li>✕ 由此可见 / 综上所述 / 值得注意的是</li>
            <li>✕ 具有重要意义 / 稳步推进成效显著</li>
            <li>✕ 既有机遇也有挑战 / 需持续关注</li>
          </ul>
        </section>

        <section className="spec-card">
          <h2>第 9 项 · 每日日报</h2>
          <ul>
            <li>
              <strong>定位</strong>：日报是分析件的每日装配产物（source_kind=digest），
              由采集服务入库的全局舆情流驱动，而非人工手写摘要。
            </li>
            <li>
              <strong>构成</strong>：当日热榜 Top N + 议题排行条 + 情感堆叠 +
              地域聚合图 + 核心判断（仅一段，句句带 [n]）。
            </li>
            <li>
              <strong>纪律</strong>：与报告同一套确定性四阶与信源脚注约束；
              采不到的字段留空并说明原因，不编数据、不凑版面。
            </li>
            <li>
              <strong>当前状态</strong>：数据底座（feed_items 采集入库）已就绪，
              日报装配与渲染随舆情工作台迭代推出。
            </li>
          </ul>
        </section>

        <section className="spec-card">
          <h2>交付与验收（五步）</h2>
          <ul>
            <li>一 · 先定 Block 类型与 registry 骨架</li>
            <li>二 · 逐件实现，数据篇 6 件优先</li>
            <li>三 · 每件配 3 组真实数据快照</li>
            <li>四 · 走查确定性 / [n] / 套话拦截</li>
            <li>五 · 通过后才注入日报与政策页</li>
          </ul>
        </section>
      </div>
      <p className="wb2-footer-note">
        规范内容与分析件规范画布屏（甲 / 乙 / 丙）同步；改动须先改画布评审，再同步本页。
      </p>
    </div>
  );
}
