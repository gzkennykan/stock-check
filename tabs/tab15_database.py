"""Tab 15: 数据中心 — 本地数据库管理 & 批量数据下载"""
import streamlit as st
import pandas as pd
from pathlib import Path
from datetime import datetime, timedelta
from data.database import (
    get_db_stats, get_stocks_in_db, get_kline, search_kline,
    insert_kline, insert_kline_batch, upsert_stock_info,
    delete_kline, delete_non_target_stocks, get_board_stats,
    get_connection,
)
from data.fetcher import fetch_data, _detect_source
from data.import_csv import _find_kline_csvs, import_csv_to_db
from data.tdx_reader import (
    scan_vipdoc, import_vipdoc_to_db_direct, import_vipdoc_to_db_incremental,
)
from data.sync import sync_daily, sync_from_tdx
from config import DATA_DIR, DB_PATH


def _render_stats():
    """渲染数据库概览"""
    stats = get_db_stats()

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("股票数量", f"{stats['stock_count']:,}")
    with col2:
        st.metric("数据总行数", f"{stats['total_rows']:,}")
    with col3:
        st.metric("数据库大小", f"{stats['db_size_mb']} MB")
    with col4:
        date_range = "-"
        if stats["min_date"] and stats["max_date"]:
            date_range = f"{stats['min_date']} ~ {stats['max_date']}"
        st.metric("日期范围", date_range)

    if stats["sources"]:
        st.caption("数据源分布: " + ", ".join(
            f"{s['source']}: {s['count']:,}" for s in stats["sources"]
        ))

    # 板块分布
    board = get_board_stats()
    if not board.empty:
        st.markdown("**板块分布**")
        cols = st.columns(len(board))
        for i, (_, r) in enumerate(board.iterrows()):
            with cols[i]:
                color = "#1E88E5" if r["board"] in ("上海主板", "深主板", "创业板", "科创板") else "#BDBDBD"
                st.metric(r["board"], f"{r['stock_count']} 只",
                          delta=f"{r['rows']:,} 行")
                st.caption(f"关注{'✅' if color == '#1E88E5' else '❌'}")


def _render_stock_list():
    """渲染数据库中的股票列表"""
    df = get_stocks_in_db()
    if df.empty:
        st.info("数据库中暂无数据，请先下载或导入")
        return

    display = df.copy()
    display["data_start"] = display["data_start"].dt.strftime("%Y-%m-%d")
    display["data_end"] = display["data_end"].dt.strftime("%Y-%m-%d")
    display = display.rename(columns={
        "symbol": "代码", "name": "名称", "market": "市场",
        "data_start": "起始日期", "data_end": "结束日期",
        "rows": "数据行数",
    })

    st.dataframe(
        display,
        use_container_width=True,
        hide_index=True,
        column_config={
            "代码": st.column_config.TextColumn(width="small"),
            "名称": st.column_config.TextColumn(width="small"),
        },
    )
    st.caption(f"共 {len(display)} 只股票")


def _render_download():
    """渲染批量数据下载面板"""
    st.subheader("📥 批量下载历史数据")

    col1, col2 = st.columns([3, 1])
    with col1:
        symbols_input = st.text_area(
            "股票代码（每行一个，或逗号/空格分隔）",
            placeholder="600036\n000001\n002594\n300750",
            height=100,
        )
    with col2:
        start_date = st.date_input("起始日期", value=datetime(2023, 1, 1))
        end_date = st.date_input("结束日期", value=datetime.today())

    # 解析代码
    symbols = []
    if symbols_input.strip():
        parts = symbols_input.replace(",", " ").split()
        for p in parts:
            p = p.strip()
            if p.isdigit() and len(p) == 6:
                symbols.append(p)

    if symbols:
        st.caption(f"识别到 {len(symbols)} 个有效代码: {', '.join(symbols[:10])}"
                   + ("..." if len(symbols) > 10 else ""))

    if st.button("⬇️ 开始下载", type="primary", disabled=not symbols,
                 use_container_width=True):
        progress = st.progress(0)
        status = st.empty()
        results = {"success": 0, "fail": 0, "rows": 0, "errors": []}

        for i, sym in enumerate(symbols):
            status.text(f"正在下载 {sym} ({i+1}/{len(symbols)})...")
            try:
                df = fetch_data(
                    sym,
                    start_date.strftime("%Y-%m-%d"),
                    end_date.strftime("%Y-%m-%d"),
                    use_cache=False,  # 强制从网络获取以更新 DB
                )
                results["success"] += 1
                results["rows"] += len(df)
            except Exception as e:
                results["fail"] += 1
                results["errors"].append(f"{sym}: {e}")
            progress.progress((i + 1) / len(symbols))

        status.empty()
        progress.empty()

        col_ok, col_fail, col_rows = st.columns(3)
        with col_ok:
            st.metric("成功", f"{results['success']} 只")
        with col_fail:
            st.metric("失败", f"{results['fail']} 只")
        with col_rows:
            st.metric("数据行数", f"{results['rows']:,}")
        if results["errors"]:
            with st.expander(f"错误详情 ({len(results['errors'])})"):
                for e in results["errors"]:
                    st.warning(e)


