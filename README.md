# 📈 WinnerK 股票量化系统

基于 Streamlit 的 A 股量化分析与选股平台，集回测、选股、监控、分析于一体。

## ✨ 核心功能

### 📊 策略回测（3 个子模块）

| 功能 | 说明 |
|------|------|
| **单策略回测** | 8 大经典策略 × 任意 A 股，输出权益曲线、回撤、买卖点、绩效指标 |
| **策略对比** | 同一股票同时跑 8 个策略，横向对比收益率、夏普比、最大回撤 |
| **参数优化** | 基于 Optuna 的超参数搜索，自动找到每只股票的最优策略参数 |

**内置策略：** 双均线 · MACD · RSI超买超卖 · 布林带 · 三均线 · KDJ · 唐奇安通道 · ATR动态跟踪

---

### 🔍 智能选股（7 个子模块）

| 功能 | 说明 |
|------|------|
| **资金排名** | 全市场 TOP50 机构净流入 / 净流出 / 换手率排行，5 分钟缓存刷新 |
| **智能筛选** | 多维度筛选：价格、涨跌幅、成交量、换手率、市值、PE、PB、资金流向 |
| **强势股** | 龙虎榜每日席位明细（机构/游资动向）+ 涨停板池（封单、封板时间）+ 炸板监控 |
| **值博率** | 综合资金流、涨跌、换手、估值 4 维度打分的全 A 股排名 |
| **北向资金** | 沪深港通每日成交额、持仓 TOP10、外资流向趋势 |
| **财务分析** | ROE/ROA/毛利率/净利率/营收增速/利润增速 雷达图 + 业绩预告 |
| **市场全景** | 行业板块热力图、行业成分股浏览、市场宽度指标（涨跌比、均线多头占比） |

---

### 🧪 高级分析（8 个子模块）

| 功能 | 说明 |
|------|------|
| **多因子排名** | 5 因子打分（动量、波动率、成交量、趋势、回撤），自定义权重，综合排名 |
| **技术形态扫描** | 金叉/死叉、均线粘合、放量突破、N日新高/新低 全市场扫描 |
| **异常检测** | 缺口高开低开、成交量异动（vs 20日均量）、逼近涨跌停、连阳连阴 |
| **行业轮动** | 行业1周/1月/3月动量排名 × 多周期轮动热力图 |
| **K线形态识别** | 8 种经典形态：看涨/看跌吞没、锤子线、倒锤子、启明星、黄昏星、三白兵、三乌鸦 |
| **相关性分析** | 全市场 Spearman 相关矩阵、低相关配对、对冲配对（负相关）、聚类 |
| **批量回测** | 单策略 × 全行业成分股，一键跑出行业平均收益 |
| **量化信号** | 市场宽度历史（MA60多头占比、涨跌比、ADL、NH/NL）、极端区间检测、因子收益回测 |

---

### 🗄️ 数据中心

| 功能 | 说明 |
|------|------|
| **数据库管理** | DuckDB 本地存储，支持 AKShare 在线下载、CSV 导入、通达信(TDX)日线文件导入 |
| **一键同步** | 点击同步全市场数据，增量导入（秒级完成） |
| **定时任务** | 附赠 `sync_daily.bat` + Windows 计划任务脚本，收盘后自动更新数据 |

---

## 🚀 快速开始

### 环境要求

- Python ≥ 3.10
- Windows / macOS / Linux

### 安装

```bash
# 1. 克隆仓库
git clone git@github.com:gzkennykan/stock-check.git
cd stock-check

# 2. 安装依赖
pip install -r requirements.txt
```

### 启动

```bash
streamlit run app.py
```

浏览器访问 `http://localhost:8501` 即可使用。

### 首次使用

1. 进入 **🗄️ 数据中心** → 选择「在线下载」或「从券商客户端导入」
2. 如果你安装了通达信（TDX）等券商客户端，系统会在启动时**自动检测并增量同步**本地数据
3. 回测功能需要先在数据中心下载对应股票的日线数据

---

