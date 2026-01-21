"""
海龟交易系统 - 新股评估脚本
交互式输入股票代码，获取买入点、止损点和加仓点建议
"""

from turtle_config import (
    TOTAL_CAPITAL,
    RISK_RATIO,
    TREND_MA_PERIOD,
    VOLUME_RATIO_THRESHOLD,
)
from turtle_core import (
    fetch_latest_data,
    analyze_market_state,
    detect_signal,
    compute_position,
    compute_stop_loss,
    compute_add_points,
)


def evaluate_stock(code):
    """
    评估单只股票的建仓价值
    输出买入点、止损点和加仓点建议
    """
    print(f"\n正在获取 {code} 的数据...")

    # 获取数据
    df, latest, name = fetch_latest_data(code)

    if df is None:
        print(f"  [错误] 数据不足或获取失败，需要至少 70 个交易日的数据")
        return

    price = latest['Close']
    n_val = latest['N']
    ma60 = latest['MA60']

    print(f"\n{'='*55}")
    print(f"  {name} ({code})")
    print(f"{'='*55}")

    # 分析市场状态
    state = analyze_market_state(latest)
    trend_up = state['trend_up']
    trend_status = state['trend_status']
    is_volume_surge = state['is_volume_surge']
    volume_status = state['volume_status']
    atr_expanding = state['atr_expanding']
    volatility_status = state['volatility_status']

    # 检测信号
    signal = detect_signal(latest, trend_up, is_volume_surge, atr_expanding)
    signal_type = signal['signal_type']
    signal_msg = signal['signal_msg']
    filter_reasons = signal['filter_reasons']

    # 计算仓位
    position = compute_position(TOTAL_CAPITAL, RISK_RATIO, n_val, price)
    unit_shares = position['unit_shares']
    unit_cost = position['unit_cost']

    # 计算模拟止损
    stop_info = compute_stop_loss(price, n_val)
    stop_loss = stop_info['stop_loss']
    stop_loss_pct = stop_info['stop_loss_pct']

    # ========== 输出 ==========

    print(f"\n【当前状态】")
    print(f"  日期: {latest['Date']}")
    print(f"  收盘价: {price:.3f} | MA60: {ma60:.3f}")
    print(f"  趋势: {trend_status} | 成交量: {volume_status}")
    print(f"  波动率: {volatility_status} | N值(ATR20): {n_val:.4f}")

    print(f"\n【买入点位分析】")
    upper_55 = latest['Upper_55']
    upper_20 = latest['Upper_20']
    dist_55 = (upper_55 - price) / price * 100
    dist_20 = (upper_20 - price) / price * 100

    print(f"  55日高点: {upper_55:.3f} (距离 {dist_55:+.1f}%)")
    print(f"  20日高点: {upper_20:.3f} (距离 {dist_20:+.1f}%)")

    # 买入建议
    if signal_type == "BUY" and not filter_reasons:
        print(f"\n  ✅ 当前已突破，符合建仓条件")
        print(f"     信号: {signal_msg}")
    elif signal_type == "BUY" and filter_reasons:
        print(f"\n  ⚠️  虽有突破信号，但不建议立即建仓")
        print(f"     信号: {signal_msg}")
        print(f"     过滤原因:")
        for r in filter_reasons:
            print(f"       - {r}")
    elif price < upper_20:
        # 未突破，给出建议入场点
        if trend_up:
            print(f"\n  ➜ 建议: 突破 {upper_20:.3f} 可考虑建仓")
            if is_volume_surge and atr_expanding:
                print(f"     当前趋势向上 + 放量 + 波动扩张，突破后可积极介入")
            elif is_volume_surge or atr_expanding:
                print(f"     当前趋势向上，突破后可适度介入")
            else:
                print(f"     建议等待放量突破确认")
        else:
            print(f"\n  ➜ 当前趋势向下 (价格 < MA60)")
            print(f"     建议等待趋势转好后再考虑")
    else:
        print(f"\n  ➜ 当前无明确信号，继续观察")

    print(f"\n【仓位建议】")
    print(f"  账户资金: {TOTAL_CAPITAL:,} 元 | 风险系数: {RISK_RATIO*100}%")
    print(f"  建议仓位: {unit_shares} 股 (约 {unit_cost:,.0f} 元)")
    position_pct = unit_cost / TOTAL_CAPITAL * 100
    print(f"  占总资金: {position_pct:.1f}%")

    print(f"\n【止损 / 加仓】")
    print(f"  入场止损: {stop_loss:.3f} (入场后 {stop_loss_pct:+.1f}%)")

    # 假设以当前价格建仓，计算加仓点
    add_points = compute_add_points(price, n_val, price)
    add_prices = [f"{p['price']:.3f}" for p in add_points]
    print(f"  加仓点位: {' / '.join(add_prices)} (每上涨 0.5N)")

    # 风险提示
    print(f"\n【风险评估】")
    risk_factors = []
    if not trend_up:
        risk_factors.append("趋势向下")
    if not is_volume_surge:
        risk_factors.append("成交量不足")
    if not atr_expanding:
        risk_factors.append("波动收缩")

    if not risk_factors:
        print(f"  🟢 当前条件较好：趋势向上 + 放量 + 波动扩张")
    elif len(risk_factors) == 1:
        print(f"  🟡 存在风险: {risk_factors[0]}")
    else:
        print(f"  🔴 多重风险: {', '.join(risk_factors)}")

    print(f"\n{'='*55}")


