"""
可视化图表：资金曲线、回撤曲线、日收益分布、K线图+买卖点
"""
import matplotlib
matplotlib.use("Agg")  # 非交互后端，避免 GUI 问题
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

# 中文字体设置
plt.rcParams["font.sans-serif"] = ["SimHei", "Microsoft YaHei", "DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False


def plot_backtest(results: dict, save_path: str | None = "backtest_result.png") -> None:
    """
    绘制综合回测结果图：资金曲线 + 回撤曲线 + 日收益分布
    """
    fig, axes = plt.subplots(3, 1, figsize=(14, 12))
    fig.suptitle("回测结果", fontsize=16, fontweight="bold")

    # 1. 资金曲线
    ax1 = axes[0]
    equity = results.get("equity_curve")
    if equity is not None and len(equity) > 0:
        ax1.plot(equity.index, equity.values, color="#1f77b4", linewidth=1.5)
        ax1.fill_between(equity.index, equity.values, equity.values[0],
                          alpha=0.1, color="#1f77b4")
        ax1.axhline(y=equity.values[0], color="gray", linestyle="--", linewidth=0.8, label="初始资金")
        ax1.set_ylabel("资金 (¥)")
        ax1.legend(loc="upper left")
    ax1.set_title("资金曲线")
    ax1.grid(True, alpha=0.3)

    # 2. 回撤曲线
    ax2 = axes[1]
    if equity is not None and len(equity) > 0:
        rolling_max = equity.cummax()
        drawdown = (equity - rolling_max) / rolling_max * 100
        ax2.fill_between(drawdown.index, drawdown.values, 0, alpha=0.6, color="#d62728")
        ax2.set_ylabel("回撤 (%)")
    ax2.set_title("回撤曲线")
    ax2.grid(True, alpha=0.3)

    # 3. 日收益分布直方图
    ax3 = axes[2]
    returns = results.get("daily_returns")
    if returns is not None and len(returns) > 1:
        arr = np.array(returns) * 100
        ax3.hist(arr, bins=50, color="#2ca02c", alpha=0.7, edgecolor="white")
        ax3.axvline(x=0, color="red", linestyle="--", linewidth=0.8)
        ax3.set_xlabel("日收益率 (%)")
        ax3.set_ylabel("频数")
    ax3.set_title("日收益分布")

    plt.tight_layout()
    if save_path:
        plt.savefig(save_path, dpi=150, bbox_inches="tight")
        print(f"图表已保存: {save_path}")
    plt.close()


def plot_kline_with_signals(df: pd.DataFrame, buy_signals: list | None = None,
                            sell_signals: list | None = None,
                            save_path: str = "kline_signals.png") -> None:
    """
    绘制 K 线图并标注买卖信号点
    df 需包含 open/high/low/close/volume，index 为日期
    """
    try:
        import mplfinance as mpf
    except ImportError:
        print("mplfinance 未安装，跳过 K 线图绘制")
        return

    df = df.copy()
    df.index = pd.to_datetime(df.index)

    # 构造买卖信号标记
    buys = pd.Series(np.nan, index=df.index)
    sells = pd.Series(np.nan, index=df.index)
    if buy_signals:
        for d in buy_signals:
            if d in df.index:
                buys[d] = df.loc[d, "low"] * 0.98
    if sell_signals:
        for d in sell_signals:
            if d in df.index:
                sells[d] = df.loc[d, "high"] * 1.02

    apds = []
    if buy_signals or sell_signals:
        apds.append(mpf.make_addplot(buys, type="scatter", markersize=80, marker="^", color="red"))
        apds.append(mpf.make_addplot(sells, type="scatter", markersize=80, marker="v", color="green"))

    kwargs = dict(
        type="candle", style="charles", volume=True,
        title="K线图 + 买卖信号", savefig=save_path,
        figsize=(14, 8)
    )
    if apds:
        kwargs["addplot"] = apds
    mpf.plot(df, **kwargs)
    print(f"K线图已保存: {save_path}")
