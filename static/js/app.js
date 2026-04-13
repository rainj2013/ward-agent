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
let _marketReportCache = null;  // string (market AI report)
let _indexAnalysisCache = {};   // prefix -> string (index AI analysis text)

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
  const indexNames = { ixic: 'Nasdaq 综合', dji: '道琼斯', spx: '标普500' };
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

// Check if US market is open (UTC time)
// US market hours: 14:30 - 21:00 UTC (Mon-Fri)
function isMarketOpen() {
  const now = new Date();
  const utcHour = now.getUTCHours();
  const utcMin = now.getUTCMinutes();
  const utcTime = utcHour * 60 + utcMin;
  const day = now.getUTCDay(); // 0=Sun, 6=Sat

  if (day === 0 || day === 6) return false;
  return utcTime >= 14 * 60 + 30 && utcTime < 21 * 60;
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

async function generateReport() {
  const btn = document.getElementById('generate-btn');
  const content = document.getElementById('report-content');
  btn.disabled = true;
  btn.textContent = '生成中...';
  content.innerHTML = '<p class="hint">正在调用 AI 分析，请稍候...</p>';

  let timeoutId;
  const timeoutPromise = new Promise((_, reject) => {
    timeoutId = setTimeout(() => reject(new Error('请求超时（90秒）')), 90000);
  });

  try {
    const resp = await Promise.race([
      fetch('/api/report'),
      timeoutPromise
    ]);
    clearTimeout(timeoutId);
    const data = await resp.json();
    if (data.ok) {
      let html = marked.parse(data.report);
      // 附加情绪评分卡片
      if (data.data && data.data.sentiment) {
        const s = data.data.sentiment;
        if (s.score !== null) {
          const scoreColor = s.score >= 6 ? '#22c55e' : s.score >= 4 ? '#f59e0b' : '#ef4444';
          const scoreLabel = s.score >= 6 ? '偏多' : s.score >= 4 ? '中性' : '偏空';
          html += `<div class="sentiment-card">
            <div class="sentiment-title">😈 市场情绪评分</div>
            <div class="sentiment-score-row">
              <span class="sentiment-score" style="color:${scoreColor}">${s.score.toFixed(1)}/9</span>
              <span class="sentiment-label" style="color:${scoreColor}">${scoreLabel}</span>
            </div>
            <div class="sentiment-interpretation">${escapeHtml(s.interpretation || '')}</div>
          </div>`;
        }
      }
      content.innerHTML = html;
      _marketReportCache = data.report;
    } else {
      content.innerHTML = `<p class="hint" style="color:#ef4444">生成失败: ${data.error}</p>`;
    }
  } catch (e) {
    content.innerHTML = `<p class="hint" style="color:#ef4444">请求失败: ${e.message}</p>`;
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

async function initChat() {
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
    div.innerHTML = typeof marked !== 'undefined' ? marked.parse(msg.content) : escapeHtml(msg.content);
  }
  return div;
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
  btn.disabled = true;
  btn.textContent = '思考中...';

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

    const payload = { conversation_id: conversationId, message };
    if (ctx.indices.length || ctx.stocks.length || Object.keys(ctx.index_klines).length || Object.keys(ctx.stock_klines).length || Object.keys(ctx.stock_analyses).length || Object.keys(ctx.index_analyses).length) {
      payload.context = ctx;
    }

    // Use SSE streaming endpoint
    const resp = await fetch('/api/chat/stream', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    const reader = resp.body.getReader();
    const decoder = new TextDecoder();
    let done = false;
    let fullReply = '';
    let convId = conversationId;
    const reqStart = Date.now();

    const assistantDiv = document.createElement('div');
    assistantDiv.className = 'chat-msg assistant';
    container.appendChild(assistantDiv);

    while (!done) {
      const { value, done: readerDone } = await reader.read();
      done = readerDone;
      if (!value) continue;
      console.log(`[stream] recv ${value.byteLength}B at +${Date.now()-reqStart}ms, done=${done}`);

      const text = decoder.decode(value, { stream: !done });
      const lines = text.split('\n');
      for (const line of lines) {
        if (!line.startsWith('data: ')) continue;
        try {
          const data = JSON.parse(line.slice(6));
          if (!data.ok) {
            assistantDiv.textContent = `出错: ${data.error}`;
            done = true;
            break;
          }
          convId = data.conversation_id;
          if (data.chunk) {
            fullReply += data.chunk;
            assistantDiv.innerHTML = typeof marked !== 'undefined' ? marked.parse(fullReply) : escapeHtml(fullReply);
            container.scrollTop = container.scrollHeight;
          }
          if (data.done) {
            assistantDiv.innerHTML = typeof marked !== 'undefined' ? marked.parse(fullReply) : escapeHtml(fullReply);
            conversationId = convId;
            localStorage.setItem('ward_conversation_id', convId);
            // Streaming already put user + assistant messages into the DOM.
            // done: only sync pagination state — never re-render.
            if (data.has_more !== undefined) _hasMoreMessages = data.has_more;
            if (data.next_before_id !== undefined) _nextBeforeId = data.next_before_id;
            const loadMoreBtn = document.getElementById('chat-load-more-btn');
            if (loadMoreBtn) loadMoreBtn.style.display = _hasMoreMessages ? 'block' : 'none';
            done = true;
          } else {
            // Chunk received: scroll to keep newest message visible
            container.scrollTop = container.scrollHeight;
          }
        } catch (e) {}
      }
    }
  } catch (e) {
    const errDiv = document.createElement('div');
    errDiv.className = 'chat-msg assistant';
    errDiv.textContent = `请求失败: ${e.message}`;
    container.appendChild(errDiv);
    container.scrollTop = container.scrollHeight;
  } finally {
    btn.disabled = false;
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
    fetch('/api/index/' + prefix + '/analyze')
      .then(r => r.json())
      .then(data => {
        btn.textContent = '🧠 AI分析';
        btn.disabled = false;
        if (!data.ok || !data.report) {
          container.innerHTML = '<h3>📊 ' + name + ' AI 分析报告</h3><div class="stock-error">分析失败: ' + (data.error || '未知错误') + '</div>';
        } else {
          container.innerHTML = '<h3>📊 ' + name + ' AI 分析报告</h3><div class="stock-analysis-content">' + (typeof marked !== 'undefined' ? marked.parse(data.report) : escapeHtml(data.report)) + '</div>';
          if (!_indexAnalysisCache) _indexAnalysisCache = {};
          _indexAnalysisCache[prefix] = data.report;
        }
        container.style.display = 'block';
      })
      .catch(err => {
        btn.textContent = '🧠 AI分析';
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
    fetch(`/api/stock/${symbol}/analyze`)
      .then(r => r.json())
      .then(data => {
        btn.textContent = '🧠 AI分析';
        btn.disabled = false;
        if (!data.ok || !data.report) {
          container.innerHTML = '<h3>📊 ' + symbol + ' 个股 AI 分析报告</h3><div class="stock-error">分析失败: ' + (data.error || '未知错误') + '</div>';
        } else {
          container.innerHTML = '<h3>📊 ' + symbol + ' 个股 AI 分析报告</h3><div class="stock-analysis-content">' + (typeof marked !== 'undefined' ? marked.parse(data.report) : escapeHtml(data.report)) + '</div>';
          _stockAnalysisCache[symbol] = data.report;
        }
        container.style.display = 'block';
      })
      .catch(err => {
        btn.textContent = '🧠 AI分析';
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
  loadMarketData();
  loadExtendedHours();

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
    const symbol = card.querySelector('.stock-result-symbol').textContent;
    const name = card.querySelector('.stock-result-name').textContent;
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
      <button class="stock-analyze-btn" data-action="analyze" data-symbol="${symbol}" data-name="${name}">🧠 AI分析</button>
      <button class="stock-chart-btn" data-action="chart" data-symbol="${symbol}" data-name="${name}">📊 K线图</button>
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
      newAnalysisEl.innerHTML = `<h3>📊 ${symbol} 个股 AI 分析报告</h3><div class="stock-analysis-content">${typeof marked !== 'undefined' ? marked.parse(analysisReport) : escapeHtml(analysisReport)}</div>`;
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
  try {
    const resp = await fetch(`/api/stock/${symbol}/analyze`);
    const data = await resp.json();
    btn.textContent = 'AI 分析';
    btn.disabled = false;
    if (!data.ok || !data.report) {
      container.innerHTML = `<h3>📊 ${symbol} 个股 AI 分析报告</h3><div class="stock-error">分析失败: ${data.error || '未知错误'}</div>`;
    } else {
      container.innerHTML = `<h3>📊 ${symbol} 个股 AI 分析报告</h3><div class="stock-analysis-content">${typeof marked !== 'undefined' ? marked.parse(data.report) : escapeHtml(data.report)}</div>`;
      _stockAnalysisCache[symbol] = data.report;
    }
    container.style.display = 'block';
  } catch (e) {
    btn.textContent = 'AI 分析';
    btn.disabled = false;
    container.innerHTML = `<h3>分析报告（${symbol}）</h3><div class="stock-error">请求失败: ${e.message}</div>`;
    container.style.display = 'block';
  }
}

function escapeHtml(text) {
  return text.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
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
      data: ['MA5', 'MA20', 'MA60'],
      orient: 'horizontal',
      bottom: 4,
      left: 'center',
      itemGap: 12,
      textStyle: { color: '#94a3b8', fontSize: 10 },
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