def _render_csv_import():
    """渲染 CSV → DB 导入面板"""
    st.subheader("📦 从 CSV 导入")

    csv_files = _find_kline_csvs(DATA_DIR)
    if not csv_files:
        st.info("data_cache 中没有单股日线 CSV 文件")
        return

    # 显示可导入的文件
    existing = get_stocks_in_db()
    existing_symbols = set(existing["symbol"].tolist()) if not existing.empty else set()

    file_info = []
    for f in csv_files:
        sym = f.stem
        try:
            df = pd.read_csv(f, index_col=0, parse_dates=True)
            in_db = sym in existing_symbols
            file_info.append({
                "代码": sym,
                "CSV行数": len(df),
                "日期范围": f"{df.index.min().date()} ~ {df.index.max().date()}",
                "已在DB": "✅" if in_db else "❌",
            })
        except Exception:
            pass

    if file_info:
        st.dataframe(
            pd.DataFrame(file_info),
            use_container_width=True,
            hide_index=True,
        )
        st.caption(f"共 {len(file_info)} 个 CSV 文件（✅=已在库中, ❌=待导入）")

    col1, col2 = st.columns(2)
    with col1:
        if st.button("📥 导入全部 CSV", use_container_width=True):
            with st.spinner("导入中..."):
                result = import_csv_to_db(dry_run=False)
            st.success(f"导入完成: {result['imported']} 行 ({len(result['stocks'])} 只股票)")
            if result["errors"]:
                for e in result["errors"]:
                    st.warning(e)
            st.rerun()

    with col2:
        if st.button("🔍 预览（不写入）", use_container_width=True, key="csv_preview_btn"):
            result = import_csv_to_db(dry_run=True)
            st.info(f"预览: {len(result['stocks'])} 只股票, "
                    f"{sum(s['rows'] for s in result['stocks'])} 行")
            for s in result["stocks"]:
                st.write(f"  • {s['symbol']}: {s['rows']} 行 ({s['start']} ~ {s['end']})")