## 📁 项目结构

```
stock-check/
├── app.py                   # Streamlit 主入口
├── config.py                # 全局配置（数据库路径、TDX路径等）
├── strategies/              # 8 个交易策略实现
│   ├── ma_cross.py          #   双均线
│   ├── macd_strategy.py     #   MACD
│   ├── rsi_strategy.py      #   RSI 超买超卖
│   ├── bollinger.py         #   布林带
│   ├── triple_ma.py         #   三均线
│   ├── kdj.py               #   KDJ
│   ├── donchian.py          #   唐奇安通道
│   └── atr_strategy.py      #   ATR 动态跟踪
├── backtest/                # 回测引擎（基于 backtrader）
├── optimizer/               # 超参数优化（基于 Optuna）
├── tabs/                    # 13 个功能标签页
│   ├── tab1_backtest.py     #   单策略回测
│   ├── tab2_compare.py      #   策略对比
│   ├── tab3_optimize.py     #   参数优化
│   ├── tab5_market_rank.py  #   资金排名 TOP50
│   ├── tab8_smart.py        #   智能多维度选股
│   ├── tab9_lhb.py          #   龙虎榜 + 涨停板
│   ├── tab10_upside.py      #   值博率评分
│   ├── tab11_portfolio.py   #   组合回测
│   ├── tab12_northbound.py  #   北向资金分析
│   ├── tab13_fundamental.py #   财务分析
│   ├── tab14_industry.py    #   行业热力图 & 市场宽度
│   ├── tab15_database.py    #   数据中心（导入/导出/同步）
│   └── tab16_advanced.py    #   高级分析（8合1）
├── data/                    # 数据层
│   ├── database.py          #   DuckDB 数据库核心
│   ├── fetcher.py           #   多源数据获取（AKShare/yfinance）
│   ├── tdx_reader.py        #   通达信 .day 二进制解析器
│   ├── sync.py              #   每日增量同步
│   ├── factors.py           #   多因子打分引擎
│   ├── patterns.py          #   技术形态扫描
│   ├── signals.py           #   量化信号 & 市场宽度
│   ├── candlestick.py       #   K线形态识别
│   ├── anomaly.py           #   异常检测
│   ├── correlation.py       #   相关性分析
│   ├── batch_backtest.py    #   批量回测
│   ├── industry_db.py       #   行业轮动分析
│   ├── zt_pool.py           #   涨停板池数据
│   ├── screener.py          #   A股实时行情 & 筛选
│   └── ...                  #   更多数据模块
└── visualization/           # 可视化组件（Plotly 图表）
```

---

## 🔧 快捷脚本

| 脚本 | 用途 |
|------|------|
| `start.bat` / `launch.bat` | Windows 一键启动 |
| `sync_daily.bat` | 收盘后增量同步数据（TDX优先 → AKShare备选） |
| `install_scheduled_task.bat` | 安装 Windows 定时任务（自动每日同步） |

---

## 📡 数据源

| 数据 | 来源 |
|------|------|
| A 股日线 | 通达信(TDX)本地 .day 文件 / AKShare 在线 |
| 实时行情 | 新浪财经 API |
| 龙虎榜 | AKShare / 东方财富 |
| 资金流向 | 新浪财经 / 东方财富 |
| 北向资金 | 东方财富数据中心 |
| 财务数据 | 新浪财经摘要 |
| 行业分类 | 申万行业 (THS/AKShare) |

---

## 🛠 技术栈

- **界面框架**: Streamlit
- **回测引擎**: Backtrader
- **超参优化**: Optuna
- **本地数据库**: DuckDB（列式存储，秒级查询数千只股票）
- **可视化**: Plotly
- **数据获取**: AKShare · yfinance · 通达信二进制解析
- **数值计算**: Pandas · NumPy

---

## 📝 免责声明

本软件仅供学习研究使用，不构成任何投资建议。股市有风险，投资需谨慎。

---

**Author:** [gzkennykan](https://github.com/gzkennykan)  
**License:** MIT
