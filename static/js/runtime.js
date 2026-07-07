"use strict";

let runtimeStatsRange = '1d';

function initRuntimeTheme() {
  const themes = ['graphite', 'forest', 'copper'];
  const apply = (theme) => {
    const selected = themes.includes(theme) ? theme : 'graphite';
    document.documentElement.dataset.theme = selected;
    localStorage.setItem('ward_theme', selected);
    document.querySelectorAll('.theme-switcher button').forEach((button) => {
      button.classList.toggle('active', button.dataset.theme === selected);
    });
  };
  apply(localStorage.getItem('ward_theme') || 'graphite');
  document.querySelectorAll('.theme-switcher button').forEach((button) => {
    button.addEventListener('click', () => apply(button.dataset.theme));
  });
}

async function loadRuntimeStats(range = runtimeStatsRange, button = null) {
  runtimeStatsRange = range;
  document.querySelectorAll('.runtime-range-btn').forEach((element) => {
    element.classList.toggle('active', element.dataset.range === range);
  });
  if (button) button.classList.add('active');
  const container = document.getElementById('runtime-stats');
  container.innerHTML = '<div class="runtime-muted">加载运行统计中...</div>';
  try {
    const response = await fetch(`/api/runtime/stats?range=${encodeURIComponent(range)}`);
    const payload = await response.json();
    if (!response.ok || !payload.ok) throw new Error(payload.error || '统计加载失败');
    renderRuntimeStats(payload.stats);
  } catch (error) {
    container.innerHTML = `<div class="runtime-muted">统计加载失败：${escapeHtml(error.message)}</div>`;
  }
}

function renderRuntimeStats(stats) {
  const items = [
    ['任务数', stats.jobs_total],
    ['成功 / 失败', `${stats.jobs_succeeded} / ${stats.jobs_failed}`],
    ['缓存命中率', `${Math.round((stats.cache_hit_rate || 0) * 100)}%`],
    ['LLM 调用', stats.llm_calls],
    ['Tokens', formatNumber(stats.total_tokens)],
    ['平均耗时', formatDuration(stats.avg_duration_ms)],
  ];
  document.getElementById('runtime-stats').innerHTML = items.map(([label, value]) => `
    <div class="runtime-stat">
      <div class="runtime-stat-label">${escapeHtml(label)}</div>
      <div class="runtime-stat-value">${escapeHtml(value)}</div>
    </div>
  `).join('');
}

async function loadRuntimeTrace() {
  const input = document.getElementById('runtime-job-input');
  const container = document.getElementById('runtime-trace');
  const jobId = input.value.trim();
  if (!jobId) {
    container.innerHTML = '<div class="runtime-muted">请输入 job id。</div>';
    return;
  }
  container.innerHTML = '<div class="runtime-muted">加载 trace 中...</div>';
  try {
    const response = await fetch(`/api/analysis-jobs/${encodeURIComponent(jobId)}/trace`);
    const payload = await response.json();
    if (!response.ok || !payload.ok) throw new Error(payload.error || 'Trace 加载失败');
    renderRuntimeTrace(payload.job, payload.events || []);
  } catch (error) {
    container.innerHTML = `<div class="runtime-muted">Trace 加载失败：${escapeHtml(error.message)}</div>`;
  }
}

function renderRuntimeTrace(job, events) {
  const usage = job.usage || {};
  const summary = [
    ['状态', job.status],
    ['类型', job.type],
    ['耗时', formatDuration(job.duration_ms)],
    ['Tokens', formatNumber(usage.total_tokens || 0)],
  ].map(([label, value]) => `
    <div class="runtime-stat">
      <div class="runtime-stat-label">${escapeHtml(label)}</div>
      <div class="runtime-stat-value">${escapeHtml(value)}</div>
    </div>
  `).join('');
  const eventHtml = events.map((event) => `
    <div class="runtime-event">
      <div class="runtime-event-time">${escapeHtml(formatTime(event.created_at))}</div>
      <div class="runtime-event-stage">${escapeHtml(event.stage || event.event || '--')}</div>
      <div class="runtime-event-message">${escapeHtml(event.message || '')}</div>
      <div class="runtime-event-duration">${escapeHtml(formatDuration(event.duration_ms))}</div>
      ${renderEventData(event.data)}
    </div>
  `).join('');
  document.getElementById('runtime-trace').innerHTML = `
    <div class="runtime-trace-summary">${summary}</div>
    ${renderTeamOverview(job, events)}
    ${eventHtml || '<div class="runtime-muted">暂无事件。</div>'}
  `;
}

