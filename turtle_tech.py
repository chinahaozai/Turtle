"""
海龟交易系统 - 持仓监控脚本
用于分析已持仓股票的信号、止损和加仓点位
"""

import time

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


# ================= 持仓配置 =================
# cost: 加权平均成本价，0 表示未持仓/观察中
# shares: 总持仓股数
# last_add_price: 最后一次加仓价格（可选，用于计算止损；无加仓则不填或填 0）
HOLDINGS = [
    {"code": "588200", "name": "科创芯片 ETF", "cost": 1.426, "shares": 29800},
    {"code": "562500", "name": "机器人 ETF", "cost": 0.915, "shares": 30000},
    {"code": "002896", "name": "中大力德", "cost": 88.509, "shares": 400},
    {"code": "159326", "name": "电网设备 ETF", "cost": 1.641, "shares": 15000},
    {"code": "002371", "name": "北方华创", "cost": 373.639, "shares": 200, "last_add_price": 490.49},
    {"code": "518880", "name": "黄金 ETF", "cost": 6.036, "shares": 4600},
    {"code": "513180", "name": "恒生科技指数 ETF", "cost": 0.712, "shares": 43400},
    {"code": "513120", "name": "港股创新药 ETF", "cost": 1.546, "shares": 18500},
    {"code": "300059", "name": "东方财富", "cost": 23.375, "shares": 1000},
    {"code": "516120", "name": "化工50 ETF", "cost": 0.742, "shares": 55000},
]


def analyze_stock(stock_info, capital, risk_ratio):
    """分析单只股票，返回分析结果字典"""
    code = stock_info["code"]
    name = stock_info["name"]
    cost = stock_info.get("cost", 0)
    held_shares = stock_info.get("shares", 0)
    last_add_price = stock_info.get("last_add_price", 0)

    print(f"\n{'='*50}")
    print(f"正在分析: {name} ({code})")
    print(f"{'='*50}")

    # 获取数据并计算指标
    df, latest, _ = fetch_latest_data(code)

    if df is None:
        print(f"  [跳过] 数据不足，需要至少 70 个交易日")
        return None

    # 获取关键数据
    price = latest['Close']
    n_val = latest['N']
    ma60 = latest['MA60']
    high_20 = latest['High_20']

    # 分析市场状态
    state = analyze_market_state(latest)
    trend_up = state['trend_up']
    trend_status = state['trend_status']
    volume_ratio = state['volume_ratio']
    volume_status = state['volume_status']
    is_volume_surge = state['is_volume_surge']
    atr_expanding = state['atr_expanding']
    volatility_status = state['volatility_status']

    # 检测信号
    signal = detect_signal(latest, trend_up, is_volume_surge, atr_expanding)
    signal_type = signal['signal_type']
    signal_msg = signal['signal_msg']
    signal_strength = signal['signal_strength']
    filter_reasons = signal['filter_reasons']

    # 计算仓位
    position = compute_position(capital, risk_ratio, n_val, price)
    unit_shares = position['unit_shares']
    unit_cost = position['unit_cost']

    # 计算止损
    stop_info = compute_stop_loss(price, n_val, cost, last_add_price, high_20, held_shares)
    stop_loss = stop_info['stop_loss']
    stop_loss_pct = stop_info['stop_loss_pct']
    stop_type = stop_info['stop_type']

    # 计算盈亏
    if cost > 0 and held_shares > 0:
        profit_pct = (price - cost) / cost
        profit_loss = (price - cost) * held_shares
        profit_loss_pct = profit_pct * 100
    else:
        profit_loss = 0
        profit_loss_pct = 0

    # 计算加仓点位
    add_points = []
    if cost > 0:
        add_base = last_add_price if last_add_price > 0 else cost
        add_points = compute_add_points(add_base, n_val, price)

    # ========== 输出结果 ==========

    print(f"\n【基础数据】")
    print(f"  日期: {latest['Date']} | 收盘价: {price:.3f}")
    print(f"  N值(ATR20): {n_val:.4f} | MA60: {ma60:.3f}")

    print(f"\n【市场状态】")
    print(f"  趋势: {trend_status}")
    print(f"  成交量: {volume_status}")
    print(f"  波动率: {volatility_status}")

    print(f"\n【唐奇安通道】")
    print(f"  55日高点: {latest['Upper_55']:.3f} | 20日高点: {latest['Upper_20']:.3f}")
    print(f"  20日低点: {latest['Lower_20']:.3f} | 10日低点: {latest['Lower_10']:.3f}")

    if cost > 0 and held_shares > 0:
        print(f"\n【持仓信息】")
        if last_add_price > 0:
            print(f"  成本: {cost:.3f} | 最后加仓: {last_add_price:.3f} | 持仓: {held_shares} 股")
        else:
            print(f"  成本: {cost:.3f} | 持仓: {held_shares} 股")
        pnl_color = "+" if profit_loss >= 0 else ""
        print(f"  浮动盈亏: {pnl_color}{profit_loss:.2f} 元 ({pnl_color}{profit_loss_pct:.2f}%)")
        print(f"  {stop_type}: {stop_loss:.3f} ({stop_loss_pct:+.2f}%)")

        if add_points:
            add_info = [f"{p['price']:.3f}({p['status']})" for p in add_points]
            print(f"  加仓点位: {' / '.join(add_info)}")

        if profit_loss_pct > 20:
            print(f"  💰 盈利丰厚，建议逐步止盈或提高止损位保护利润")
    else:
        print(f"\n【建仓参考】")
        print(f"  建议仓位: {unit_shares} 股 (约 {unit_cost:.0f} 元)")
        print(f"  模拟止损: {stop_loss:.3f} (入场后 -2N)")

    print(f"\n【信号判断】")
    print(f"  原始信号: {signal_msg}")

    if filter_reasons:
        print(f"  ⚠️  过滤原因:")
        for reason in filter_reasons:
            print(f"      - {reason}")
        print(f"  最终建议: 观望，等待更好时机")
    else:
        if signal_type == "BUY":
            print(f"  ✅ 信号有效 (强度: {'★' * signal_strength})")
            print(f"  建议操作: 买入 {unit_shares} 股")
        elif signal_type == "SELL":
            print(f"  🔴 离场信号")
            if held_shares > 0:
                print(f"  建议操作: 减仓或清仓 (当前持仓 {held_shares} 股)")
            else:
                print(f"  建议操作: 观望，不宜入场")
        else:
            print(f"  继续持有，关注关键点位")

    time.sleep(0.3)

    return {
        "code": code,
        "name": name,
        "price": price,
        "cost": cost,
        "shares": held_shares,
        "profit_pct": profit_loss_pct if cost > 0 else 0,
        "profit_loss": profit_loss if cost > 0 else 0,
        "signal_type": signal_type,
        "signal_msg": signal_msg,
        "filter_reasons": filter_reasons,
        "trend_up": trend_up,
        "volume_ratio": volume_ratio,
        "unit_shares": unit_shares,
        "stop_loss": stop_loss,
        "stop_type": stop_type,
        "stop_loss_pct": stop_loss_pct,
    }


