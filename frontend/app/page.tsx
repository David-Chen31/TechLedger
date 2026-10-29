"use client";

import { useCallback, useEffect, useState } from "react";

const apiBase = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

type Source = {
  id: string;
  url: string;
  host: string;
  status: string;
  review_status: string;
  storage_policy: string;
  review_note: string | null;
  latest_snapshot_id: string | null;
};

type SearchHit = {
  chunk_id: string;
  source_url: string;
  snapshot_sha256: string;
  title: string;
  start_char: number;
  end_char: number;
  snippet: string;
  score: number;
  mode: string;
};

type Citation = SearchHit & { text: string };

type ResearchResult = {
  id: string; status: string; error_code: string | null; card_id: string | null; card_status: string | null;
  events: { stage: string; detail: Record<string, unknown>; at: string }[];
  result: { question: string; summary: string; evidence: SearchHit[]; claims: { text: string; chunk_id: string }[]; unknowns: string[]; model_mode: string; usage: Record<string, number>; duration_ms: number; retrieval_trace?: { calls: { stage: string; query: string; hit_count: number }[]; repaired: { candidate: string; capability: string; added: number }[]; unresolved: { candidate: string; capability: string }[]; stop_reason: string; evidence_input_chars: number } } | null;
};

type Card = { id: string; status: string; content: { question: string; summary: string; evidence: SearchHit[] }; stale_source_ids: string[]; history: { action: string; note: string; at: string }[] };
type Evaluation = { mode: string; case_count: number; source_recall_at_k: number | null; source_top1_accuracy: number | null; negative_abstention_rate: number | null; term_recall_at_k: number | null; citation_valid_rate: number | null;
  cases: { id: string; hit_count: number; expected_source_recall: number | null; expected_term_recall: number | null }[] };

type Snapshot = {
  id: string;
  title: string;
  content_sha256: string;
  content_type: string;
  byte_size: number;
  fetched_at: string;
};

type SyncJob = {
  id: string;
  status: string;
  result: string | null;
  error_code: string | null;
  error_message: string | null;
};

const examples = [
  { label: "LangGraph 文档", url: "https://docs.langchain.com/oss/python/langgraph/overview" },
  { label: "CrewAI 文档", url: "https://docs.crewai.com/en/introduction" },
  { label: "LangGraph 发布记录", url: "https://github.com/langchain-ai/langgraph/releases" },
  { label: "CrewAI 发布记录", url: "https://github.com/crewAIInc/crewAI/releases" },
];

async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${apiBase}${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...init?.headers },
    cache: "no-store",
  });
  if (!response.ok) {
    const payload = await response.json().catch(() => null);
    const message = payload?.detail?.message ?? payload?.detail?.code ?? `HTTP ${response.status}`;
    throw new Error(message);
  }
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

