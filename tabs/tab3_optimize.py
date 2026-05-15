"""Tab 3: 参数优化 — Optuna 网格搜索，支持全部8个策略"""
import streamlit as st
import pandas as pd
from backtest_utils import load_data, optuna_objective
from visualization.plotly_charts import plot_optimization_history


# 每个策略的可优化参数定义
# 每项: {"name": 参数名, "label": 显示名, "type": int/float, "min": 最小值, "max": 最大值, "default": 默认, "step": 步长}
STRATEGY_OPT_PARAMS = {
    "双均线 (MA Cross)": [
        {"name": "fast_period", "label": "快线周期", "type": "int", "min": 2, "max": 30, "default": 5},
        {"name": "slow_period", "label": "慢线周期", "type": "int", "min": 10, "max": 60, "default": 20},
    ],
    "MACD": [
        {"name": "fast_period", "label": "快线", "type": "int", "min": 6, "max": 24, "default": 12},
        {"name": "slow_period", "label": "慢线", "type": "int", "min": 20, "max": 52, "default": 26},
        {"name": "signal_period", "label": "信号线", "type": "int", "min": 5, "max": 15, "default": 9},
    ],
    "RSI 超买超卖": [
        {"name": "rsi_period", "label": "RSI 周期", "type": "int", "min": 5, "max": 30, "default": 14},
        {"name": "oversold", "label": "超卖阈值", "type": "int", "min": 15, "max": 45, "default": 30},
        {"name": "overbought", "label": "超买阈值", "type": "int", "min": 60, "max": 90, "default": 70},
    ],
    "布林带 (Bollinger)": [
        {"name": "period", "label": "布林带周期", "type": "int", "min": 5, "max": 50, "default": 20},
        {"name": "devfactor", "label": "标准差倍数", "type": "float", "min": 1.0, "max": 4.0, "default": 2.0, "step": 0.5},
    ],
    "三均线 (Triple MA)": [
        {"name": "fast_period", "label": "快线周期", "type": "int", "min": 2, "max": 15, "default": 5},
        {"name": "mid_period", "label": "中线周期", "type": "int", "min": 10, "max": 30, "default": 20},
        {"name": "slow_period", "label": "慢线周期", "type": "int", "min": 30, "max": 90, "default": 60},
    ],
    "KDJ": [
        {"name": "period", "label": "KDJ 周期", "type": "int", "min": 5, "max": 20, "default": 9},
        {"name": "period_dfast", "label": "K值平滑", "type": "int", "min": 2, "max": 5, "default": 3},
        {"name": "upper", "label": "超买区", "type": "int", "min": 60, "max": 90, "default": 80},
        {"name": "lower", "label": "超卖区", "type": "int", "min": 10, "max": 40, "default": 20},
    ],
    "唐奇安通道 (Donchian)": [
        {"name": "period", "label": "通道周期", "type": "int", "min": 10, "max": 60, "default": 20},
    ],
    "ATR动态跟踪": [
        {"name": "fast_period", "label": "快线周期", "type": "int", "min": 5, "max": 20, "default": 10},
        {"name": "slow_period", "label": "慢线周期", "type": "int", "min": 20, "max": 60, "default": 30},
        {"name": "atr_period", "label": "ATR 周期", "type": "int", "min": 7, "max": 21, "default": 14},
        {"name": "atr_mult", "label": "ATR 倍数", "type": "float", "min": 1.0, "max": 6.0, "default": 3.0, "step": 0.5},
    ],
}