def print_summary(results):
    """打印汇总信息"""
    print("\n")
    print("=" * 60)
    print("【今日汇总】")
    print("=" * 60)

    buy_signals = []
    sell_signals = []
    filtered_signals = []

    total_value = 0
    total_cost = 0
    total_pnl = 0

    for r in results:
        if r is None:
            continue

        if r["cost"] > 0 and r["shares"] > 0:
            total_value += r["price"] * r["shares"]
            total_cost += r["cost"] * r["shares"]
            total_pnl += r["profit_loss"]

        if r["signal_type"] == "BUY":
            if r["filter_reasons"]:
                filtered_signals.append(r)
            else:
                buy_signals.append(r)
        elif r["signal_type"] == "SELL":
            sell_signals.append(r)

    valid_results = [r for r in results if r is not None and r["cost"] > 0]
    if valid_results:
        print(f"\n📊 持仓概览:")
        print(f"   总市值: {total_value:,.0f} 元 | 总成本: {total_cost:,.0f} 元")
        pnl_pct = (total_value - total_cost) / total_cost * 100 if total_cost > 0 else 0
        print(f"   总盈亏: {total_pnl:+,.0f} 元 ({pnl_pct:+.2f}%)")

        sorted_results = sorted(valid_results, key=lambda x: x["profit_pct"], reverse=True)
        print(f"\n   盈亏排名:")
        for r in sorted_results:
            print(f"   {r['name']}: {r['profit_pct']:+.2f}%")

    if buy_signals:
        print(f"\n🟢 有效买入信号:")
        for r in buy_signals:
            print(f"   {r['name']} ({r['code']}) - {r['signal_msg']}")
            print(f"      建议: 买入 {r['unit_shares']} 股 @ {r['price']:.3f}")

    if sell_signals:
        print(f"\n🔴 卖出信号:")
        for r in sell_signals:
            print(f"   {r['name']} ({r['code']}) - {r['signal_msg']}")
            if r["shares"] > 0:
                print(f"      当前持仓: {r['shares']} 股, 止损位: {r['stop_loss']:.3f}")

    if filtered_signals:
        print(f"\n⚠️  被过滤的信号 (谨慎对待):")
        for r in filtered_signals:
            print(f"   {r['name']} ({r['code']}) - {r['signal_msg']}")
            print(f"      过滤原因: {'; '.join(r['filter_reasons'])}")

    if not buy_signals and not sell_signals and not filtered_signals:
        print(f"\n   今日无明确信号，继续观察")

    print("\n" + "=" * 60)


if __name__ == "__main__":
    print("=" * 60)
    print("海龟交易法则 - A股优化版 v3 (模块化)")
    print(f"账户资金: {TOTAL_CAPITAL:,} 元 | 风险系数: {RISK_RATIO*100}%")
    print(f"趋势均线: MA{TREND_MA_PERIOD} | 放量阈值: {VOLUME_RATIO_THRESHOLD}x")
    print("=" * 60)

    results = []
    for stock in HOLDINGS:
        result = analyze_stock(stock, TOTAL_CAPITAL, RISK_RATIO)
        results.append(result)

    print_summary(results)

    print("\n提示: 此脚本基于 AkShare 免费接口，仅供学习参考，实盘请以券商为准。")
