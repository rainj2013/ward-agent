// Ward — US Market Data UI

const REFRESH_INTERVAL = 30; // seconds

let countdownTimer = null;
let refreshTimer = null;

// Cache for card data — used to build chat context
const _cardCache = {
  indices: {},
  stocks: {},
};
const _extendedCache = {}; // prefix -> { pre, regular, after, previous_close }

// Extended caches for chat context
const _indexKlineCache = {};    // prefix -> [{date, open, high, low, close, volume}, ...]
const _stockKlineCache = {};    // symbol -> [{date, open, high, low, close, volume}, ...]
const _stockAnalysisCache = {}; // symbol -> string (AI analysis text)
let _indexAnalysisCache = {};   // prefix -> string (index AI analysis text)
let _runtimeStatsRange = '1d';

function fmt(num) {
  if (num === null || num === undefined) return '--';
  return typeof num === 'number'
    ? num.toLocaleString('en-US', { maximumFractionDigits: 2 })
    : num;
}

function pct(color) {
  if (color === null || color === undefined) return '--';
  return color > 0 ? `+${color.toFixed(2)}%` : `${color.toFixed(2)}%`;
}

function setChange(el, value) {
  el.textContent = pct(value);
  el.className = 'change ' + (value > 0 ? 'positive' : value < 0 ? 'negative' : 'neutral');
}

function fillCard(prefix, data) {
  document.getElementById(prefix + '-price').textContent = fmt(data.close);
  setChange(document.getElementById(prefix + '-change'), data.change_pct);
  document.getElementById(prefix + '-open').textContent = fmt(data.open);
  document.getElementById(prefix + '-high').textContent = fmt(data.high);
  document.getElementById(prefix + '-low').textContent = fmt(data.low);
  document.getElementById(prefix + '-volume').textContent = fmt(data.volume);
  // header change always visible
  const hdrChange = document.getElementById(prefix + '-header-change');
  if (hdrChange) {
    hdrChange.textContent = pct(data.change_pct);
    hdrChange.className = 'card-change ' + (data.change_pct > 0 ? 'positive' : data.change_pct < 0 ? 'negative' : 'neutral');
  }
  // Cache for chat context
  const indexNames = { ixic: 'Nasdaq 综合', dji: '道琼斯', spx: '标普500', gold: '黄金' };
  _cardCache.indices[prefix] = {
    name: indexNames[prefix] || prefix,
    close: data.close,
    change: data.change,
    change_pct: data.change_pct,
    open: data.open,
    high: data.high,
    low: data.low,
    volume: data.volume,
  };
}

function showCard(cardId, isHistorical = false) {
  const card = document.getElementById(cardId);
  card.querySelector('.loading').style.display = 'none';
  card.querySelector('.card-body').style.display = 'block';
  const footer = card.querySelector('.card-footer');
  if (footer) footer.style.display = 'flex';
  if (isHistorical) {
    const label = card.querySelector('.card-badge');
    if (label) {
      label.style.display = 'inline-block';
    }
  }
}

function toggleCard(card) {
  const body = card.querySelector('.card-body');
  const footer = card.querySelector('.card-footer');
  const isOpen = body.style.display !== 'none';
  body.style.display = isOpen ? 'none' : 'block';
  if (footer) footer.style.display = isOpen ? 'none' : 'flex';
}

function getNewYorkDateParts(date = new Date()) {
  const parts = new Intl.DateTimeFormat('en-US', {
    timeZone: 'America/New_York',
    weekday: 'short',
    hour: '2-digit',
    minute: '2-digit',
    hourCycle: 'h23',
  }).formatToParts(date);
  return Object.fromEntries(parts.map(part => [part.type, part.value]));
}

// Check if US market is open by New York local time.
// Regular session: Mon-Fri 09:30-16:00 America/New_York.
function isMarketOpen() {
  const ny = getNewYorkDateParts();
  if (ny.weekday === 'Sat' || ny.weekday === 'Sun') return false;

  const minutes = Number(ny.hour) * 60 + Number(ny.minute);
  return minutes >= 9 * 60 + 30 && minutes < 16 * 60;
}

function updateMarketStatus() {
  const dot = document.getElementById('status-dot');
  const text = document.getElementById('status-text');
  const countdown = document.getElementById('refresh-countdown');

  if (isMarketOpen()) {
    dot.className = 'status-dot open';
    text.textContent = '美股交易中';
    countdown.textContent = '';
  } else {
    dot.className = 'status-dot closed';
    text.textContent = '美股已休市';
    countdown.textContent = '';
  }
}

function startCountdown(seconds) {
  let remaining = seconds;
  const countdown = document.getElementById('refresh-countdown');

  if (countdownTimer) clearInterval(countdownTimer);
  countdownTimer = setInterval(() => {
    remaining--;
    if (remaining <= 0) {
      countdown.textContent = '';
      clearInterval(countdownTimer);
    } else {
      countdown.textContent = `${remaining}s 后刷新`;
    }
  }, 1000);
}

function isHistoricalData(data) {
  if (!data || !data.date) return false;
  const today = new Date().toISOString().split('T')[0];
  return data.date !== today;
}

async function loadMarketData() {
  try {
    const resp = await fetch('/api/market-overview');
    const data = await resp.json();

    if (!data.ok) return;

    // Nasdaq Composite
    if (data.nasdaq_composite) {
      fillCard('ixic', data.nasdaq_composite);
      showCard('card-ixic', isHistoricalData(data.nasdaq_composite));
    }

    // Dow Jones
    if (data.dow_jones) {
      fillCard('dji', data.dow_jones);
      showCard('card-dji', isHistoricalData(data.dow_jones));
    }

    // S&P 500
    if (data.sp500) {
      fillCard('spx', data.sp500);
      showCard('card-spx', isHistoricalData(data.sp500));
    }

    // Gold
    if (data.gold) {
      fillCard('gold', data.gold);
      showCard('card-gold', isHistoricalData(data.gold));
    }

    updateMarketStatus();

    // Auto-refresh if market is open
    if (isMarketOpen()) {
      startCountdown(REFRESH_INTERVAL);
      if (refreshTimer) clearTimeout(refreshTimer);
      refreshTimer = setTimeout(() => {
        loadMarketData();
        loadExtendedHours();
      }, REFRESH_INTERVAL * 1000);
    }
  } catch (e) {
    console.error('Failed to load market data:', e);
  }
}

// Map index prefix to ETF symbols for extended hours
const EXTENDED_SYMBOLS = {
  ixic: 'QQQ',
  spx: 'SPY',
  dji: 'DIA',
};

async function loadExtendedHours() {
  const section = document.getElementById('extended-section');
  try {
    const results = await Promise.all([
      fetch('/api/stock/QQQ/extended').then(r => r.json()),
      fetch('/api/stock/SPY/extended').then(r => r.json()),
      fetch('/api/stock/DIA/extended').then(r => r.json()),
    ]);

    const prefixes = ['ixic', 'spx', 'dji'];
    let hasData = false;

    for (let i = 0; i < prefixes.length; i++) {
      const prefix = prefixes[i];
      const d = results[i];
      if (!d.ok) continue;

      hasData = true;

      // Fill pre-market
      const pre = d.pre_market;
      const preEl = document.querySelector(`#ext-${prefix}-pre .ext-slot-price`);
      if (pre && pre.price) {
        const chg = pre.price - d.previous_close;
        const pct = (chg / d.previous_close * 100).toFixed(2);
        preEl.textContent = `${pre.price.toLocaleString()} (${chg >= 0 ? '+' : ''}${pct}%)`;
        preEl.className = `ext-slot-price ${chg >= 0 ? 'positive' : 'negative'}`;
      } else {
        preEl.textContent = '--';
        preEl.className = 'ext-slot-price loading';
      }

      // Fill regular
      const reg = d.regular;
      const regEl = document.querySelector(`#ext-${prefix}-reg .ext-slot-price`);
      if (reg && reg.price) {
        const chg = reg.price - d.previous_close;
        const pct = (chg / d.previous_close * 100).toFixed(2);
        regEl.textContent = `${reg.price.toLocaleString()} (${chg >= 0 ? '+' : ''}${pct}%)`;
        regEl.className = `ext-slot-price ${chg >= 0 ? 'positive' : 'negative'}`;
      } else {
        regEl.textContent = '--';
        regEl.className = 'ext-slot-price loading';
      }

      // Fill after-hours
      const after = d.after_hours;
      const afterEl = document.querySelector(`#ext-${prefix}-after .ext-slot-price`);
      if (after && after.price) {
        const chg = after.price - reg.price;
        const pct = (chg / reg.price * 100).toFixed(2);
        afterEl.textContent = `${after.price.toLocaleString()} (${chg >= 0 ? '+' : ''}${pct}%)`;
        afterEl.className = `ext-slot-price ${chg >= 0 ? 'positive' : 'negative'}`;
      } else {
        afterEl.textContent = '--';
        afterEl.className = 'ext-slot-price loading';
      }

      // Cache for chat context (after variable declarations)
      _extendedCache[prefix] = {
        pre: pre && pre.price ? { price: pre.price } : null,
        regular: reg && reg.price ? { price: reg.price } : null,
        after: after && after.price ? { price: after.price } : null,
        previous_close: d.previous_close,
      };
    }

    if (hasData) {
      section.style.display = 'block';
    }
  } catch (e) {
    console.error('Failed to load extended hours:', e);
  }
}