def _render_tdx_import():
    """渲染通达信 .day → DB 导入面板"""
    st.subheader("📡 从券商客户端导入 (通达信 .day)")

    # 自动扫描常见路径（从 config 统一读取）
    from config import TDX_VIPDOC_CANDIDATES, get_tdx_vipdoc_path
    found_paths = [p for p in TDX_VIPDOC_CANDIDATES if Path(p).exists()]

    # 如果手动配置了路径，也加入
    detected = get_tdx_vipdoc_path()
    if detected and str(detected) not in found_paths:
        found_paths.insert(0, str(detected))

    col_path, col_scan = st.columns([3, 1])
    with col_path:
        default_path = found_paths[0] if found_paths else ""
        vipdoc_path = st.text_input(
            "通达信 vipdoc 目录路径",
            value=default_path,
            placeholder="C:/zd_zxzq_gm/vipdoc",
            help="券商客户端数据目录，如 C:/zd_zxzq_gm/vipdoc",
        )
    with col_scan:
        st.caption("")  # 对齐占位
        scan_clicked = st.button("🔍 扫描", use_container_width=True,
                                 disabled=not vipdoc_path)

    if not vipdoc_path:
        if found_paths:
            st.info(f"检测到路径: {found_paths[0]}")
        else:
            st.warning(
                "未检测到券商客户端数据目录。"
                "请先在券商客户端中浏览日K线图以下载数据，"
                "或手动输入 vipdoc 目录路径。"
            )
        return

    vipdoc = Path(vipdoc_path)
    if not vipdoc.exists():
        st.error(f"路径不存在: {vipdoc_path}")
        return

    # 扫描文件
    day_files = scan_vipdoc(vipdoc)

    if not day_files:
        st.info(
            "该目录下没有 .day 文件。\n\n"
            "**如何下载数据:**\n"
            "1. 打开中信证券客户端\n"
            "2. 在日K线图上逐一浏览您关心的股票\n"
            "3. 客户端会自动下载历史数据到 vipdoc 目录\n"
            "4. 回到此页面刷新即可看到可导入的文件"
        )
        # 即使没有 .day 文件也显示目录信息
        st.caption(f"vipdoc 目录存在: {vipdoc}")
        for sub in ["sh/lday", "sz/lday", "bj/lday"]:
            sub_path = vipdoc / sub
            if sub_path.is_dir():
                fcnt = len(list(sub_path.glob("*.day")))
                st.caption(f"  {sub}/: {fcnt} 个 .day 文件")
        return

    # 统计
    total_rows = sum(f["estimated_rows"] for f in day_files)
    markets = set(f["market"] for f in day_files)
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("文件数", len(day_files))
    with col2:
        st.metric("预估行数", f"{total_rows:,}")
    with col3:
        st.metric("覆盖市场", ", ".join(markets))

    # 已有 vs 新增
    existing = get_stocks_in_db()
    existing_symbols = set(existing["symbol"].tolist()) if not existing.empty else set()
    new_count = sum(1 for f in day_files if f["symbol"] not in existing_symbols)
    update_count = sum(1 for f in day_files if f["symbol"] in existing_symbols)

    st.caption(
        f"其中 **{new_count}** 只股票尚未入库，"
        f"**{update_count}** 只将更新已有数据"
    )

    # 文件列表（可折叠）
    with st.expander(f"查看文件列表 ({len(day_files)} 个)", expanded=False):
        file_df = pd.DataFrame([{
            "代码": f["symbol"],
            "市场": f["market"].upper(),
            "文件大小(KB)": round(f["size"] / 1024, 1),
            "预估行数": f["estimated_rows"],
            "状态": "✅ 已在库" if f["symbol"] in existing_symbols else "🆕 新股票",
        } for f in day_files])
        st.dataframe(file_df, use_container_width=True, hide_index=True)

    # 导入按钮
    col_act1, col_act2, col_act3 = st.columns(3)
    with col_act1:
        if st.button("⚡ 增量同步（秒级）", type="primary", use_container_width=True,
                     help="只读取每个文件末尾最新记录，仅导入新增日期"):
            with st.spinner("增量同步中..."):
                progress = st.progress(0)
                status = st.empty()

                def on_progress(cur, tot, sym):
                    progress.progress(cur / tot)
                    if cur % 200 == 0:
                        status.text(f"[{cur}/{tot}] {sym}")

                result = import_vipdoc_to_db_incremental(
                    vipdoc, progress_callback=on_progress
                )
                progress.empty()
                status.empty()

            st.toast(
                f"新增 {result['imported']} 只，"
                f"跳过 {result.get('skipped', 0)} 只（已最新）"
            )
            if result["errors"]:
                with st.expander(f"错误 ({len(result['errors'])})"):
                    for e in result["errors"]:
                        st.warning(e)
            st.rerun()

    with col_act2:
        if st.button("📥 全量导入（较慢）", use_container_width=True,
                     help="重新解析全部历史数据，适合首次导入或数据修复"):
            with st.spinner("全量导入中..."):
                progress = st.progress(0)
                status = st.empty()

                def on_progress(cur, tot, sym):
                    progress.progress(cur / tot)
                    if cur % 200 == 0:
                        status.text(f"[{cur}/{tot}] {sym}")

                result = import_vipdoc_to_db_direct(
                    vipdoc, progress_callback=on_progress
                )
                progress.empty()
                status.empty()

            st.success(
                f"导入完成: {result['imported']:,} 行 "
                f"({len(result['stocks'])} 只股票)"
            )
            if result["errors"]:
                with st.expander(f"错误 ({len(result['errors'])})"):
                    for e in result["errors"]:
                        st.warning(e)
            st.rerun()

    with col_act3:
        if st.button("🔍 预览（不写入）", use_container_width=True, key="tdx_preview_btn"):
            from data.tdx_reader import parse_day_file

            preview = []
            for f in day_files[:10]:  # 只解析前10只预览
                try:
                    df = parse_day_file(f["path"])
                    if df is not None:
                        preview.append({
                            "代码": f["symbol"],
                            "行数": len(df),
                            "起始日期": str(df.index.min().date()),
                            "结束日期": str(df.index.max().date()),
                        })
                except Exception as e:
                    preview.append({
                        "代码": f["symbol"],
                        "行数": f"解析失败: {e}",
                        "起始日期": "-",
                        "结束日期": "-",
                    })

            if preview:
                st.dataframe(
                    pd.DataFrame(preview),
                    use_container_width=True,
                    hide_index=True,
                )
            else:
                st.warning("未能解析任何文件")