def render():
    if st.session_state.get("work_mode", "回测") != "回测":
        st.info("请先在侧边栏切换到「📊 回测工作台」模式")
        return

    symbol = st.session_state.get("symbol", "")
    strategy_name = st.session_state.get("strategy_name", "")
    strategy_cls = st.session_state.get("strategy_cls")
    start_date = st.session_state.get("start_date")
    end_date = st.session_state.get("end_date")

    st.title("参数优化")

    if not strategy_cls:
        st.info("请先在侧边栏选择策略")
        return

    st.subheader("优化设置")
    col1, col2, col3 = st.columns(3)
    with col1:
        opt_target = st.selectbox("优化目标", ["夏普比率", "年化收益", "最小回撤"])
        target_map = {"夏普比率": "sharpe", "年化收益": "return", "最小回撤": "drawdown"}
    with col2:
        n_trials = st.number_input("试验次数", min_value=10, max_value=500, value=50, step=10)
    with col3:
        st.write("")
        st.caption("次数越多越精确，但耗时更长")

    # ── 动态参数范围 UI ──
    param_defs = STRATEGY_OPT_PARAMS.get(strategy_name, [])
    if not param_defs:
        st.warning(f"策略 '{strategy_name}' 暂不支持参数优化")
        return

    st.subheader("优化参数范围")
    user_param_configs = []

    # 每行最多 4 个参数输入
    chunk_size = 4
    for i in range(0, len(param_defs), chunk_size):
        chunk = param_defs[i:i + chunk_size]
        cols = st.columns(len(chunk))
        for j, pd_def in enumerate(chunk):
            with cols[j]:
                st.caption(pd_def["label"])
                lo_key = f"opt_{pd_def['name']}_lo"
                hi_key = f"opt_{pd_def['name']}_hi"
                if pd_def["type"] == "float":
                    step = pd_def.get("step", 0.1)
                    lo_val = st.number_input("最小值", value=pd_def["min"], step=step, key=lo_key)
                    hi_val = st.number_input("最大值", value=pd_def["max"], step=step, key=hi_key)
                else:
                    lo_val = st.number_input("最小值", value=pd_def["min"], step=1, key=lo_key)
                    hi_val = st.number_input("最大值", value=pd_def["max"], step=1, key=hi_key)
                user_param_configs.append({
                    "name": pd_def["name"],
                    "type": pd_def["type"],
                    "min": lo_val,
                    "max": hi_val,
                    "step": pd_def.get("step"),
                })

    optimize_btn = st.button("⚡ 开始优化", type="primary", key="optimize_btn")

    if optimize_btn and symbol:
        start_s = start_date.strftime("%Y-%m-%d")
        end_s = end_date.strftime("%Y-%m-%d")

        import optuna

        df = load_data(symbol, start_s, end_s)
        if df.empty:
            st.error(f"未能获取 {symbol} 的行情数据")
            st.stop()

        progress_bar = st.progress(0)
        status_text = st.empty()

        class StreamlitCallback:
            def __init__(self, n):
                self.n = n
                self.pb = progress_bar
                self.st = status_text

            def __call__(self, study, trial):
                self.pb.progress(trial.number / self.n)
                if trial.value is not None:
                    self.st.text(f"第 {trial.number}/{self.n} 次试验 | 当前最优: {study.best_value:.4f}")

        with st.spinner(f"运行 optuna 优化... 共 {n_trials} 次试验"):
            optuna.logging.set_verbosity(optuna.logging.WARNING)
            study = optuna.create_study(direction="maximize")
            study.optimize(
                lambda trial: optuna_objective(
                    trial, strategy_cls, df, user_param_configs, target_map[opt_target]
                ),
                n_trials=n_trials,
                callbacks=[StreamlitCallback(n_trials)],
            )

        progress_bar.progress(1.0)
        status_text.text("优化完成!")
        st.success(f"最佳参数: {study.best_params} | 最佳值: {study.best_value:.4f}")

        trials_df = study.trials_dataframe()
        param_names = [p["name"] for p in param_defs]
        fig_opt = plot_optimization_history(trials_df, param_names)
        st.plotly_chart(fig_opt, use_container_width=True)

        st.subheader("最优参数组合")
        best_cols = st.columns(len(study.best_params))
        for i, (k, v) in enumerate(study.best_params.items()):
            with best_cols[i]:
                label = next((p["label"] for p in param_defs if p["name"] == k), k)
                display_val = f"{v:.2f}" if isinstance(v, float) else str(v)
                st.metric(label, display_val)

        st.dataframe(trials_df.head(10), use_container_width=True, hide_index=True)