function renderEventData(value) {
  if (!value) return '';
  const text = JSON.stringify(value, null, 2);
  const lines = text.split('\n').length;
  if (text.length <= 1200 && lines <= 24) return `<pre class="runtime-event-data">${escapeHtml(text)}</pre>`;
  return `<details class="runtime-event-data runtime-event-data-collapsed">
    <summary>报文较长，点击展开 · ${lines} 行 · ${formatNumber(text.length)} 字符</summary>
    <pre>${escapeHtml(text)}</pre>
  </details>`;
}

function renderTeamOverview(job, events) {
  if (!job || job.type !== 'stock_comparison') return '';
  const plan = events.find((event) => event.event === 'leader_plan');
  const workers = events.filter((event) => event.event === 'worker_done');
  const verification = events.find((event) => ['verification_passed', 'verification_failed'].includes(event.event));
  const symbols = plan?.data?.symbols || job.payload?.symbols || [];
  const workerHtml = workers.length ? workers.map((event) => {
    const data = event.data || {};
    const ok = data.ok !== false;
    return `<div class="runtime-team-worker ${ok ? 'ok' : 'error'}">
      <div class="runtime-team-worker-symbol">${escapeHtml(data.symbol || '--')}</div>
      <div class="runtime-team-worker-meta">${ok ? '完成' : '失败'} · 趋势 ${escapeHtml(data.trend?.status || '--')} · K线 ${escapeHtml(data.data_quality?.kline_count ?? '--')}</div>
    </div>`;
  }).join('') : '<div class="runtime-muted">Worker 尚未完成。</div>';
  const verifier = verification?.data;
  return `<div class="runtime-team">
    <div class="runtime-team-title">Team Overview${symbols.length ? ` · ${escapeHtml(symbols.join(' / '))}` : ''}</div>
    <div class="runtime-team-grid">
      <div class="runtime-team-card"><div class="runtime-team-card-label">Leader</div><div class="runtime-team-card-value">${plan ? '计划已生成' : '等待计划'}</div></div>
      <div class="runtime-team-card runtime-team-workers-card"><div class="runtime-team-card-label">Workers</div><div class="runtime-team-workers">${workerHtml}</div></div>
      <div class="runtime-team-card ${verifier?.passed === false ? 'error' : verifier?.passed === true ? 'ok' : ''}"><div class="runtime-team-card-label">Verifier</div><div class="runtime-team-card-value">${verifier?.passed === true ? '验证通过' : verifier?.passed === false ? '验证失败' : '等待验证'}</div></div>
    </div>
  </div>`;
}

function refreshRuntimePanel() {
  loadRuntimeStats(runtimeStatsRange);
}

function formatDuration(milliseconds) {
  if (milliseconds === null || milliseconds === undefined) return '--';
  return milliseconds < 1000 ? `${milliseconds}ms` : `${(milliseconds / 1000).toFixed(1)}s`;
}

function formatNumber(value) {
  if (value === null || value === undefined) return '--';
  return Number(value).toLocaleString('en-US');
}

function formatTime(value) {
  if (!value) return '--';
  const date = new Date(value + (value.endsWith('Z') ? '' : 'Z'));
  return Number.isNaN(date.getTime()) ? value.slice(11, 19) : date.toLocaleTimeString('zh-CN', { hour12: false });
}

document.addEventListener('DOMContentLoaded', () => {
  initRuntimeTheme();
  loadRuntimeStats('1d');
  const jobId = new URLSearchParams(window.location.search).get('job_id');
  if (jobId) {
    document.getElementById('runtime-job-input').value = jobId;
    loadRuntimeTrace();
  }
});