def manage_position(code, cost, shares, last_add_price=0):
    """
    持仓管理：计算动态止损和加仓点
    输出N值、止损点、加仓点建议
    """
    print(f"\n正在获取 {code} 的数据...")

    # 获取数据
    df, latest, name = fetch_latest_data(code)

    if df is None:
        print(f"  [错误] 数据不足或获取失败，需要至少 70 个交易日的数据")
        return

    price = latest['Close']
    n_val = latest['N']
    ma60 = latest['MA60']
    high_20 = latest['High_20']

    print(f"\n{'='*55}")
    print(f"  {name} ({code}) - 持仓管理")
    print(f"{'='*55}")

    # 分析市场状态
    state = analyze_market_state(latest)
    trend_status = state['trend_status']
    volume_status = state['volume_status']
    volatility_status = state['volatility_status']

    # 计算盈亏
    profit_pct = (price - cost) / cost
    profit_loss = (price - cost) * shares
    profit_loss_pct = profit_pct * 100

    # 计算止损
    stop_info = compute_stop_loss(price, n_val, cost, last_add_price, high_20, shares)
    stop_loss = stop_info['stop_loss']
    stop_loss_pct = stop_info['stop_loss_pct']
    stop_type = stop_info['stop_type']

    # 计算加仓点位
    add_base = last_add_price if last_add_price > 0 else cost
    add_points = compute_add_points(add_base, n_val, price)

    # ========== 输出 ==========

    print(f"\n【当前状态】")
    print(f"  日期: {latest['Date']}")
    print(f"  收盘价: {price:.3f} | MA60: {ma60:.3f}")
    print(f"  趋势: {trend_status} | 成交量: {volume_status}")
    print(f"  波动率: {volatility_status}")

    print(f"\n【波动率指标】")
    print(f"  N值(ATR20): {n_val:.4f}")
    print(f"  20日均N: {latest['N_MA']:.4f}")
    atr_status = "扩张 ↑" if n_val > latest['N_MA'] else "收缩 ↓"
    print(f"  ATR状态: {atr_status}")
    print(f"  提示: N值越大代表波动越剧烈，止损和加仓点位会相应调整")

    print(f"\n【持仓信息】")
    if last_add_price > 0:
        print(f"  成本价: {cost:.3f} | 最后加仓价: {last_add_price:.3f}")
    else:
        print(f"  成本价: {cost:.3f}")
    print(f"  持仓数量: {shares} 股")
    print(f"  持仓市值: {price * shares:,.2f} 元")
    pnl_color = "+" if profit_loss >= 0 else ""
    print(f"  浮动盈亏: {pnl_color}{profit_loss:.2f} 元 ({pnl_color}{profit_loss_pct:.2f}%)")

    print(f"\n【止损策略】")
    print(f"  {stop_type}: {stop_loss:.3f} ({stop_loss_pct:+.2f}%)")
    distance_to_stop = (price - stop_loss) / n_val
    print(f"  当前距止损: {distance_to_stop:.2f}N (约 {(price - stop_loss)/price*100:.2f}%)")
    
    if profit_loss_pct > 10:
        print(f"  💡 盈利已超10%，当前使用移动止损保护利润")
    if price <= stop_loss:
        print(f"  ⚠️  警告: 已触及止损位，建议立即离场！")

    print(f"\n【加仓策略】")
    print(f"  加仓基准价: {add_base:.3f} {'(最后加仓价)' if last_add_price > 0 else '(成本价)'}")
    print(f"  加仓间隔: 0.5N = {0.5 * n_val:.3f} 元")
    print(f"  加仓点位:")
    for i, point in enumerate(add_points, 1):
        status_icon = "✓" if point['status'] == "已过" else "○"
        print(f"    {status_icon} 第{i}次: {point['price']:.3f} ({point['status']})")
    
    # 下一个加仓点提示
    next_add = None
    for point in add_points:
        if point['status'] == "待触发":
            next_add = point['price']
            break
    
    if next_add:
        dist_to_add = (next_add - price) / price * 100
        print(f"\n  💡 下次加仓点: {next_add:.3f} (还需上涨 {dist_to_add:+.2f}%)")
    else:
        print(f"\n  💡 所有加仓点已触发，建议不再加仓")

    # 风险提示
    print(f"\n【风险评估】")
    risk_factors = []
    if price < ma60:
        risk_factors.append("价格已跌破MA60趋势线")
    if profit_loss_pct < -10:
        risk_factors.append("浮亏超过10%")
    if price <= stop_loss * 1.05:
        risk_factors.append("接近止损位")

    if not risk_factors:
        print(f"  🟢 当前状态正常，继续持有")
    else:
        print(f"  🔴 风险提示:")
        for r in risk_factors:
            print(f"      - {r}")

    print(f"\n{'='*55}")