def _render_analysis():
    """渲染数据库内数据分析"""
    st.subheader("📊 数据内分析")

    df = get_stocks_in_db()
    if df.empty:
        st.info("数据库为空，请先下载数据")
        return

    # SQL 查询面板
    st.markdown("---")
    st.markdown("##### 🔍 自定义 SQL 查询")

    sql = st.text_area(
        "输入 SQL 查询（表名: daily_kline）",
        value="SELECT symbol, COUNT(*) as days, "
              "MIN(close) as min_close, MAX(close) as max_close, "
              "AVG(close) as avg_close\n"
              "FROM daily_kline\n"
              "GROUP BY symbol\n"
              "ORDER BY symbol",
        height=120,
    )
    if st.button("执行查询", key="run_sql"):
        try:
            conn = get_connection(read_only=True)
            result = conn.execute(sql).df()
            conn.close()
            st.dataframe(result, use_container_width=True, hide_index=True)
            st.caption(f"返回 {len(result)} 行")
        except Exception as e:
            st.error(f"查询错误: {e}")


def _render_sync():
    """每日同步最新数据"""
    st.subheader("🔄 每日数据同步")
    st.caption("收盘后一键拉取全部在库股票的最新交易日数据（使用 AKShare）")

    stats = get_db_stats()
    db_stocks = get_stocks_in_db()
    latest_date = stats.get("max_date", "")

    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("在库股票", f"{stats['stock_count']:,}")
    with col2:
        st.metric("最新数据日期", latest_date or "无")
    with col3:
        today = datetime.now().strftime("%Y-%m-%d")
        need_sync = latest_date and latest_date < today
        st.metric("是否需要同步", "✅ 需要" if need_sync else "✅ 已最新")

    # 方式一：一键同步
    st.markdown("---")
    col_a, col_b = st.columns([2, 1])
    with col_a:
        st.markdown("**方式一：AKShare 在线同步（收盘后）**")
        st.caption("用 AKShare 拉取最新交易日数据。每只股票约 0.15 秒，9253 只需约 23 分钟。")
    with col_b:
        if st.button("🔄 一键同步最新", type="primary", use_container_width=True, key="sync_btn"):
            with st.spinner("正在同步最新交易日数据（这可能需要几分钟）..."):
                progress = st.progress(0)
                status = st.empty()

                def on_progress(cur, tot, sym, st_msg):
                    progress.progress(cur / tot)
                    status.text(f"[{cur}/{tot}] {sym} {st_msg}")

                result = sync_daily(progress_cb=on_progress)
                progress.empty()
                status.empty()

                st.toast(f"更新 {result['updated']} 只，新增 {result['new_rows']} 行")
                if result["errors"]:
                    with st.expander(f"{len(result['errors'])} 个错误"):
                        for e in result["errors"]:
                            st.warning(e)
                st.rerun()

    # 方式二：TDX 本地同步
    st.markdown("---")
    col_c, col_d = st.columns([2, 1])
    with col_c:
        st.markdown("**方式二：券商客户端本地同步（秒级）**")
        st.caption("从通达信 vipdoc 目录导入。需先在券商客户端浏览过K线图以触发自动下载。")
    with col_d:
        from config import get_tdx_vipdoc_path
        detected_path = get_tdx_vipdoc_path()
        default_tdx = str(detected_path) if detected_path else "C:/zd_zxzq_gm/vipdoc"
        tdx_path = st.text_input("vipdoc 路径", value=default_tdx,
                                  key="sync_tdx_path", label_visibility="collapsed")
    if st.button("📡 从券商客户端同步", use_container_width=True, key="sync_tdx_btn"):
        with st.spinner("正在从券商客户端导入..."):
            result = sync_from_tdx(tdx_path if Path(tdx_path).exists() else None)
            st.toast(f"导入 {result['imported']} 行 ({len(result.get('stocks', []))} 只)")
            if result["errors"]:
                for e in result["errors"][:5]:
                    st.warning(e)
            st.rerun()

    st.markdown("---")
    st.caption(
        "💡 **推荐流程：** 每个交易日收盘后（15:30 后），打开券商客户端浏览一遍日K线图，"
        "然后点击「从券商客户端同步」即可秒级更新。若无券商客户端，使用「一键同步最新」通过 AKShare 在线拉取。"
    )