export default function Home() {
  const [sources, setSources] = useState<Source[]>([]);
  const [url, setUrl] = useState("");
  const [selected, setSelected] = useState<string | null>(null);
  const [snapshots, setSnapshots] = useState<Snapshot[]>([]);
  const [snapshotDiff, setSnapshotDiff] = useState<{ available: boolean; reason?: string; diff?: string } | null>(null);
  const [activeJob, setActiveJob] = useState<string | null>(null);
  const [job, setJob] = useState<SyncJob | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [reviewNote, setReviewNote] = useState("");
  const [query, setQuery] = useState("");
  const [searchMode, setSearchMode] = useState("bm25");
  const [hits, setHits] = useState<SearchHit[]>([]);
  const [citation, setCitation] = useState<Citation | null>(null);
  const [researchQuestion, setResearchQuestion] = useState("");
  const [researchConstraints, setResearchConstraints] = useState("");
  const [researchCandidates, setResearchCandidates] = useState("LangGraph, CrewAI");
  const [researchId, setResearchId] = useState<string | null>(null);
  const [research, setResearch] = useState<ResearchResult | null>(null);
  const [cards, setCards] = useState<Card[]>([]);
  const [datasetText, setDatasetText] = useState('{"version":1,"cases":[]}');
  const [evaluation, setEvaluation] = useState<Evaluation | null>(null);

  const loadCards = useCallback(async () => {
    try { setCards(await api<Card[]>("/api/cards")); }
    catch (cause) { setError(cause instanceof Error ? cause.message : "加载决策库失败"); }
  }, []);

  const loadSources = useCallback(async () => {
    try {
      setSources(await api<Source[]>("/api/sources"));
      setError(null);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "加载来源失败");
    }
  }, []);

  const loadSnapshots = useCallback(async (sourceId: string) => {
    try {
      setSnapshots(await api<Snapshot[]>(`/api/sources/${sourceId}/snapshots`));
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "加载快照失败");
    }
  }, []);

  useEffect(() => { void loadSources(); void loadCards(); }, [loadSources, loadCards]);

  useEffect(() => {
    if (!activeJob) return;
    let cancelled = false;
    const poll = async () => {
      try {
        const result = await api<SyncJob>(`/api/jobs/${activeJob}`);
        if (cancelled) return;
        setJob(result);
        if (result.status === "completed" || result.status === "failed") {
          setActiveJob(null);
          void loadSources();
          void loadCards();
          if (selected) void loadSnapshots(selected);
        }
      } catch (cause) {
        if (!cancelled) setError(cause instanceof Error ? cause.message : "查询同步任务失败");
      }
    };
    void poll();
    const timer = window.setInterval(() => { void poll(); }, 1500);
    return () => { cancelled = true; window.clearInterval(timer); };
  }, [activeJob, loadSnapshots, loadSources, selected]);

  useEffect(() => {
    if (!researchId) return;
    let cancelled = false;
    const poll = async () => {
      try {
        const value = await api<ResearchResult>(`/api/research/${researchId}`);
        if (!cancelled) {
          setResearch(value);
          if (["completed", "partial", "failed", "cancelled"].includes(value.status)) setResearchId(null);
        }
      } catch (cause) { if (!cancelled) setError(cause instanceof Error ? cause.message : "查询调研失败"); }
    };
    void poll();
    const timer = window.setInterval(() => { void poll(); }, 1500);
    return () => { cancelled = true; window.clearInterval(timer); };
  }, [researchId]);

  useEffect(() => {
    if (!researchId) return;
    const stream = new EventSource(`${apiBase}/api/research/${researchId}/events`);
    stream.addEventListener("stage", () => {
      void api<ResearchResult>(`/api/research/${researchId}`).then(setResearch).catch(() => undefined);
    });
    stream.addEventListener("done", () => {
      void api<ResearchResult>(`/api/research/${researchId}`).then(setResearch).catch(() => undefined);
      stream.close();
    });
    return () => stream.close();
  }, [researchId]);

  async function addSource(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const created = await api<Source>("/api/sources", {
        method: "POST",
        body: JSON.stringify({ url }),
      });
      setUrl("");
      setSelected(created.id);
      await loadSources();
      await loadSnapshots(created.id);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "登记来源失败");
    } finally {
      setBusy(false);
    }
  }

  async function syncSource(sourceId: string) {
    setError(null);
    setJob(null);
    try {
      const queued = await api<SyncJob>(`/api/sources/${sourceId}/sync`, { method: "POST" });
      setActiveJob(queued.id);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "创建同步任务失败");
    }
  }

  async function rebuildSource(sourceId: string) {
    try {
      const queued = await api<SyncJob>(`/api/sources/${sourceId}/rebuild`, { method: "POST" });
      setActiveJob(queued.id);
    } catch (cause) { setError(cause instanceof Error ? cause.message : "重建索引失败"); }
  }

  async function archiveSource(sourceId: string) {
    const reason = window.prompt("归档来源将移除本地索引，相关决策会要求复核。请输入归档理由。");
    if (!reason?.trim()) return;
    try {
      await api<void>(`/api/sources/${sourceId}?reason=${encodeURIComponent(reason)}`, { method: "DELETE" });
      if (selected === sourceId) { setSelected(null); setSnapshots([]); }
      await loadSources(); await loadCards();
    } catch (cause) { setError(cause instanceof Error ? cause.message : "归档来源失败"); }
  }

  function chooseSource(sourceId: string) {
    setSelected(sourceId);
    setSnapshotDiff(null);
    void loadSnapshots(sourceId);
  }

  async function loadDiff() {
    if (!selected) return;
    try { setSnapshotDiff(await api(`/api/sources/${selected}/diff`)); }
    catch (cause) { setError(cause instanceof Error ? cause.message : "查看差异失败"); }
  }

  async function approveIndex() {
    if (!selected) return;
    setError(null);
    try {
      await api<Source>(`/api/sources/${selected}/review`, {
        method: "POST",
        body: JSON.stringify({ allow_local_index: true, note: reviewNote }),
      });
      setReviewNote("");
      await loadSources();
      await syncSource(selected);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "来源审核失败");
    }
  }

  async function searchEvidence(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    setCitation(null);
    try {
      setHits(await api<SearchHit[]>(`/api/search?query=${encodeURIComponent(query)}&mode=${searchMode}`));
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "检索失败");
    }
  }

  async function openCitation(chunkId: string) {
    try {
      setCitation(await api<Citation>(`/api/chunks/${chunkId}`));
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "引用已失效");
    }
  }

  async function startResearch(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null); setResearch(null);
    try {
      const created = await api<{ id: string }>("/api/research", { method: "POST", body: JSON.stringify({
        question: researchQuestion, constraints: researchConstraints,
        candidates: researchCandidates.split(",").map((part) => part.trim()).filter(Boolean).slice(0, 3),
      }) });
      setResearchId(created.id);
    } catch (cause) { setError(cause instanceof Error ? cause.message : "创建调研失败"); }
  }

  async function reviewDecision(action: "approve" | "return") {
    if (!research?.card_id) return;
    const note = window.prompt("请记录审核理由");
    if (!note?.trim()) return;
    try {
      await api(`/api/cards/${research.card_id}/review`, { method: "POST", body: JSON.stringify({ action, note }) });
      setResearch({ ...research, card_status: action === "approve" ? "approved" : "returned" });
      await loadCards();
    } catch (cause) { setError(cause instanceof Error ? cause.message : "审核失败"); }
  }

  async function cardAction(card: Card, action: "keep" | "archive" | "revision") {
    const note = window.prompt("请记录操作理由");
    if (!note?.trim()) return;
    try {
      if (action === "revision") {
        const summary = window.prompt("修改后的结论", card.content.summary);
        if (!summary?.trim()) return;
        const ids = window.prompt("当前证据片段 ID（逗号分隔）。请先在证据检索中查找最新来源。", card.content.evidence.map((item) => item.chunk_id).join(","));
        if (!ids?.trim()) return;
        await api(`/api/cards/${card.id}/revision`, { method: "POST", body: JSON.stringify({ summary, note,
          evidence_chunk_ids: ids.split(",").map((item) => item.trim()).filter(Boolean) }) });
      } else {
        await api(`/api/cards/${card.id}/review`, { method: "POST", body: JSON.stringify({ action, note }) });
      }
      await loadCards();
    } catch (cause) { setError(cause instanceof Error ? cause.message : "决策操作失败"); }
  }

  async function runEvaluation(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    try {
      const dataset = JSON.parse(datasetText);
      setEvaluation(await api<Evaluation>(`/api/evaluation/replay?mode=${searchMode}`, { method: "POST", body: JSON.stringify(dataset) }));
    } catch (cause) { setError(cause instanceof Error ? cause.message : "评测失败"); }
  }

  return (
    <main className="shell">
      <header className="hero">
        <div className="eyebrow">TECHLEDGER · 技术决策账本</div>
        <h1>让技术选型有证据，能复核。</h1>
        <p>将公开技术资料、调研证据和人工审核的决策连成可复核的记录。</p>
      </header>

      <section className="workspace">
        <div className="panel">
          <div className="panelTitle"><div><h2>来源登记</h2><p>仅接受首批批准的官方文档与发布记录地址。</p></div><span className="count">{sources.length} 个来源</span></div>
          <form onSubmit={addSource} className="sourceForm">
            <label htmlFor="source-url">来源 URL</label>
            <div className="formRow"><input id="source-url" type="url" required value={url} onChange={(event) => setUrl(event.target.value)} placeholder="https://docs.langchain.com/..." /><button disabled={busy} type="submit">{busy ? "登记中" : "登记来源"}</button></div>
          </form>
          <div className="examples">示例：{examples.map((item) => <button key={item.url} type="button" onClick={() => setUrl(item.url)}>{item.label}</button>)}</div>
          {error && <div role="alert" className="alert">{error}</div>}
          <div className="sourceList">
            {sources.length === 0 && <p className="empty">还没有来源。选择一个官方示例开始。</p>}
            {sources.map((source) => (
              <article key={source.id} className={`sourceCard ${selected === source.id ? "selected" : ""}`}>
                <button className="sourceSelect" type="button" onClick={() => chooseSource(source.id)}>
                  <strong>{source.host}</strong><span>{source.url}</span>
                </button>
                <div className="sourceMeta"><span className={`badge ${source.status}`}>{source.status}</span><span>保存策略：{source.storage_policy === "index_local" ? "已审核索引" : "仅元数据"}</span><button type="button" onClick={() => void syncSource(source.id)}>同步</button>{source.storage_policy === "index_local" && <button type="button" onClick={() => void rebuildSource(source.id)}>重建索引</button>}<button type="button" onClick={() => void archiveSource(source.id)}>归档</button></div>
              </article>
            ))}
          </div>
        </div>

        <aside className="panel detailPanel">
          <div className="panelTitle"><div><h2>来源快照</h2><p>相同内容不会生成重复快照；旧版本保留。</p></div></div>
          {!selected && <p className="empty">选择左侧来源，查看同步历史。</p>}
          {selected && snapshots.length === 0 && <p className="empty">此来源尚无快照。点击“同步”获取标题与内容指纹。</p>}
          {selected && snapshots.length > 1 && <button type="button" onClick={() => void loadDiff()}>查看最新两版差异</button>}
          {snapshotDiff && (snapshotDiff.available ? <pre className="diffView">{snapshotDiff.diff}</pre> : <p className="empty">无法显示正文差异：{snapshotDiff.reason}</p>)}
          {job && <div className={`job ${job.status}`}><strong>同步任务：{job.status}</strong><span>{job.error_message ?? job.result ?? "正在处理"}</span></div>}
          {selected && sources.find((item) => item.id === selected)?.storage_policy === "metadata_only" && <div className="reviewBox">
            <h3>允许本地索引</h3>
            <p>请先核查该来源的使用条款。确认后填写审核依据，系统才会在下次同步时保存可检索文本。</p>
            <textarea value={reviewNote} onChange={(event) => setReviewNote(event.target.value)} placeholder="记录允许本地索引的依据（至少 10 字）" />
            <button type="button" disabled={reviewNote.trim().length < 10} onClick={() => void approveIndex()}>确认并同步</button>
          </div>}
          {selected && snapshots.map((snapshot) => (
            <div className="snapshot" key={snapshot.id}>
              <h3>{snapshot.title}</h3>
              <p>{new Date(snapshot.fetched_at).toLocaleString("zh-CN")}</p>
              <dl><dt>类型</dt><dd>{snapshot.content_type}</dd><dt>大小</dt><dd>{snapshot.byte_size.toLocaleString()} B</dd><dt>SHA-256</dt><dd className="hash">{snapshot.content_sha256}</dd></dl>
            </div>
          ))}
          <p className="footnote">未经审核的来源只保存元数据。允许本地索引后，提取文本用于检索；原文不会作为公开数据包再发布。</p>
        </aside>
      </section>

      <section className="panel searchPanel">
        <div className="panelTitle"><div><h2>证据检索</h2><p>仅检索已审核允许索引的来源，结果绑定内容快照。</p></div></div>
        <form className="formRow searchForm" onSubmit={searchEvidence}>
          <input aria-label="检索问题" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="例如：durable execution" required />
          <select aria-label="检索模式" value={searchMode} onChange={(event) => setSearchMode(event.target.value)}><option value="bm25">BM25 关键词</option><option value="vector">字符向量</option><option value="hybrid">融合</option></select>
          <button type="submit">搜索证据</button>
        </form>
        {hits.length === 0 && <p className="empty">输入术语搜索；没有结果时请检查来源是否已通过审核并完成同步。</p>}
        <div className="hitGrid">{hits.map((hit) => <article className="hit" key={hit.chunk_id}>
          <h3>{hit.title}</h3><p>{hit.snippet}</p>
          <div className="hitMeta"><span>得分 {hit.score.toFixed(3)}</span><span>位置 {hit.start_char}–{hit.end_char}</span><button type="button" onClick={() => void openCitation(hit.chunk_id)}>核对引用</button><button type="button" onClick={() => void navigator.clipboard.writeText(hit.chunk_id)}>复制片段 ID</button></div>
        </article>)}</div>
        {citation && <div className="citation"><div className="panelTitle"><h3>固定快照中的原文</h3><button type="button" onClick={() => setCitation(null)}>关闭</button></div><a href={citation.source_url} target="_blank" rel="noreferrer">{citation.source_url}</a><p>{citation.text}</p><small>SHA-256：{citation.snapshot_sha256}</small></div>}
      </section>
      <section className="panel searchPanel">
        <div className="panelTitle"><div><h2>技术调研</h2><p>根据已审核的来源形成可审查草稿。未配置模型时使用模拟模式。</p></div></div>
        <form className="researchForm" onSubmit={startResearch}>
          <label>问题<input required minLength={10} value={researchQuestion} onChange={(event) => setResearchQuestion(event.target.value)} placeholder="LangGraph 是否适合需要持久化的工作流？" /></label>
          <label>硬约束<input required value={researchConstraints} onChange={(event) => setResearchConstraints(event.target.value)} placeholder="例如：需要人工审核与恢复执行" /></label>
          <label>候选方案（逗号分隔，最多 3 个）<input required value={researchCandidates} onChange={(event) => setResearchCandidates(event.target.value)} /></label>
          <button type="submit" disabled={Boolean(researchId)}>开始调研</button>
        </form>
        {researchId && <p className="empty">调研运行中：{researchId}</p>}
        {researchId && <button type="button" onClick={async () => { await api(`/api/research/${researchId}/cancel`, { method: "POST" }); setResearchId(null); }}>取消运行</button>}
        {research && <div className="researchResult"><strong>状态：{research.status} · 模式：{research.result?.model_mode ?? "—"}</strong>
          <div>{research.events?.map((event, index) => <p key={`${event.at}-${index}`}>{event.stage} · {new Date(event.at).toLocaleTimeString("zh-CN")}</p>)}</div>
          <p>{research.result?.summary ?? research.error_code}</p>
          {research.result && <p>耗时 {research.result.duration_ms} ms · Token：{research.result.usage.total_tokens ?? "未知"}</p>}
          {research.result?.retrieval_trace && <details><summary>证据核查轨迹 · {research.result.retrieval_trace.calls.length} 次检索 · 停止原因：{research.result.retrieval_trace.stop_reason}</summary>
            <p>送入模型的证据字符：{research.result.retrieval_trace.evidence_input_chars}（不等于 Token）</p>
            {research.result.retrieval_trace.calls.map((call, index) => <p key={`${call.stage}-${index}`}>{call.stage === "repair" ? "补检索" : "初检索"} · {call.query} · 命中 {call.hit_count}</p>)}
          </details>}
          {research.result?.claims.map((claim) => <div key={claim.chunk_id}><p>来源原文：{claim.text}</p><button type="button" onClick={() => void openCitation(claim.chunk_id)}>核对原文</button></div>)}
          {research.result?.unknowns.map((item) => <p key={item}>待核查：{item}</p>)}
          {research.result?.evidence.map((item) => <button key={item.chunk_id} type="button" onClick={() => void openCitation(item.chunk_id)}>{item.title} · {item.snapshot_sha256.slice(0, 10)}</button>)}
          {research.card_id && research.card_status === "draft" && <div className="reviewActions"><button type="button" onClick={() => void reviewDecision("approve")}>批准草稿</button><button type="button" onClick={() => void reviewDecision("return")}>退回草稿</button></div>}
          {research.card_status && research.card_status !== "draft" && <p>审核结果：{research.card_status}</p>}
        </div>}
      </section>
      <section className="panel searchPanel">
        <div className="panelTitle"><div><h2>决策库</h2><p>仅展示已批准和需复核的卡片；来源变化后由人工处理。</p></div><button type="button" onClick={() => void loadCards()}>刷新</button></div>
        {cards.length === 0 && <p className="empty">暂无已批准的决策卡。</p>}
        {cards.map((card) => <article className="hit" key={card.id}>
          <h3>{card.content.question}</h3><p>{card.content.summary}</p>
          <p>状态：{card.status} · 证据 {card.content.evidence.length} 条</p>
          {card.stale_source_ids.length > 0 && <p>变更来源：{card.stale_source_ids.join(", ")}</p>}
          <div className="reviewActions">
            {card.status === "needs_review" && <button type="button" onClick={() => void cardAction(card, "keep")}>复核后维持</button>}
            <button type="button" onClick={() => void cardAction(card, "revision")}>修订结论</button>
            <button type="button" onClick={() => void cardAction(card, "archive")}>归档</button>
          </div>
          <details><summary>操作历史（{card.history.length}）</summary>{card.history.map((event, index) => <p key={`${event.at}-${index}`}>{event.action} · {event.note} · {new Date(event.at).toLocaleString("zh-CN")}</p>)}</details>
        </article>)}
      </section>
      <section className="panel searchPanel">
        <div className="panelTitle"><div><h2>检索回归评测</h2><p>粘贴人工核实并冻结的 JSON 题集；仅衡量来源召回、术语召回和引用完整性。</p></div></div>
        <form className="researchForm" onSubmit={runEvaluation}>
          <label>评测集 JSON<textarea rows={8} value={datasetText} onChange={(event) => setDatasetText(event.target.value)} /></label>
          <button type="submit">运行评测</button>
        </form>
        {evaluation && <div className="researchResult">
          <p>模式 {evaluation.mode} · 用例 {evaluation.case_count} 条 · 来源召回 {evaluation.source_recall_at_k ?? "未知"} · Top1 来源命中 {evaluation.source_top1_accuracy ?? "未知"} · 负例拒答 {evaluation.negative_abstention_rate ?? "未知"} · 术语召回 {evaluation.term_recall_at_k ?? "未知"} · 引用有效率 {evaluation.citation_valid_rate ?? "未知"}</p>
          {evaluation.cases.map((item) => <p key={item.id}>{item.id}：命中 {item.hit_count}，来源召回 {item.expected_source_recall ?? "未知"}，术语召回 {item.expected_term_recall ?? "未知"}</p>)}
        </div>}
      </section>
    </main>
  );
}