function renderReportStatus(content, message, jobId) {
  const jobHtml = jobId ? `<div class="analysis-job-meta">Job: <code>${escapeHtml(jobId)}</code> · <a href="/runtime?job_id=${encodeURIComponent(jobId)}" target="_blank" rel="noopener">查看 Trace</a></div>` : '';
  content.innerHTML = `<p class="hint">${escapeHtml(message)}</p>${jobHtml}`;
}

function renderMarketReport(content, report, result, jobId) {
  let html = renderMarkdown(report);
  const data = result && result.data ? result.data : {};
  const s = data.sentiment;
  if (s && s.score !== null && s.score !== undefined) {
    const scoreColor = s.score >= 6 ? '#22c55e' : s.score >= 4 ? '#f59e0b' : '#ef4444';
    const scoreLabel = s.score >= 6 ? '偏多' : s.score >= 4 ? '中性' : '偏空';
    html += `<div class="sentiment-card">
      <div class="sentiment-title">😈 市场情绪评分</div>
      <div class="sentiment-score-row">
        <span class="sentiment-score" style="color:${scoreColor}">${Number(s.score).toFixed(1)}/9</span>
        <span class="sentiment-label" style="color:${scoreColor}">${scoreLabel}</span>
      </div>
      <div class="sentiment-interpretation">${escapeHtml(s.interpretation || '')}</div>
    </div>`;
  }
  if (jobId) {
    html += `<div class="analysis-job-meta">Job: <code>${escapeHtml(jobId)}</code> · <a href="/runtime?job_id=${encodeURIComponent(jobId)}" target="_blank" rel="noopener">查看 Trace</a></div>`;
  }
  renderStreamingHtml(content, html);
}

async function generateReport() {
  const btn = document.getElementById('generate-btn');
  const content = document.getElementById('report-content');
  btn.disabled = true;
  btn.textContent = '生成中...';
  renderReportStatus(content, '分析任务排队中...', null);

  try {
    await runAnalysisJob(
      '/api/analysis-jobs/report',
      (message, data) => {
        const jobId = data && data.job ? data.job.id : null;
        renderReportStatus(content, message, jobId);
      },
      (report, result, job) => {
        renderMarketReport(content, report, result, job && job.id);
      }
    );
  } catch (e) {
    content.innerHTML = `<p class="hint" style="color:#ef4444">请求失败: ${escapeHtml(e.message)}</p>`;
  } finally {
    btn.disabled = false;
    btn.textContent = '重新生成';
  }
}

// Chat — conversation state
let conversationId = localStorage.getItem('ward_conversation_id') ? parseInt(localStorage.getItem('ward_conversation_id')) : null;
let _hasMoreMessages = false;
let _nextBeforeId = null;
let _historyLoaded = false;
let _toolInvokeMap = new Map(); // tool_call_id -> div，正在查询的工具调用
let _lastThinking = null;       // 当前思考指示器 DOM 节点
let _sseBuffer = '';            // SSE 事件跨 TCP 分包的拼接缓冲
let _chatAbortCtrl = null;

function parseSseEvent(rawEvent) {
  const dataLines = rawEvent.replace(/\r\n/g, '\n').split('\n')
    .filter(line => line.startsWith('data:'))
    .map(line => line.slice(5).replace(/^ /, ''));
  if (!dataLines.length) return null;
  return JSON.parse(dataLines.join('\n'));
}

async function streamTextResponse(url, onChunk, onDone) {
  const resp = await fetch(url);
  if (!resp.ok || !resp.body) {
    throw new Error(`HTTP ${resp.status}`);
  }

  const reader = resp.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  let fullText = '';

  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    if (!value) continue;

    buffer += decoder.decode(value, { stream: true });
    const parts = buffer.split(/\r?\n\r?\n/);
    buffer = parts.pop() || '';

    for (const raw of parts) {
      const data = parseSseEvent(raw);
      if (!data) continue;
      if (!data.ok) {
        throw new Error(data.error || '未知错误');
      }
      if (data.chunk) {
        fullText += data.chunk;
        onChunk(fullText, data);
      }
      if (data.done) {
        const finalText = data.report || fullText;
        if (finalText !== fullText) {
          fullText = finalText;
          onChunk(fullText, data);
        }
        onDone(fullText, data);
        return;
      }
    }
  }

  if (buffer.trim()) {
    const data = parseSseEvent(buffer);
    if (data && !data.ok) throw new Error(data.error || '未知错误');
    if (data && data.chunk) {
      fullText += data.chunk;
      onChunk(fullText, data);
    }
    if (data && data.done) {
      const finalText = data.report || fullText;
      onDone(finalText, data);
    }
  }
}

async function runAnalysisJob(createUrl, onStatus, onDone, createOptions = {}) {
  const createResp = await fetch(createUrl, { method: 'POST', ...createOptions });
  if (!createResp.ok) {
    throw new Error(`HTTP ${createResp.status}`);
  }
  const created = await createResp.json();
  if (!created.ok || !created.job) {
    throw new Error(created.error || '创建分析任务失败');
  }
  rememberRuntimeJob(created.job.id);
  onStatus(formatAnalysisJobStatus({ message: '任务已创建', stage: 'queued', job: created.job }), {
    job: created.job,
    stage: 'queued',
    message: '任务已创建',
  });

  const resp = await fetch(`/api/analysis-jobs/${created.job.id}/events`);
  if (!resp.ok || !resp.body) {
    throw new Error(`HTTP ${resp.status}`);
  }

  const reader = resp.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';

  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    if (!value) continue;

    buffer += decoder.decode(value, { stream: true });
    const parts = buffer.split(/\r?\n\r?\n/);
    buffer = parts.pop() || '';

    for (const raw of parts) {
      const data = parseSseEvent(raw);
      if (!data) continue;
      if (!data.ok) throw new Error(data.error || '分析任务失败');
      if (data.message) onStatus(formatAnalysisJobStatus(data), data);
      if (data.done) {
        const job = data.job;
        if (!job || job.status !== 'succeeded' || !job.result) {
          throw new Error((job && job.error) || '分析任务失败');
        }
        onDone(job.result.report || '', job.result, job);
        return;
      }
    }
  }

  throw new Error('分析任务连接中断');
}

function rememberRuntimeJob(jobId) {
  if (!jobId) return;
  const input = document.getElementById('runtime-job-input');
  if (input) input.value = jobId;
}

function renderAnalysisStatus(container, title, message, jobId) {
  const jobHtml = jobId ? `<div class="analysis-job-meta">Job: <code>${escapeHtml(jobId)}</code> · <a href="/runtime?job_id=${encodeURIComponent(jobId)}" target="_blank" rel="noopener">查看 Trace</a></div>` : '';
  container.innerHTML = `${title}<div class="stock-analysis-content"><p class="hint">${escapeHtml(message)}</p>${jobHtml}</div>`;
}

function renderAnalysisReport(container, title, report, jobId) {
  const jobHtml = jobId ? `<div class="analysis-job-meta">Job: <code>${escapeHtml(jobId)}</code> · <a href="/runtime?job_id=${encodeURIComponent(jobId)}" target="_blank" rel="noopener">查看 Trace</a></div>` : '';
  renderStreamingHtml(container, `${title}<div class="stock-analysis-content">${renderMarkdown(report)}${jobHtml}</div>`);
}

function renderChatJobCard(job) {
  if (!job || !job.id) return '';
  const symbols = Array.isArray(job.symbols) ? job.symbols.join(' / ') : '';
  const typeLabel = job.type === 'stock_comparison' ? '多股对比 Team' : (job.type || '后台任务');
  const traceUrl = job.trace_url || `/runtime?job_id=${encodeURIComponent(job.id)}`;
  return `<div class="chat-job-card" id="chat-job-${escapeHtml(job.id)}">
    <div class="chat-job-title">${escapeHtml(typeLabel)}</div>
    ${symbols ? `<div class="chat-job-symbols">${escapeHtml(symbols)}</div>` : ''}
    <div class="chat-job-meta">Job: <code>${escapeHtml(job.id)}</code></div>
    <div class="chat-job-status">任务运行中，完成后会自动回填结果。</div>
    <a href="${escapeHtml(traceUrl)}" target="_blank" rel="noopener">查看 Team Trace</a>
  </div>`;
}