def _render_management():
    """渲染数据管理（删除等）"""
    st.subheader("🗑️ 数据管理")

    df = get_stocks_in_db()
    if df.empty:
        st.info("数据库为空")
        return

    # 板块清理
    st.markdown("##### 🧹 板块清理（仅保留关注的四大板块）")
    board = get_board_stats()
    if not board.empty:
        target_boards = board[board["board"].isin(["上海主板", "深主板", "创业板", "科创板"])]
        non_target = board[~board["board"].isin(["上海主板", "深主板", "创业板", "科创板"])]
        total_non = non_target["stock_count"].sum() if not non_target.empty else 0

        if total_non > 0:
            st.caption(f"当前有 **{int(total_non)}** 只非关注板块股票（北交所/B股/基金等），"
                       f"删除后可减少同步时间约 {int(total_non/9253*100)}%")
            if st.button("🗑️ 删除非关注板块数据", type="secondary",
                         help="仅保留上海主板(60)、深主板(00)、创业板(30)、科创板(688)",
                         key="cleanup_board"):
                result = delete_non_target_stocks()
                st.toast(f"已删除 {result['deleted_stocks']} 只股票, {result['deleted_rows']:,} 行")
                st.rerun()
        else:
            st.success("✅ 当前仅包含四大关注板块数据")

    # 删除指定股票数据
    st.markdown("##### 删除指定股票")
    symbols_in_db = df["symbol"].tolist()
    to_delete = st.multiselect(
        "选择要删除的股票（从数据库移除，不影响 CSV）",
        options=symbols_in_db,
        key="delete_stocks",
    )
    if to_delete:
        confirm = st.checkbox(f"确认删除 {len(to_delete)} 只股票的全部数据？此操作不可撤销")
        if confirm and st.button("❌ 确认删除", type="secondary"):
            for sym in to_delete:
                n = delete_kline(sym)
                st.toast(f"{sym}: 已删除 {n} 行")
            st.rerun()

    # 数据库文件信息
    st.markdown("---")
    st.markdown("##### 数据库文件")
    if DB_PATH.exists():
        size_mb = DB_PATH.stat().st_size / (1024 * 1024)
        st.write(f"📁 路径: `{DB_PATH}`")
        st.write(f"📏 大小: {size_mb:.2f} MB")
        st.write(f"🕐 修改时间: {datetime.fromtimestamp(DB_PATH.stat().st_mtime)}")


def render():
    st.title("🗄️ 数据中心")
    st.caption("本地 DuckDB 数据库 — 高性能历史数据分析引擎")

    sub1, sub2, sub3, sub4, sub5, sub6, sub7 = st.tabs([
        "📊 概览", "📋 股票列表", "🔄 日常同步", "📥 批量下载", "📦 CSV导入", "📡 TDX导入", "🔍 SQL查询"
    ])

    with sub1:
        _render_stats()
        st.markdown("---")
        _render_management()

    with sub2:
        _render_stock_list()

    with sub3:
        _render_sync()

    with sub4:
        _render_download()

    with sub5:
        _render_csv_import()

    with sub6:
        _render_tdx_import()

    with sub7:
        _render_analysis()