def main():
    """主函数，支持循环输入"""
    print("=" * 55)
    print("海龟交易系统 - 智能交易助手")
    print(f"账户资金: {TOTAL_CAPITAL:,} 元 | 风险系数: {RISK_RATIO*100}%")
    print(f"趋势均线: MA{TREND_MA_PERIOD} | 放量阈值: {VOLUME_RATIO_THRESHOLD}x")
    print("=" * 55)
    print("\n请选择功能模式:")
    print("  1 - 新股评估 (评估建仓价值，给出买入点、止损点、加仓点)")
    print("  2 - 持仓管理 (动态止损、加仓点分析，查看N值波动率)")
    print("  q - 退出\n")

    while True:
        try:
            mode = input("请选择功能 (1/2/q): ").strip()

            if mode.lower() in ('q', 'quit', 'exit'):
                print("\n再见！祝交易顺利！")
                break

            if not mode:
                continue

            if mode == '1':
                # 新股评估模式
                print("\n--- 新股评估模式 ---")
                code = input("请输入股票代码: ").strip()

                if not code:
                    continue

                if not code.isdigit() or len(code) != 6:
                    print("  [错误] 请输入6位数字的股票代码")
                    continue

                evaluate_stock(code)

            elif mode == '2':
                # 持仓管理模式
                print("\n--- 持仓管理模式 ---")
                code = input("请输入股票代码: ").strip()

                if not code:
                    continue

                if not code.isdigit() or len(code) != 6:
                    print("  [错误] 请输入6位数字的股票代码")
                    continue

                try:
                    cost = float(input("请输入成本价: ").strip())
                    shares = int(input("请输入持仓数量: ").strip())
                    
                    last_add_input = input("最后加仓价 (没有加仓请直接回车): ").strip()
                    last_add_price = float(last_add_input) if last_add_input else 0

                    manage_position(code, cost, shares, last_add_price)

                except ValueError:
                    print("  [错误] 请输入有效的数字")
                    continue

            else:
                print("  [错误] 请输入 1 或 2 选择功能模式")

        except KeyboardInterrupt:
            print("\n\n已中断，再见！")
            break
        except Exception as e:
            print(f"  [错误] {e}")

    print("\n提示: 此脚本基于 AkShare 免费接口，仅供学习参考，实盘请以券商为准。")


if __name__ == "__main__":
    main()
