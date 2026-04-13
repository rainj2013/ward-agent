# Ward — 美股市场数据分析

基于 AI 的美股市场数据分析工具，支持指数实时行情、盘前/盘中/盘后行情、个股查询、K 线技术图表、指数 AI 分析、个股 AI 分析报告、AI 智能问答。

> ⚠️ **投资风险提示**：本工具所有数据仅供参考，不构成任何投资建议。入市有风险，投资需谨慎。

![Python](https://img.shields.io/badge/Python-3.12+-blue.svg)
![License](https://img.shields.io/badge/license-MIT-green.svg)

---

## 功能特性

### 已实现

#### 📊 指数行情
- 默认展示 Nasdaq 综合、道琼斯、标普 500 三大指数
- 交易时段内每 30 秒自动刷新
- 收盘状态自动检测
- 点击展开详细行情（开盘价、最高、最低、成交量）

#### 🕐 盘前 / 盘中 / 盘后行情
- 展示三大指数盘前（Pre-Market）、盘中（Regular）、盘后（After-Hours）三个时段价格
- 数据来源：QQQ（纳指）、SPY（标普）、DIA（道指）ETF
- 跟随主行情刷新周期自动更新

#### 📈 K 线图与技术指标
- 支持指数和个股 K 线（历史数据）
- 均线叠加：MA5 / MA20 / MA60
- 支撑位 / 压力位自动标记
- 黄金分割线
- 全屏 overlay 展示

#### 🔍 个股查询
- 输入股票代码或名称搜索
- 实时行情：现价、涨跌幅、52 周高低、成交量、市值、PE
- 点击卡片刷新单票行情

#### 🤖 指数 AI 分析
- 每个指数卡片独立提供「🧠 AI 分析」按钮
- Nasdaq 综合、道琼斯、标普 500 均可单独分析
- 基于 60 日 K 线原始数据（OHLCV）进行 AI 技术分析
- 指数 AI 分析结果会带入智能问答上下文

#### 📝 个股 AI 分析报告
- 每个个股卡片提供「🧠 AI 分析」按钮
- 一键生成单票深度 AI 分析报告
- 包含技术面分析、支撑/压力位、市场情绪研判
- Markdown 格式渲染，表格、加粗、列表均可

#### 💬 智能问答
- 自然语言提问，AI 基于实时市场数据回答
- 对话历史本地 SQLite 持久化
- 支持加载更多历史消息（游标分页）
- 流式输出，实时显示 AI 回复
- 指数 AI 分析报告自动带入问答上下文

---

## 界面预览

```
┌─────────────────────────────────────────────────┐
│  📈 Ward                          [市场状态 ●]  │
│  美股市场数据分析                    刷新倒计时   │
├─────────────────────────────────────────────────┤
│  [Nasdaq 综合]    [道琼斯]    [标普 500]        │
│  点击展开详情 + AI分析 + K线图按钮              │
├─────────────────────────────────────────────────┤
│  🔍 个股查询                                     │
│  [输入股票代码或名称...              ] [搜索]   │
│  [AAPL  Apple Inc.     +2.3%    $182.5    ]     │
│  [NVDA  NVIDIA Corp   +4.1%    $875.2    ]     │
├─────────────────────────────────────────────────┤
│  🤖 AI 市场分析报告                              │
│  [生成报告]                                     │
│  今日市场整体呈上涨趋势，Nasdaq 领涨...          │
├─────────────────────────────────────────────────┤
│  💬 智能问答                                     │
│  [对话历史]                        [加载更多]  │
│  你: 道琼斯今天涨了多少？                        │
│  AI: 道琼斯指数上涨 0.82%，收盘价...            │
│  [输入问题...]                      [发送]     │
└─────────────────────────────────────────────────┘
```

---

## 快速开始

### 环境要求

- Python 3.12+
- [uv](https://github.com/astral-sh/uv)（推荐）或 pip

### 1. 克隆代码

```bash
git clone git@github.com:rainj2013/ward-agent.git
cd ward-agent
```

### 2. 配置 API 密钥

```bash
cp .env.example .env
```

编辑 `.env`，填入你的 MiniMax API Key：

```env
MINIMAX_API_KEY=***
```

> 支持的环境变量：
> - `MINIMAX_API_KEY` / `MINIMAX_PORTAL_API_KEY`（必填）
> - `LLM_MODEL`（可选，默认 `MiniMax-M2.7-highspeed`）
> - `ANTHROPIC_BASE_URL`（可选，默认 MiniMax 代理地址）

### 3. 安装依赖并运行

```bash
uv sync
uv run ward
```

或直接用 pip：

```bash
pip install -e .
ward
```

### 4. 访问

浏览器打开 http://localhost:8000

---

## 技术架构

```
ward-agent/
├── src/ward/
│   ├── api/routes.py          # FastAPI 路由
│   ├── core/
│   │   ├── config.py          # 配置管理（dotenv）
│   │   └── data_fetcher*.py   # 数据抓取（akshare）
│   ├── schemas/models.py      # Pydantic 模型
│   ├── services/
│   │   ├── chat_service.py    # AI 对话逻辑
│   │   ├── index_service.py   # 指数行情 + AI 分析
│   │   ├── stock_service.py   # 个股行情
│   │   ├── report_service.py  # AI 报告生成
│   │   └── db/
│   │       └── conversation_service.py  # SQLite 聊天历史
│   └── app.py                 # FastAPI 应用入口
└── static/
    ├── index.html              # 前端页面
    ├── css/style.css           # 样式
    └── js/app.js              # 前端逻辑
```

- **后端**：FastAPI + SQLite
- **前端**：原生 HTML/CSS/JS（无框架依赖）
- **数据源**：akshare（东方财富、新浪财经）
- **AI**：MiniMax API（Anthropic 兼容模式）

---

## 功能路线图

### Phase 1 — 基础展示层 ✅
- [x] 默认展示 Nasdaq + 道指 + 标普500 三个指数
- [x] 交易时间段内定时自动刷新（每 30 秒）
- [x] 指数卡片支持点击展开更多数据

### Phase 2 — 交互式问答 ✅
- [x] 聊天输入框（类似 ChatGPT 那种对话 UI）
- [x] AI 基于实时市场数据回答用户问题
- [x] 对话历史展示
- [x] 指数 AI 分析报告自动带入问答上下文

### Phase 3 — 个股深度分析 ✅
- [x] 输入股票代码/名称
- [x] 自动抓取：股价、PE、财务数据、近期新闻
- [x] AI 生成个股分析报告

### Phase 4 — 指数 AI 分析 ✅
- [x] 每个指数独立 AI 分析按钮（Nasdaq / 道琼斯 / 标普500）
- [x] 基于 60 日 K 线原始数据进行分析
- [x] 分析结果缓存，支持单独刷新

### Phase 5 — 技术分析图表 ✅
- [x] K 线图（支持历史数据）
- [x] 均线叠加（MA5/MA20/MA60）
- [x] 支撑位/压力位标记
- [x] 黄金分割线

---

## Roadmap

### Phase 6 — Worker / Reviewer 角色分离
- [ ] 指数和个股 AI 分析各自独立的 Worker Agent
- [ ] Reviewer Agent 对报告打分，不合格自动重写（最多 3 次）
- [ ] 明确的停止条件：格式正确 + 技术指标覆盖完整 + 无事实性错误

### Phase 7 — 外部 Tool Calling
- [ ] AkShare / yfinance 接口标准化
- [ ] 封装 LLM 可调用的工具：get_stock_quote、get_stock_news、get_market_sentiment、search_stock
- [ ] 智能问答支持主动获取页面之外的信息（新闻、财报日历等）

### Phase 8 — 外部测试验证
- [ ] 从 AI 分析报告中提取关键断言
- [ ] 用 K 线数据自动校验断言正确性
- [ ] 不一致时标记可疑并要求重写

### Phase 9 — 短反馈循环
- [ ] Worker 分段输出，段落级别 Reviewer 检查
- [ ] 发现问题立即中断，而不是等全文完成

### Phase 10 — 智能上下文管理
- [ ] 基于语义相似度的上下文压缩（embedding 向量检索）
- [ ] 分层记忆：短期（最近对话）+ 中期（市场摘要）+ 长期（用户偏好）
- [ ] 多 Agent 协作调度

---

## License

MIT License — 保留署名即可随意使用，包括商业用途。

---

## 免责声明

本工具仅供信息展示和辅助参考，所有市场数据均来源于第三方公开接口，**不构成任何投资建议**。投资有风险，入市需谨慎。本工具的开发者不对任何因使用本工具而产生的投资损失承担责任。

---

## 致谢

本项目使用以下开源数据源：

- [akshare](https://github.com/akfamily/akshare) — 东方财富、新浪财经等数据
- [yfinance](https://github.com/ranaroussi/yfinance) — Yahoo Finance 美股数据
- [ECharts](https://echarts.apache.org/) — K 线图可视化
- [Marked](https://marked.js.org/) — Markdown 渲染