function persistAssistantMessage(conversationId, messageId, content) {
  if (!conversationId || !messageId || !content) return;
  fetch(`/api/chat/${conversationId}/messages/${messageId}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ content }),
  }).catch(() => {});
}

function pollChatJobResult(job, replyContent, getIntroText, options = {}) {
  if (!job || !job.id) return;
  let attempts = 0;
  const timer = setInterval(async () => {
    attempts += 1;
    try {
      const resp = await fetch(`/api/analysis-jobs/${encodeURIComponent(job.id)}`);
      const data = await resp.json();
      if (!data.ok || !data.job) throw new Error(data.error || '任务状态获取失败');
      const snapshot = data.job;
      const card = document.getElementById(`chat-job-${job.id}`);
      if (card) {
        const status = card.querySelector('.chat-job-status');
        if (status) status.textContent = snapshot.stage_message || snapshot.status || '任务运行中';
      }
      if (snapshot.status === 'succeeded' && snapshot.result) {
        clearInterval(timer);
        const intro = getIntroText ? getIntroText() : '';
        const report = snapshot.result.report || '';
        const persistedContent = `${intro}\n\n${report}`.trim();
        const jobHtml = renderChatJobCard({ ...job, trace_url: `/runtime?job_id=${job.id}` }).replace(
          '任务运行中，完成后会自动回填结果。',
          '任务已完成。'
        );
        replyContent.innerHTML = `${renderMarkdown(intro)}${jobHtml}<div class="chat-job-result">${renderMarkdown(report)}</div>`;
        persistAssistantMessage(options.conversationId, options.messageId, persistedContent);
        const scrollContainer = replyContent.closest('.chat-messages');
        if (scrollContainer) scrollContainer.scrollTop = scrollContainer.scrollHeight;
      } else if (snapshot.status === 'failed') {
        clearInterval(timer);
        if (card) {
          card.classList.add('error');
          const status = card.querySelector('.chat-job-status');
          if (status) status.textContent = snapshot.error || '任务失败';
        }
      }
      if (attempts >= 180) clearInterval(timer);
    } catch (_) {
      if (attempts >= 180) clearInterval(timer);
    }
  }, 1000);
}

async function loadRuntimeStats(range = _runtimeStatsRange, btn = null) {
  _runtimeStatsRange = range;
  document.querySelectorAll('.runtime-range-btn').forEach(el => {
    el.classList.toggle('active', el.dataset.range === range);
  });
  if (btn) btn.classList.add('active');

  const container = document.getElementById('runtime-stats');
  if (!container) return;
  container.innerHTML = '<div class="runtime-muted">加载运行统计中...</div>';

  try {
    const resp = await fetch(`/api/runtime/stats?range=${encodeURIComponent(range)}`);
    const data = await resp.json();
    if (!data.ok) throw new Error(data.error || '统计加载失败');
    renderRuntimeStats(data.stats);
  } catch (e) {
    container.innerHTML = `<div class="runtime-muted">统计加载失败：${escapeHtml(e.message)}</div>`;
  }
}

function loadRuntimeJobFromUrl() {
  const params = new URLSearchParams(window.location.search);
  const jobId = params.get('job_id');
  if (!jobId) return;
  const input = document.getElementById('runtime-job-input');
  if (input) input.value = jobId;
  loadRuntimeTrace();
}

function renderRuntimeStats(stats) {
  const container = document.getElementById('runtime-stats');
  if (!container) return;
  const items = [
    ['任务数', stats.jobs_total],
    ['成功 / 失败', `${stats.jobs_succeeded} / ${stats.jobs_failed}`],
    ['缓存命中率', `${Math.round((stats.cache_hit_rate || 0) * 100)}%`],
    ['LLM 调用', stats.llm_calls],
    ['Tokens', fmtRuntimeNumber(stats.total_tokens)],
    ['平均耗时', formatDurationMs(stats.avg_duration_ms)],
  ];
  container.innerHTML = items.map(([label, value]) => `
    <div class="runtime-stat">
      <div class="runtime-stat-label">${escapeHtml(label)}</div>
      <div class="runtime-stat-value">${escapeHtml(String(value ?? '--'))}</div>
    </div>
  `).join('');
}

async function loadRuntimeTrace() {
  const input = document.getElementById('runtime-job-input');
  const container = document.getElementById('runtime-trace');
  if (!input || !container) return;
  const jobId = input.value.trim();
  if (!jobId) {
    container.innerHTML = '<div class="runtime-muted">请输入 job id。</div>';
    return;
  }
  container.innerHTML = '<div class="runtime-muted">加载 trace 中...</div>';

  try {
    const resp = await fetch(`/api/analysis-jobs/${encodeURIComponent(jobId)}/trace`);
    const data = await resp.json();
    if (!data.ok) throw new Error(data.error || 'Trace 加载失败');
    renderRuntimeTrace(data.job, data.events || []);
  } catch (e) {
    container.innerHTML = `<div class="runtime-muted">Trace 加载失败：${escapeHtml(e.message)}</div>`;
  }
}

function renderRuntimeTrace(job, events) {
  const container = document.getElementById('runtime-trace');
  if (!container) return;
  const usage = job.usage || {};
  const summary = [
    ['状态', job.status],
    ['类型', job.type],
    ['耗时', formatDurationMs(job.duration_ms)],
    ['Tokens', fmtRuntimeNumber(usage.total_tokens || 0)],
  ].map(([label, value]) => `
    <div class="runtime-stat">
      <div class="runtime-stat-label">${escapeHtml(label)}</div>
      <div class="runtime-stat-value">${escapeHtml(String(value ?? '--'))}</div>
    </div>
  `).join('');

  const teamOverview = renderRuntimeTeamOverview(job, events);
  const eventHtml = events.map(ev => {
    const data = ev.data ? JSON.stringify(ev.data, null, 2) : '';
    return `
      <div class="runtime-event">
        <div class="runtime-event-time">${escapeHtml(formatTraceTime(ev.created_at))}</div>
        <div class="runtime-event-stage">${escapeHtml(ev.stage || ev.event || '--')}</div>
        <div class="runtime-event-message">${escapeHtml(ev.message || '')}</div>
        <div class="runtime-event-duration">${escapeHtml(formatDurationMs(ev.duration_ms))}</div>
        ${data ? `<div class="runtime-event-data">${escapeHtml(data)}</div>` : ''}
      </div>
    `;
  }).join('');

  container.innerHTML = `
    <div class="runtime-trace-summary">${summary}</div>
    ${teamOverview}
    ${eventHtml || '<div class="runtime-muted">暂无事件。</div>'}
  `;
}

function renderRuntimeTeamOverview(job, events) {
  if (!job || job.type !== 'stock_comparison') return '';

  const plan = events.find(ev => ev.event === 'leader_plan');
  const workers = events.filter(ev => ev.event === 'worker_done');
  const synthesisStart = events.find(ev => ev.stage === 'leader_synthesis' && ev.event === 'llm_call_start');
  const synthesisEnd = events.find(ev => ev.stage === 'leader_synthesis' && ev.event === 'llm_call_end');
  const verification = events.find(ev => ev.event === 'verification_passed' || ev.event === 'verification_failed');
  const symbols = plan && plan.data && plan.data.symbols
    ? plan.data.symbols.join(' / ')
    : ((job.payload && job.payload.symbols) || []).join(' / ');

  const workerHtml = workers.length ? workers.map(ev => {
    const data = ev.data || {};
    const ok = data.ok !== false;
    const symbol = data.symbol || '--';
    const trend = data.trend && data.trend.status ? data.trend.status : '--';
    const klineCount = data.data_quality && data.data_quality.kline_count !== undefined ? data.data_quality.kline_count : '--';
    return `<div class="runtime-team-worker ${ok ? 'ok' : 'error'}">
      <div class="runtime-team-worker-symbol">${escapeHtml(symbol)}</div>
      <div class="runtime-team-worker-meta">${ok ? '完成' : '失败'} · 趋势 ${escapeHtml(String(trend))} · K线 ${escapeHtml(String(klineCount))}</div>
    </div>`;
  }).join('') : '<div class="runtime-muted">Worker 尚未完成。</div>';

  const verifierData = verification && verification.data ? verification.data : null;
  const verifierPassed = verifierData ? verifierData.passed : null;
  const warnings = verifierData && verifierData.warnings ? verifierData.warnings : [];
  const errors = verifierData && verifierData.errors ? verifierData.errors : [];

  return `<div class="runtime-team">
    <div class="runtime-team-title">Team Overview${symbols ? ` · ${escapeHtml(symbols)}` : ''}</div>
    <div class="runtime-team-grid">
      <div class="runtime-team-card">
        <div class="runtime-team-card-label">Leader</div>
        <div class="runtime-team-card-value">${plan ? '计划已生成' : '等待计划'}</div>
        <div class="runtime-team-card-note">${synthesisEnd ? '聚合完成' : synthesisStart ? '正在聚合' : '等待 Worker'}</div>
      </div>
      <div class="runtime-team-card runtime-team-workers-card">
        <div class="runtime-team-card-label">Workers</div>
        <div class="runtime-team-workers">${workerHtml}</div>
      </div>
      <div class="runtime-team-card ${verifierPassed === false ? 'error' : verifierPassed === true ? 'ok' : ''}">
        <div class="runtime-team-card-label">Verifier</div>
        <div class="runtime-team-card-value">${verifierPassed === true ? '验证通过' : verifierPassed === false ? '验证失败' : '等待验证'}</div>
        ${errors.length ? `<div class="runtime-team-card-note error">${escapeHtml(errors.join('；'))}</div>` : ''}
        ${warnings.length ? `<div class="runtime-team-card-note">${escapeHtml(warnings.join('；'))}</div>` : ''}
      </div>
    </div>
  </div>`;
}

function refreshRuntimePanel() {
  loadRuntimeStats(_runtimeStatsRange);
}

function formatDurationMs(ms) {
  if (ms === null || ms === undefined) return '--';
  if (ms < 1000) return `${ms}ms`;
  return `${(ms / 1000).toFixed(1)}s`;
}

function fmtRuntimeNumber(value) {
  if (value === null || value === undefined) return '--';
  return Number(value).toLocaleString('en-US');
}

function formatTraceTime(value) {
  if (!value) return '--';
  const d = new Date(value + (value.endsWith('Z') ? '' : 'Z'));
  if (Number.isNaN(d.getTime())) return value.slice(11, 19);
  return d.toLocaleTimeString('zh-CN', { hour12: false });
}

function formatAnalysisJobStatus(data) {
  const eventData = data.data || {};
  const job = data.job || {};
  const stage = data.stage || job.stage;
  let message = data.message || job.stage_message || '分析任务处理中';

  if (stage === 'queued') {
    const pos = eventData.queue_position || job.queue_position;
    const wait = eventData.estimated_wait_seconds;
    if (pos) message += `，前面还有 ${Math.max(pos - 1, 0)} 个任务`;
    if (wait) message += `，预计等待约 ${wait} 秒`;
  }

  if (stage === 'cache_check') {
    message = '正在检查是否已有可复用分析';
  } else if (stage === 'cache_hit') {
    message = '命中缓存，已复用现有分析';
  } else if (stage === 'fetching_data') {
    message = data.event === 'stage_end' ? '基础数据获取完成' : '正在获取行情、K线、新闻和财务数据';
  } else if (stage === 'sentiment_analysis') {
    message = data.event === 'llm_call_end' ? '市场情绪分析完成' : '正在生成市场情绪分析';
  } else if (stage === 'llm_generating') {
    message = data.event === 'llm_call_end' ? '模型分析报告生成完成' : '正在等待模型生成分析报告';
  } else if (stage === 'leader_plan') {
    message = 'Leader 已生成任务计划';
  } else if (stage === 'worker_fetch') {
    message = data.event === 'stage_end' ? '所有 Worker 摘要已完成' : 'Worker 正在获取并整理标的数据';
  } else if (stage === 'leader_synthesis') {
    message = data.event === 'llm_call_end' ? 'Leader 对比报告生成完成' : 'Leader 正在聚合 Worker 摘要';
  } else if (stage === 'verifying') {
    message = data.event === 'verification_passed' ? 'Verifier 验证通过' : data.event === 'verification_failed' ? 'Verifier 验证失败' : 'Verifier 正在检查报告';
  } else if (stage === 'execute_handler') {
    message = '正在执行分析任务';
  } else if (stage === 'succeeded' && eventData.cache_hit) {
    message = '命中缓存，已复用现有分析';
  }

  return message;
}

async function initChat() {
  if (!document.getElementById('chat-messages')) {
    return;
  }
  if (!conversationId) {
    _historyLoaded = false; // fresh conversation
    return;
  }
  try {
    const res = await fetch(`/api/history/${conversationId}/messages?limit=10`);
    const data = await res.json();
    if (data.ok && data.messages && data.messages.length) {
      _hasMoreMessages = data.has_more;
      _nextBeforeId = data.next_before_id;
      renderMessages(data.messages);
      _historyLoaded = true;
    } else {
      _historyLoaded = true; // no messages but conversation exists
    }
  } catch (_) {
    _historyLoaded = false;
  }
}

function _msgToDiv(msg) {
  const div = document.createElement('div');
  div.className = `chat-msg ${msg.role === 'user' ? 'user' : 'assistant'}`;
  if (msg.role === 'user') {
    div.textContent = msg.content;
  } else {
    const content = msg.content || '';
    const job = extractChatJobFromContent(content);
    if (job) {
      const intro = extractChatJobIntro(content);
      div.innerHTML = `${renderMarkdown(content)}${renderChatJobCard(job)}`;
      pollChatJobResult(job, div, () => intro, {
        conversationId,
        messageId: msg.id,
      });
    } else {
      div.innerHTML = renderMarkdown(content);
    }
  }
  return div;
}

function extractChatJobFromContent(content) {
  const match = String(content || '').match(/\/runtime\?job_id=([A-Za-z0-9_-]+)/);
  if (!match) return null;
  const symbolsMatch = String(content || '').match(/已为\s+(.+?)\s+创建多股对比/);
  const symbols = symbolsMatch
    ? symbolsMatch[1].split(/[、,\s]+/).filter(Boolean)
    : [];
  return {
    id: match[1],
    type: 'stock_comparison',
    symbols,
    trace_url: `/runtime?job_id=${match[1]}`,
  };
}

function extractChatJobIntro(content) {
  const lines = String(content || '').split('\n').map(line => line.trim()).filter(Boolean);
  return lines.find(line => line.includes('/runtime?job_id=')) || String(content || '').trim();
}

function renderMessages(messages, prepend = false) {
  const container = document.getElementById('chat-messages');
  const hint = container.querySelector('.hint');
  const loadMoreBtn = document.getElementById('chat-load-more-btn');

  if (prepend) {
    // prepend: older messages from "load more" — insert above current messages.
    // messages come ASC [oldest→newest]; we want TOP chronological order.
    // Strategy: save existing messages, clear container, rebuild as:
    // [btn, ...newMessages, ...existingMessages]
    const btn = document.getElementById('chat-load-more-btn');
    const existingMsgs = Array.from(container.querySelectorAll('.chat-msg'));
    if (btn) btn.remove();
    container.innerHTML = '';
    // new older messages at top
    for (const msg of messages) {
      container.appendChild(_msgToDiv(msg));
    }
    // then existing messages
    for (const div of existingMsgs) {
      container.appendChild(div);
    }
    if (btn) container.insertBefore(btn, container.firstChild);
  } else {
    // Initial / full render: clear and show all messages.
    // Backend returns DESC (newest→oldest) for initial load; reverse to oldest→newest.
    const btn = document.getElementById('chat-load-more-btn');
    if (btn) btn.remove(); // remove button before innerHTML = ''
    container.innerHTML = '';
    const sorted = [...messages].reverse();
    for (const msg of sorted) {
      container.appendChild(_msgToDiv(msg));
    }
    if (btn) container.insertBefore(btn, container.firstChild);
    if (hint) hint.remove();
    // Scroll to bottom so newest message is visible
    container.scrollTop = container.scrollHeight;
  }
  // sync loadMoreBtn visibility
  if (loadMoreBtn) loadMoreBtn.style.display = _hasMoreMessages ? 'block' : 'none';
}

async function loadMoreMessages() {
  if (!_hasMoreMessages || !conversationId) return;
  const btn = document.getElementById('chat-load-more-btn');
  btn.disabled = true;
  btn.textContent = '加载中...';
  try {
    const url = `/api/history/${conversationId}/messages?limit=10&before_id=${_nextBeforeId}`;
    const res = await fetch(url);
    const data = await res.json();
    if (data.ok && data.messages.length) {
      _hasMoreMessages = data.has_more;
      _nextBeforeId = data.next_before_id;
      renderMessages(data.messages, true);
    } else {
      _hasMoreMessages = false;
      btn.style.display = 'none';
    }
  } catch (_) {}
  btn.disabled = false;
  btn.textContent = '加载更多消息';
}

async function sendChat() {
  const input = document.getElementById('chat-input');
  const btn = document.getElementById('chat-send-btn');
  const message = input.value.trim();
  if (!message) return;

  input.value = '';
  const isCancelling = btn.dataset.thinking === '1';
  if (isCancelling) {
    btn.dataset.thinking = '0';
    if (_chatAbortCtrl) _chatAbortCtrl.abort();
    fetch(`/api/chat/${conversationId || 0}/cancel`, { method: 'POST' }).catch(() => {});
    return;
  }
  btn.dataset.thinking = '1';
  btn.textContent = '取消';

  // AbortController for cancelling the in-flight request
  const abortCtrl = new AbortController();
  _chatAbortCtrl = abortCtrl;
  const abortSignal = abortCtrl.signal;

  const container = document.getElementById('chat-messages');
  const hint = container.querySelector('.hint');
  if (hint) hint.remove();

  // Load existing conversation history if we have a conversation_id (e.g. after page refresh)
  if (conversationId && !_historyLoaded) {
    try {
      const res = await fetch(`/api/history/${conversationId}/messages?limit=10`);
      const data = await res.json();
      if (data.ok && data.messages && data.messages.length) {
        _hasMoreMessages = data.has_more;
        _nextBeforeId = data.next_before_id;
        renderMessages(data.messages);
      }
      _historyLoaded = true;
    } catch (_) {}
  }

  const userDiv = document.createElement('div');
  userDiv.className = 'chat-msg user';
  userDiv.textContent = message;
  container.appendChild(userDiv);
  container.scrollTop = container.scrollHeight;

  const assistantDiv = document.createElement('div');
  assistantDiv.className = 'chat-msg assistant';
  const answerDiv = document.createElement('div');
  const replyContent = document.createElement('div'); // 专门放回答文本，chunk只更新这个
  answerDiv.appendChild(replyContent);
  assistantDiv.appendChild(answerDiv);
  container.appendChild(assistantDiv);

  const pendingDiv = document.createElement('div');
  pendingDiv.className = 'chat-thinking';
  pendingDiv.innerHTML = '<span class="think-label">🤔 思考中</span><span class="think-text"></span>';
  answerDiv.insertAdjacentElement('afterbegin', pendingDiv);
  _lastThinking = pendingDiv;
  container.scrollTop = container.scrollHeight;

  try {
    // Build full context — everything loaded in the UI
    const ctx = { indices: [], stocks: [], index_klines: {}, stock_klines: {}, stock_analyses: {}, index_analyses: {}, extended_hours: {} };

    // Today's snapshot — indices
    for (const prefix of ['ixic', 'dji', 'spx']) {
      const d = _cardCache.indices[prefix];
      if (d && d.close != null) {
        ctx.indices.push({
          name: d.name,
          close: parseFloat(d.close),
          change: parseFloat(d.change),
          change_pct: parseFloat(d.change_pct),
          open: parseFloat(d.open),
          high: parseFloat(d.high),
          low: parseFloat(d.low),
          volume: parseFloat(d.volume),
        });
      }
    }
    // Today's snapshot — stocks
    for (const [sym, d] of Object.entries(_cardCache.stocks)) {
      if (d && d.close != null) {
        ctx.stocks.push({
          symbol: sym,
          name: d.name,
          close: parseFloat(d.close),
          change: parseFloat(d.change),
          change_pct: parseFloat(d.change_pct),
          open: parseFloat(d.open),
          high: parseFloat(d.high),
          low: parseFloat(d.low),
          volume: parseFloat(d.volume),
        });
      }
    }
    // 60-day klines — indices
    for (const [prefix, bars] of Object.entries(_indexKlineCache)) {
      if (bars && bars.length) ctx.index_klines[prefix] = bars;
    }
    // 60-day klines — stocks
    for (const [sym, bars] of Object.entries(_stockKlineCache)) {
      if (bars && bars.length) ctx.stock_klines[sym] = bars;
    }
    // Extended hours data — indices
    for (const [prefix, data] of Object.entries(_extendedCache)) {
      if (data) ctx.extended_hours = ctx.extended_hours || {};
      ctx.extended_hours[prefix] = data;
    }
    // Stock AI analyses
    for (const [sym, text] of Object.entries(_stockAnalysisCache)) {
      if (text) ctx.stock_analyses[sym] = text;
    }
    // Index AI reports (individual)
    for (const [prefix, report] of Object.entries(_indexAnalysisCache)) {
      if (report) ctx.index_analyses[prefix] = report;
    }

    const payload = { conversation_id: conversationId || 0, message };
    if (ctx.indices.length || ctx.stocks.length || Object.keys(ctx.index_klines).length || Object.keys(ctx.stock_klines).length || Object.keys(ctx.stock_analyses).length || Object.keys(ctx.index_analyses).length) {
      payload.context = ctx;
    }

    // Use SSE streaming endpoint
    const resp = await fetch('/api/chat/stream', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
      signal: abortSignal,
    });
    const reader = resp.body.getReader();
    const decoder = new TextDecoder();
    let streamClosed = false;
    let chatDone = false;
    let fullReply = '';
    let activeJob = null;
    let assistantMessageId = null;
    let convId = conversationId;
    const reqStart = Date.now();

    while (!streamClosed && !chatDone) {
      const { value, done: readerDone } = await reader.read();
      streamClosed = readerDone;
      if (!value) continue;

      // Reusable buffer to reassemble SSE events split across TCP packets
      _sseBuffer = (_sseBuffer || '') + decoder.decode(value, { stream: !streamClosed });

      // Split on SSE event boundaries; keep the trailing partial event buffered.
      let parts = _sseBuffer.split(/\r?\n\r?\n/);
      // Last part may be incomplete — keep it in buffer
      _sseBuffer = parts.pop() || '';

      for (const raw of parts) {
        let data;
        try {
          data = parseSseEvent(raw);
          if (!data) continue;
        } catch(e) {
          console.error('[WARD] SSE parse error:', e.message, 'raw:', raw.slice(0, 200));
          continue;
        }

        // 先处理工具调用/结果，它们没有 ok 字段，不能用 !data.ok 判断
        if (data.tool_call) {
          if (_lastThinking && !_lastThinking.querySelector('.think-text').textContent.trim()) {
            _lastThinking.remove();
            _lastThinking = null;
          }
          const toolDiv = document.createElement('div');
          toolDiv.className = 'chat-tool-invoke';
          const toolName = data.tool_call.name || 'unknown';
          const callId = data.tool_call.id || null;
          toolDiv.textContent = '🔧 正在查询 ' + toolName + '...';
          toolDiv.dataset.toolName = toolName;
          toolDiv.dataset.callId = callId;
          answerDiv.insertAdjacentElement('afterbegin', toolDiv);
          container.scrollTop = container.scrollHeight;
          _toolInvokeMap.set(callId, toolDiv);
          continue;
        }
        if (data.tool_result) {
          const resultId = data.tool_result.id || '';
          const toolDiv = _toolInvokeMap.get(resultId);
          if (!toolDiv) {
            console.warn('[WARD] tool_result no match for id:', resultId);
          } else {
            const ok = data.tool_result.ok;
            toolDiv.classList.toggle('ok', !!ok);
            toolDiv.classList.toggle('error', !ok);
            toolDiv.textContent = ok
              ? '✅ ' + (data.tool_result.name || toolDiv.dataset.toolName) + ' 查询成功'
              : '❌ ' + (data.tool_result.name || toolDiv.dataset.toolName) + ' 查询失败';
            container.scrollTop = container.scrollHeight;
          }
          continue;
        }

        // 通用对话事件
        if (!data.ok) {
          replyContent.textContent = `出错: ${data.error}`;
          chatDone = true;
          break;
        }
        convId = data.conversation_id;
        if (convId && conversationId !== convId) {
          conversationId = convId;
          localStorage.setItem('ward_conversation_id', convId);
        }
        if (data.assistant_message_id) {
          assistantMessageId = data.assistant_message_id;
        }
        if (data.job) {
          activeJob = data.job;
          if (_lastThinking) {
            _lastThinking.remove();
            _lastThinking = null;
          }
          replyContent.insertAdjacentHTML('beforeend', renderChatJobCard(data.job));
          container.scrollTop = container.scrollHeight;
        }
        if (data.chunk) {
          if (_lastThinking && !_lastThinking.querySelector('.think-text').textContent.trim()) {
            _lastThinking.remove();
            _lastThinking = null;
          }
          fullReply += data.chunk;
          replyContent.innerHTML = (typeof marked !== 'undefined' ? marked.parse(fullReply) : escapeHtml(fullReply))
            + (activeJob ? renderChatJobCard(activeJob) : '');
          container.scrollTop = container.scrollHeight;
        }
        if (data.done) {
          if (data.cancelled) {
            // Cancelled mid-stream — remove thinking indicator, show brief notice
            if (_lastThinking) { _lastThinking.remove(); _lastThinking = null; }
            _toolInvokeMap.clear(); // 清理工具调用指示器
            const cancelNotice = document.createElement('div');
            cancelNotice.className = 'chat-tool-invoke';
            cancelNotice.textContent = '⚠️ 已取消';
            answerDiv.insertAdjacentElement('afterbegin', cancelNotice);
          } else {
            replyContent.innerHTML = (typeof marked !== 'undefined' ? marked.parse(fullReply) : escapeHtml(fullReply))
              + (activeJob ? renderChatJobCard(activeJob) : '');
          }
          conversationId = convId;
          localStorage.setItem('ward_conversation_id', convId);
          // Streaming already put user + assistant messages into the DOM.
          // done: only sync pagination state — never re-render.
          if (data.has_more !== undefined) _hasMoreMessages = data.has_more;
          if (data.next_before_id !== undefined) _nextBeforeId = data.next_before_id;
          const loadMoreBtn = document.getElementById('chat-load-more-btn');
          if (loadMoreBtn) loadMoreBtn.style.display = _hasMoreMessages ? 'block' : 'none';
          if (activeJob) {
            pollChatJobResult(activeJob, replyContent, () => fullReply, {
              conversationId: convId,
              messageId: assistantMessageId,
            });
          }
          _toolInvokeMap.clear(); // 重置工具调用 map
          _lastThinking = null;  // 重置，避免下一条消息的 thinking 追加到旧 div
          chatDone = true;
        } else if (data.thinking) {
          // 模型思考中 → 累积追加到同一个 div，保持顺序
          if (_lastThinking) {
            _lastThinking.querySelector('.think-text').textContent += data.thinking;
          } else {
            const thinkDiv = document.createElement('div');
            thinkDiv.className = 'chat-thinking';
            thinkDiv.innerHTML = '<span class="think-label">🤔 思考中</span><span class="think-text"></span>';
            answerDiv.insertAdjacentElement('afterbegin', thinkDiv);
            container.scrollTop = container.scrollHeight;
            _lastThinking = thinkDiv;
          }
        }
        // else: unknown event type — ignore
      }
    }

    if (!chatDone && _sseBuffer.trim()) {
      try {
        const data = parseSseEvent(_sseBuffer);
        if (data && !data.ok) {
          replyContent.textContent = `出错: ${data.error}`;
        } else if (data && data.chunk) {
          fullReply += data.chunk;
          replyContent.innerHTML = renderMarkdown(fullReply)
            + (activeJob ? renderChatJobCard(activeJob) : '');
        }
        if (data && data.done) {
          conversationId = data.conversation_id || convId;
          localStorage.setItem('ward_conversation_id', conversationId);
        }
      } catch(e) {
        console.error('[WARD] final SSE parse error:', e.message);
      }
    }
  } catch (e) {
    if (e.name === 'AbortError') {
      if (_lastThinking) { _lastThinking.remove(); _lastThinking = null; }
    } else {
      if (_lastThinking) { _lastThinking.remove(); _lastThinking = null; }
      replyContent.textContent = `请求失败: ${e.message}`;
      container.scrollTop = container.scrollHeight;
    }
  } finally {
    _sseBuffer = '';
    _chatAbortCtrl = null;
    btn.dataset.thinking = '0';
    btn.textContent = '发送';
  }
}

function handleIndexAnalyze(prefix, name, btn) {
    const container = document.getElementById('analysis-' + prefix);
    const savedReport = _indexAnalysisCache && _indexAnalysisCache[prefix];
    const wasVisible = container && container.style.display === 'block';
    if (wasVisible && savedReport) {
      container.style.display = 'none';
      return;
    }
    btn.textContent = '分析中...';
    btn.disabled = true;
    container.style.display = 'block';
    container.innerHTML = '<h3>' + name + ' 分析报告</h3><div class="stock-analysis-content"><p class="hint">分析任务排队中...</p></div>';
    runAnalysisJob(
      '/api/analysis-jobs/index/' + prefix,
      (message, data) => {
        const jobId = data && data.job ? data.job.id : null;
        renderAnalysisStatus(container, '<h3>' + name + ' 分析报告</h3>', message, jobId);
       },
       (report, result, job) => {
         btn.textContent = '分析';
        btn.disabled = false;
        renderAnalysisReport(container, '<h3>' + name + ' 分析报告</h3>', report, job && job.id);
        if (!_indexAnalysisCache) _indexAnalysisCache = {};
        _indexAnalysisCache[prefix] = report;
      }
    )
      .catch(err => {
        btn.textContent = '分析';
        btn.disabled = false;
        container.innerHTML = '<h3>分析报告</h3><div class="stock-error">请求失败: ' + err.message + '</div>';
        container.style.display = 'block';
      });
  }

function handleAnalyzeAction(symbol, name, btn) {
    const container = document.getElementById('analysis-' + symbol);
    const savedReport = _stockAnalysisCache[symbol];
    const wasVisible = container && container.style.display === 'block';
    if (wasVisible && savedReport) {
      container.style.display = 'none';
      return;
    }
    btn.textContent = '分析中...';
    btn.disabled = true;
    container.style.display = 'block';
    container.innerHTML = '<h3>' + name + ' 分析报告</h3><div class="stock-analysis-content"><p class="hint">分析任务排队中...</p></div>';
    runAnalysisJob(
      `/api/analysis-jobs/stock/${symbol}`,
      (message, data) => {
        const jobId = data && data.job ? data.job.id : null;
        renderAnalysisStatus(container, '<h3>' + name + ' 分析报告</h3>', message, jobId);
       },
       (report, result, job) => {
         btn.textContent = '分析';
        btn.disabled = false;
        renderAnalysisReport(container, '<h3>' + name + ' 分析报告</h3>', report, job && job.id);
        _stockAnalysisCache[symbol] = report;
      }
    )
      .catch(err => {
        btn.textContent = '分析';
        btn.disabled = false;
        container.innerHTML = '<h3>分析报告（' + symbol + '）</h3><div class="stock-error">请求失败: ' + err.message + '</div>';
        container.style.display = 'block';
      });
  }

  function handleChartAction(symbol, name, btn) {
    const container = document.getElementById('chart-' + symbol);
    const savedData = _stockKlineCache[symbol];
    const wasVisible = container && container.style.display === 'block';
    if (wasVisible && savedData) {
      container.style.display = 'none';
      return;
    }
    container.style.display = 'block';
    if (savedData && savedData.length) {
      renderStockChart(container, symbol, name, savedData);
      return;
    }
    container.innerHTML = '<div class="stock-chart-loading">加载K线数据中...</div>';
    fetch(`/api/stock/${symbol}/kline?days=60`)
      .then(r => r.json())
      .then(data => {
        if (!data.ok || !data.data || data.data.length === 0) {
          container.innerHTML = '<div class="stock-error">K线数据加载失败</div>';
          return;
        }
        _stockKlineCache[symbol] = data.data;
        renderStockChart(container, symbol, name, data.data);
      })
      .catch(err => {
        container.innerHTML = '<div class="stock-error">请求失败: ' + err.message + '</div>';
      });
  }

document.addEventListener('DOMContentLoaded', () => {
  if (document.getElementById('market-cards')) {
    loadMarketData();
    loadExtendedHours();
  }
  if (document.getElementById('runtime-stats')) {
    loadRuntimeStats('1d');
    loadRuntimeJobFromUrl();
  }

  // Delegated button clicks — data-action buttons inside stock cards
  document.addEventListener('click', (e) => {
    const btn = e.target.closest('[data-action]');
    if (!btn) return;
    e.stopPropagation();
    const action = btn.dataset.action;
    const symbol = btn.dataset.symbol;
    const name = btn.dataset.name;
    if (action === 'analyze') {
      handleAnalyzeAction(symbol, name, btn);
    } else if (action === 'chart') {
      handleChartAction(symbol, name, btn);
    }
  });

  // Delegated card clicks — click card (non-button area) to load quote
  document.addEventListener('click', (e) => {
    const card = e.target.closest('.stock-result-card');
    if (!card) return;
    if (e.target.closest('[data-action]')) return;
    if (e.target.closest('.stock-analysis-card')) return;
    if (e.target.closest('.stock-chart-container')) return;
    const symbolEl = card.querySelector('.stock-result-symbol');
    const nameEl = card.querySelector('.stock-result-name');
    if (!symbolEl || !nameEl) return;
    const symbol = symbolEl.textContent;
    const name = nameEl.textContent;
    loadStockQuote(symbol, name, card);
  });
});

// Stock search
async function searchStock() {
  const q = document.getElementById('stock-search-input').value.trim();
  const results = document.getElementById('stock-results');
  if (!q) return;

  results.innerHTML = '<div class="stock-loading">搜索中...</div>';

  try {
    const resp = await fetch(`/api/stock/search?q=${encodeURIComponent(q)}`);
    const data = await resp.json();
    if (!data.ok || data.results.length === 0) {
      results.innerHTML = '<div class="stock-error">未找到相关股票</div>';
      return;
    }
    // Show search results list
    results.innerHTML = '';
    for (const stock of data.results) {
      const card = document.createElement('div');
      card.className = 'stock-result-card';
      card.innerHTML = `<div class="stock-result-header">
        <span class="stock-result-symbol">${stock.symbol}</span>
        <span class="stock-result-name">${stock.name}</span>
      </div>`;
      card.onclick = () => loadStockQuote(stock.symbol, stock.name, card);
      results.appendChild(card);
    }
  } catch (e) {
    results.innerHTML = `<div class="stock-error">搜索失败: ${e.message}</div>`;
  }
}

async function loadStockQuote(symbol, name, card) {
  // Save chart/analysis state before wiping innerHTML
  const chartEl = document.getElementById('chart-' + symbol);
  const analysisEl = document.getElementById('analysis-' + symbol);
  const chartVisible = chartEl && chartEl.style.display === 'block';
  const analysisVisible = analysisEl && analysisEl.style.display === 'block';
  const chartContent = chartEl ? chartEl.innerHTML : '';
  const analysisContent = analysisEl ? analysisEl.innerHTML : '';
  const chartData = chartVisible ? _stockKlineCache[symbol] : null;
  const analysisReport = analysisVisible ? _stockAnalysisCache[symbol] : null;

  card.innerHTML = '<div class="stock-loading">加载行情中...</div>';
  try {
    const resp = await fetch(`/api/stock/${symbol}/quote`);
    const data = await resp.json();
    if (!data.ok || !data.data) {
      card.innerHTML = `<div class="stock-result-header">
        <span class="stock-result-symbol">${symbol}</span>
        <span class="stock-result-name">${name}</span>
      </div><div class="stock-error">加载失败: ${data.error || '网络错误'}</div>`;
      return;
    }
    const d = data.data;
    const changeClass = d.change_pct > 0 ? 'positive' : d.change_pct < 0 ? 'negative' : 'neutral';
    const changeSign = d.change_pct > 0 ? '+' : '';
    // Cache for chat context
    _cardCache.stocks[symbol] = {
      name,
      close: d.price,
      change: d.change,
      change_pct: d.change_pct,
      open: d.open,
      high: d.high,
      low: d.low,
      volume: d.volume,
    };

    card.innerHTML = `<div class="stock-result-header">
      <span class="stock-result-symbol">${symbol}</span>
      <span class="stock-result-name">${name}</span>
    </div>
    <div class="stock-result-price">${fmt(d.price)}</div>
    <div class="stock-result-change ${changeClass}">${changeSign}${d.change.toFixed(2)} (${changeSign}${d.change_pct.toFixed(2)}%)</div>
    <div class="stock-result-meta">
      <span>开盘 ${fmt(d.open)}</span>
      <span>最高 ${fmt(d.high)}</span>
      <span>最低 ${fmt(d.low)}</span>
      <span>成交量 ${fmt(d.volume)}</span>
    </div>
    <div class="stock-result-actions">
      <button class="stock-analyze-btn" data-action="analyze" data-symbol="${symbol}" data-name="${name}">分析</button>
      <button class="stock-chart-btn" data-action="chart" data-symbol="${symbol}" data-name="${name}">K线</button>
    </div>
    <div id="chart-${symbol}" class="stock-chart-container" style="display:none"></div>
    <div id="analysis-${symbol}" class="stock-analysis-card" style="display:none"></div>`;

    // Clear card onclick so button clicks don't bubble to it
    card.onclick = null;

    // Bind button clicks directly (don't rely on document delegation + stopPropagation
    // since DOM0 onclick fires before addEventListener handlers)
    card.querySelector('.stock-analyze-btn').onclick = (e) => {
      e.stopPropagation();
      handleAnalyzeAction(symbol, name, card.querySelector('.stock-analyze-btn'));
    };
    card.querySelector('.stock-chart-btn').onclick = (e) => {
      e.stopPropagation();
      handleChartAction(symbol, name, card.querySelector('.stock-chart-btn'));
    };

    // Restore chart/analysis state after innerHTML rebuild
    const newChartEl = document.getElementById('chart-' + symbol);
    const newAnalysisEl = document.getElementById('analysis-' + symbol);

    if (chartVisible && chartData) {
      newChartEl.style.display = 'block';
      renderStockChart(newChartEl, symbol, name, chartData);
    } else if (chartVisible && chartContent) {
      newChartEl.style.display = 'block';
      newChartEl.innerHTML = chartContent;
    }

    if (analysisVisible && analysisReport) {
      newAnalysisEl.style.display = 'block';
      newAnalysisEl.innerHTML = `<h3>${symbol} 分析报告</h3><div class="stock-analysis-content">${typeof marked !== 'undefined' ? marked.parse(analysisReport) : escapeHtml(analysisReport)}</div>`;
    } else if (analysisVisible && analysisContent) {
      newAnalysisEl.style.display = 'block';
      newAnalysisEl.innerHTML = analysisContent;
    }
  } catch (e) {
    card.innerHTML = `<div class="stock-error">请求失败: ${e.message}</div>`;
  }
}

async function loadStockAnalysis(symbol, name, btn) {
  const container = document.getElementById('analysis-' + symbol);
  if (container.style.display === 'block') {
    container.style.display = 'none';
    return;
  }
  btn.textContent = '分析中...';
  btn.disabled = true;
  container.style.display = 'block';
    container.innerHTML = '<h3>' + name + ' 分析报告</h3><div class="stock-analysis-content"><p class="hint">分析任务排队中...</p></div>';
  try {
    await runAnalysisJob(
      `/api/analysis-jobs/stock/${symbol}`,
      (message, data) => {
        const jobId = data && data.job ? data.job.id : null;
        renderAnalysisStatus(container, '<h3>' + name + ' 分析报告</h3>', message, jobId);
       },
       (report, result, job) => {
         btn.textContent = '分析';
        _stockAnalysisCache[symbol] = report;
      }
    );
  } catch (e) {
    container.innerHTML = `<h3>分析报告（${symbol}）</h3><div class="stock-error">请求失败: ${e.message}</div>`;
    container.style.display = 'block';
  } finally {
    btn.textContent = '分析';
    btn.disabled = false;
  }
}

function escapeHtml(text) {
  return text.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}

function renderMarkdown(text) {
  return typeof marked !== 'undefined' ? marked.parse(text) : escapeHtml(text);
}

function keepStreamingOutputInView(container) {
  requestAnimationFrame(() => {
    const innerScroller = container.querySelector('.stock-analysis-content');
    if (innerScroller) {
      innerScroller.scrollTop = innerScroller.scrollHeight;
    }

    const rect = container.getBoundingClientRect();
    const viewportHeight = window.innerHeight || document.documentElement.clientHeight;
    if (rect.bottom > viewportHeight || rect.top < 0) {
      window.scrollBy({ top: rect.bottom - viewportHeight + 24, behavior: 'auto' });
    }
  });
}

function renderStreamingHtml(container, html) {
  container.innerHTML = html;
  keepStreamingOutputInView(container);
}

// K-line chart
async function toggleStockChart(symbol, name, btn) {
  const container = document.getElementById('chart-' + symbol);
  if (container.style.display === 'block') {
    container.style.display = 'none';
    return;
  }
  container.style.display = 'block';
  container.innerHTML = '<div class="stock-chart-loading">加载K线数据中...</div>';

  try {
    const resp = await fetch(`/api/stock/${symbol}/kline?days=60`);
    const data = await resp.json();
    if (!data.ok || !data.data || data.data.length === 0) {
      container.innerHTML = '<div class="stock-error">K线数据加载失败</div>';
      return;
    }
    renderStockChart(container, symbol, name, data.data);
    // Cache raw kline data for chat context
    _stockKlineCache[symbol] = data.data;
  } catch (e) {
    container.innerHTML = `<div class="stock-error">请求失败: ${e.message}</div>`;
  }
}

function renderStockChart(container, symbol, name, klineData) {
  // Abort if container is no longer in the DOM
  if (!container || !container.parentNode) return;

  // Tear down any existing resizeObserver to avoid leaks
  if (_chartResizeObserver && container.parentNode) {
    try { _chartResizeObserver.unobserve(container); } catch (_) {}
    _chartResizeObserver = null;
  }

  const ohlc = klineData.map(d => [d.open, d.close, d.low, d.high]);

  // Determine color per candle: compare close vs PREVIOUS close (not open)
  const isUp = klineData.map((d, i) =>
    i === 0 ? d.close >= d.open : d.close >= klineData[i - 1].close
  );

  // MA calculation — fill early periods with first valid MA so line is visible
  function ma(period) {
    const result = [];
    for (let i = 0; i < ohlc.length; i++) {
      if (i < period - 1) {
        result.push(null); // placeholder — will fill below
      } else {
        let sum = 0;
        for (let j = 0; j < period; j++) {
          sum += ohlc[i - j][1]; // close price
        }
        result.push(parseFloat((sum / period).toFixed(2)));
      }
    }
    // Backfill nulls with first valid value so the line renders from the left edge
    if (result.every(v => v === null)) return result;
    const first = result.find(v => v !== null);
    return result.map(v => v === null ? first : v);
  }

  const ma5 = ma(5);
  const ma20 = ma(20);
  const ma60 = ma(60);

  // Support/Resistance: use recent 20-day high/low as approximate levels
  const recentOhlc = ohlc.slice(-20);
  const recentHighs = recentOhlc.map(d => d[1]);
  const recentLows = recentOhlc.map(d => d[2]);
  const resistance = Math.max(...recentHighs);
  const support = Math.min(...recentLows);

  // Fibonacci retracement from recent low to recent high
  const fibLow = support;
  const fibHigh = resistance;
  const fibRange = fibHigh - fibLow;
  const fibLevels = [
    { level: 0.382, label: '38.2%', value: fibLow + fibRange * 0.382 },
    { level: 0.5, label: '50%', value: fibLow + fibRange * 0.5 },
    { level: 0.618, label: '61.8%', value: fibLow + fibRange * 0.618 },
  ];

  // Dispose any existing ECharts instance on this container first
  try {
    const existingInstance = echarts.getInstanceByDom(container);
    if (existingInstance) {
      existingInstance.dispose();
    }
    container.innerHTML = '';
  } catch (e) {
    // If getInstanceByDom throws (e.g. container is detached), force clear
    try { container.innerHTML = ''; } catch (_) {}
  }

  const chart = echarts.init(container, null, { renderer: 'canvas', useDirtyRect: true });
  const option = {
    backgroundColor: 'transparent',
    animation: true,
    title: {
      text: `${name} K线`,
      subtext: '',
      textStyle: { color: '#38bdf8', fontSize: 14, fontWeight: '600' },
      subtextStyle: { color: '#64748b', fontSize: 11 },
      left: 'center',
    },
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'cross' },
      backgroundColor: '#1e293b',
      borderColor: '#334155',
      textStyle: { color: '#e2e8f0', fontSize: 12 },
      formatter: function(params) {
        const candlestick = params.find(p => p.seriesType === 'candlestick');
        if (!candlestick) return '';
        // Use klineData directly instead of candlestick.data
        // to avoid ECharts internal data transformation issues
        const raw = klineData[candlestick.dataIndex];
        if (!raw) return '';
        return `<strong>${raw.date}</strong><br/>
          开: ${fmt(raw.open)}<br/>
          高: ${fmt(raw.high)}<br/>
          低: ${fmt(raw.low)}<br/>
          收: ${fmt(raw.close)}`;
      },
    },
    grid: [
      {
        left: '10%', right: '8%', top: '18%', height: '50%', bottom: '15%',
        containLabel: true,
      },
      { left: '10%', right: '8%', top: '73%', height: '14%' },
    ],
    legend: {
      data: [
        { name: 'MA5', itemStyle: { color: '#f59e0b' }, textStyle: { color: '#f59e0b', fontSize: 10 } },
        { name: 'MA20', itemStyle: { color: '#a78bfa' }, textStyle: { color: '#a78bfa', fontSize: 10 } },
        { name: 'MA60', itemStyle: { color: '#38bdf8' }, textStyle: { color: '#38bdf8', fontSize: 10 } },
      ],
      orient: 'horizontal',
      bottom: 4,
      left: 'center',
      itemGap: 12,
      selected: {
        'MA5': true, 'MA20': true, 'MA60': true,
      },
    },
    xAxis: [
      {
        type: 'category', data: klineData.map(d => d.date),
        gridIndex: 0, axisLine: { lineStyle: { color: '#334155' } },
        axisLabel: { color: '#64748b', fontSize: 10 },
        axisTick: { show: false },
        splitLine: { show: false },
      },
      {
        type: 'category', data: klineData.map(d => d.date),
        gridIndex: 1, axisLine: { lineStyle: { color: '#334155' } },
        axisLabel: { show: false }, axisTick: { show: false }, splitLine: { show: false },
      },
    ],
    yAxis: [
      {
        scale: true, gridIndex: 0,
        axisLine: { lineStyle: { color: '#334155' } },
        axisLabel: { color: '#64748b', fontSize: 10 },
        splitLine: { lineStyle: { color: '#1e293b', type: 'dashed' } },
      },
      {
        scale: true, gridIndex: 1,
        axisLine: { show: false }, axisTick: { show: false },
        axisLabel: { show: false }, splitLine: { show: false },
      },
    ],
    dataZoom: [
      { type: 'inside', xAxisIndex: [0, 1], start: 60, end: 100 },
      { type: 'slider', xAxisIndex: [0, 1], start: 60, end: 100,
        bottom: 42, height: 22,
        borderColor: '#334155',
        backgroundColor: '#1e293b',
        fillerColor: 'rgba(56,189,248,0.08)',
        handleStyle: { color: '#38bdf8', borderColor: '#38bdf8' },
        textStyle: { color: '#64748b', fontSize: 10 },
        moveHandleStyle: { color: '#38bdf8' },
        emphasis: { handleStyle: { color: '#7dd3fc', borderColor: '#7dd3fc' } },
      },
    ],
    series: [
      {
        name: 'K线', type: 'candlestick',
        data: ohlc.map((d, i) => ({
          value: d,
          itemStyle: {
            color: isUp[i] ? '#ef4444' : '#22c55e',
            borderColor: isUp[i] ? '#ef4444' : '#22c55e',
          },
        })),
        xAxisIndex: 0, yAxisIndex: 0,
        markLine: {
          silent: true, symbol: ['none', 'none'],
          lineStyle: { color: '#64748b', type: 'dashed', width: 1, opacity: 0.5 },
          label: { show: true, position: 'insideEndTop', color: '#94a3b8', fontSize: 9 },
          data: [
            ...fibLevels.map(fib => ({ yAxis: fib.value, name: fib.label })),
            { yAxis: resistance, name: '阻力 ' + fmt(resistance), lineStyle: { color: '#ef4444', width: 1.5, opacity: 0.8 } },
            { yAxis: support, name: '支撑 ' + fmt(support), lineStyle: { color: '#22c55e', width: 1.5, opacity: 0.8 } },
          ],
        },
      },
      {
        name: 'MA5', type: 'line', data: ma5,
        smooth: false, symbol: 'none',
        lineStyle: { color: '#f59e0b', width: 1 },
        xAxisIndex: 0, yAxisIndex: 0,
      },
      {
        name: 'MA20', type: 'line', data: ma20,
        smooth: false, symbol: 'none',
        lineStyle: { color: '#a78bfa', width: 1 },
        xAxisIndex: 0, yAxisIndex: 0,
      },
      {
        name: 'MA60', type: 'line', data: ma60,
        smooth: false, symbol: 'none',
        lineStyle: { color: '#38bdf8', width: 1 },
        xAxisIndex: 0, yAxisIndex: 0,
      },
      // Volume bars
      {
        name: '成交量', type: 'bar',
        data: klineData.map((d, i) => ({
          value: d.volume,
          itemStyle: { color: isUp[i] ? 'rgba(239,68,68,0.5)' : 'rgba(34,197,94,0.5)' },
        })),
        xAxisIndex: 1, yAxisIndex: 1,
      },
    ],
  };

  chart.setOption(option);
  chart.resize();

  // Resize observer (module-level to allow cleanup on next render)
  _chartResizeObserver = new ResizeObserver(() => { chart.resize(); });
  _chartResizeObserver.observe(container);
}

// Map index prefix to yfinance-compatible symbols (NOT Sina symbols)
const INDEX_SYMBOLS = {
  ixic: '^IXIC',
  dji: '^DJI',
  spx: '^GSPC',
  gold: 'GC=F',
};

// Track which index chart is currently in overlay mode
let _activeIndexChart = null; // prefix string or null

// Module-level resize observer (cleanup on re-render)
let _chartResizeObserver = null;

async function toggleIndexChart(prefix, name) {
  // If same prefix is already open in overlay, close it
  if (_activeIndexChart === prefix) {
    closeIndexChartOverlay();
    return;
  }

  // Close any existing overlay first (if switching to a different index)
  if (_activeIndexChart !== null) {
    closeIndexChartOverlay();
  }

  // Show overlay below cards
  const overlay = document.getElementById('index-chart-overlay');
  const overlayTitle = document.getElementById('index-chart-overlay-title');
  const overlayContent = document.getElementById('index-chart-overlay-content');

  overlayTitle.textContent = name + ' K线';
  overlayContent.innerHTML = '<div class="stock-chart-loading">加载K线数据中...</div>';
  overlay.style.display = 'block';
  _activeIndexChart = prefix;

  try {
    const resp = await fetch('/api/stock/' + INDEX_SYMBOLS[prefix] + '/kline?days=60');
    const data = await resp.json();
    if (!data.ok || !data.data || data.data.length === 0) {
      overlayContent.innerHTML = '<div class="stock-error">K线数据加载失败</div>';
      return;
    }
    renderStockChart(overlayContent, INDEX_SYMBOLS[prefix], name, data.data);
    // Cache raw kline data for chat context
    _indexKlineCache[prefix] = data.data;
  } catch (e) {
    overlayContent.innerHTML = '<div class="stock-error">请求失败: ' + e.message + '</div>';
  }
}

function closeIndexChartOverlay() {
  const overlay = document.getElementById('index-chart-overlay');
  const overlayContent = document.getElementById('index-chart-overlay-content');
  overlay.style.display = 'none';
  overlayContent.innerHTML = '';
  _activeIndexChart = null;
}

document.addEventListener('DOMContentLoaded', initChat);
