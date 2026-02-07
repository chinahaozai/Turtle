"""
海龟交易系统 - 核心模块
包含数据获取、指标计算、信号判断、仓位计算等核心逻辑
"""

import os
import akshare as ak
import pandas as pd
from datetime import datetime

from turtle_config import (
    TREND_MA_PERIOD,
    VOLUME_MA_PERIOD,
    VOLUME_RATIO_THRESHOLD,
    ETF_PREFIXES,
    BYPASS_PROXY,
)

# 绕过系统代理，避免代理软件未运行时请求失败
if BYPASS_PROXY:
    for key in ['http_proxy', 'https_proxy', 'HTTP_PROXY', 'HTTPS_PROXY',
                'all_proxy', 'ALL_PROXY']:
        os.environ.pop(key, None)
    os.environ['NO_PROXY'] = '*'
    os.environ['no_proxy'] = '*'


def _exchange_prefix(code):
    """根据代码判断交易所前缀 (sh/sz)"""
    if code.startswith('6'):
        return 'sh'
    elif code.startswith(('0', '3')):
        return 'sz'
    # ETF: 51/52/56/58/59 -> 上海, 15/16 -> 深圳
    if code[:2] in ('51', '52', '56', '58', '59'):
        return 'sh'
    return 'sz'


def get_stock_data(code, start_date, end_date):
    """
    获取股票或 ETF 数据，自动识别类型并调用对应接口
    优先使用网易/新浪接口，东方财富接口作为备选
    返回统一格式的 DataFrame
    """
    df = None
    is_etf = any(code.startswith(p) for p in ETF_PREFIXES)
    prefix = _exchange_prefix(code)

    try:
        if is_etf:
            # 优先: 新浪 ETF 接口
            df = ak.fund_etf_hist_sina(symbol=f"{prefix}{code}")
            if df is not None and not df.empty:
                df = df.rename(columns={
                    'date': 'Date', 'open': 'Open', 'close': 'Close',
                    'high': 'High', 'low': 'Low', 'volume': 'Volume'
                })
                # 新浪接口返回全量数据，按日期过滤
                df['Date'] = pd.to_datetime(df['Date'])
                df = df[(df['Date'] >= start_date) & (df['Date'] <= end_date)]
                df['Date'] = df['Date'].dt.strftime('%Y-%m-%d')
                df = df.reset_index(drop=True)
        else:
            # 优先: 网易股票接口 (前复权)
            df = ak.stock_zh_a_daily(
                symbol=f"{prefix}{code}",
                start_date=start_date,
                end_date=end_date,
                adjust="qfq"
            )
            if df is not None and not df.empty:
                df = df.rename(columns={
                    'date': 'Date', 'open': 'Open', 'close': 'Close',
                    'high': 'High', 'low': 'Low', 'volume': 'Volume'
                })
    except Exception as e:
        print(f"  [备用接口] 主接口失败 ({e})，尝试东方财富接口...")
        # 备选: 东方财富接口
        try:
            if is_etf:
                df = ak.fund_etf_hist_em(
                    symbol=code, period="daily",
                    start_date=start_date, end_date=end_date,
                    adjust="qfq"
                )
            else:
                df = ak.stock_zh_a_hist(
                    symbol=code, period="daily",
                    start_date=start_date, end_date=end_date,
                    adjust="qfq"
                )
            if df is not None and not df.empty:
                df = df.rename(columns={
                    '日期': 'Date', '开盘': 'Open', '收盘': 'Close',
                    '最高': 'High', '最低': 'Low', '成交量': 'Volume'
                })
        except Exception as e2:
            print(f"  [错误] 数据获取失败: {e2}")
            return None

    return df


def get_stock_name(code):
    """
    获取股票或 ETF 名称，通过新浪实时行情接口
    """
    import requests

    prefix = _exchange_prefix(code)
    try:
        r = requests.get(
            f"https://hq.sinajs.cn/list={prefix}{code}",
            headers={"Referer": "https://finance.sina.com.cn/"},
            timeout=5,
        )
        # 格式: var hq_str_sz002371="北方华创,..."
        text = r.text
        if '="' in text:
            name = text.split('="')[1].split(',')[0]
            if name:
                return name
    except Exception:
        pass

    return f"未知({code})"


def calculate_indicators(df):
    """
    计算所有技术指标，返回添加了指标列的 DataFrame
    包含: TR, N(ATR20), 唐奇安通道, MA60, 成交量均线, ATR趋势
    """
    # 1. TR 和 N 值 (ATR20)
    prev_close = df['Close'].shift(1)
    df['TR'] = pd.concat([
        df['High'] - df['Low'],
        (df['High'] - prev_close).abs(),
        (df['Low'] - prev_close).abs()
    ], axis=1).max(axis=1)
    df['N'] = df['TR'].rolling(window=20).mean()

    # 2. 唐奇安通道 (shift(1) 避免未来函数)
    df['Upper_55'] = df['High'].rolling(window=55).max().shift(1)
    df['Upper_20'] = df['High'].rolling(window=20).max().shift(1)
    df['Lower_20'] = df['Low'].rolling(window=20).min().shift(1)
    df['Lower_10'] = df['Low'].rolling(window=10).min().shift(1)

    # 3. 趋势判断: MA60
    df['MA60'] = df['Close'].rolling(window=TREND_MA_PERIOD).mean()

    # 4. 成交量均线
    df['Volume_MA'] = df['Volume'].rolling(window=VOLUME_MA_PERIOD).mean()

    # 5. 波动率趋势: ATR 是否扩张
    df['N_MA'] = df['N'].rolling(window=20).mean()

    # 6. 计算近期最高价 (用于移动止损)
    df['High_20'] = df['High'].rolling(window=20).max()

    return df


def analyze_market_state(latest):
    """
    分析市场状态，返回趋势、成交量、波动率状态
    """
    price = latest['Close']
    ma60 = latest['MA60']
    volume = latest['Volume']
    volume_ma = latest['Volume_MA']

    # 趋势方向
    trend_up = price > ma60
    trend_status = "上升趋势 ↑" if trend_up else "下降趋势 ↓"

    # 成交量状态
    volume_ratio = volume / volume_ma if volume_ma > 0 else 1
    is_volume_surge = volume_ratio >= VOLUME_RATIO_THRESHOLD
    volume_status = f"放量 ({volume_ratio:.1f}x)" if is_volume_surge else f"缩量 ({volume_ratio:.1f}x)"

    # 波动率状态
    atr_expanding = latest['N'] > latest['N_MA']
    volatility_status = "波动扩张" if atr_expanding else "波动收缩"

    return {
        "trend_up": trend_up,
        "trend_status": trend_status,
        "volume_ratio": volume_ratio,
        "is_volume_surge": is_volume_surge,
        "volume_status": volume_status,
        "atr_expanding": atr_expanding,
        "volatility_status": volatility_status,
    }


def detect_signal(latest, trend_up, is_volume_surge, atr_expanding):
    """
    检测买卖信号，返回信号类型、消息和强度
    """
    price = latest['Close']

    signal_type = "HOLD"
    signal_msg = "持仓观察"
    signal_strength = 0

    # 买入信号检测
    break_55 = price > latest['Upper_55']
    break_20 = price > latest['Upper_20']

    # 卖出信号检测
    break_lower_10 = price < latest['Lower_10']
    break_lower_20 = price < latest['Lower_20']

    # 综合判断
    if break_55:
        signal_type = "BUY"
        signal_msg = "★★ 突破 55 日高点"
        signal_strength = 3 if (trend_up and is_volume_surge) else 2 if trend_up else 1
    elif break_20:
        signal_type = "BUY"
        signal_msg = "★ 突破 20 日高点"
        signal_strength = 2 if (trend_up and is_volume_surge) else 1 if trend_up else 0
    elif break_lower_10:
        signal_type = "SELL"
        signal_msg = "▼▼ 跌破 10 日低点 (短线离场)"
        signal_strength = 2
    elif break_lower_20:
        signal_type = "SELL"
        signal_msg = "▼ 跌破 20 日低点 (清仓信号)"
        signal_strength = 3

    # 信号过滤
    filter_reasons = []
    if signal_type == "BUY":
        if not trend_up:
            filter_reasons.append("价格在 MA60 下方，趋势向下")
        if not is_volume_surge:
            filter_reasons.append(f"成交量不足 ({latest['Volume']/latest['Volume_MA']:.1f}x < {VOLUME_RATIO_THRESHOLD}x)")
        if not atr_expanding:
            filter_reasons.append("波动率收缩，突破可能无效")

    return {
        "signal_type": signal_type,
        "signal_msg": signal_msg,
        "signal_strength": signal_strength,
        "filter_reasons": filter_reasons,
    }


def compute_position(capital, risk_ratio, n_val, price):
    """
    计算建仓仓位
    返回建议股数和预估金额
    """
    if n_val > 0:
        unit_shares = int((capital * risk_ratio) / n_val // 100) * 100
    else:
        unit_shares = 0

    unit_cost = unit_shares * price

    return {
        "unit_shares": unit_shares,
        "unit_cost": unit_cost,
    }


def compute_stop_loss(price, n_val, cost=0, last_add_price=0, high_20=0, held_shares=0):
    """
    计算止损位
    - 有持仓时：根据成本/加仓价计算，盈利超10%启用移动止损
    - 无持仓时：模拟止损 (当前价 - 2N)
    """
    if cost > 0 and held_shares > 0:
        # 确定止损基准价
        if last_add_price > 0:
            base_price = last_add_price
            base_type = "加仓"
        else:
            base_price = cost
            base_type = "成本"

        # 基础止损 (基准价 - 2N)
        base_stop = base_price - 2 * n_val

        # 移动止损 (20日最高价 - 2N)
        trailing_stop = high_20 - 2 * n_val

        # 计算盈亏
        profit_pct = (price - cost) / cost

        # 盈利超过 10% 时，启用移动止损
        if profit_pct > 0.1:
            stop_loss = max(base_stop, trailing_stop, cost)  # 至少保本
            stop_type = "移动止损"
        else:
            stop_loss = base_stop
            stop_type = f"固定止损({base_type})"

        stop_loss_pct = (stop_loss - price) / price * 100
    else:
        # 无持仓，模拟止损
        stop_loss = price - 2 * n_val
        stop_loss_pct = -2 * n_val / price * 100
        stop_type = "模拟止损"

    return {
        "stop_loss": stop_loss,
        "stop_loss_pct": stop_loss_pct,
        "stop_type": stop_type,
    }


def compute_add_points(base_price, n_val, current_price):
    """
    计算加仓点位
    经典海龟：每上涨 0.5N 加仓一次，最多加仓 3 次
    """
    add_points = []
    for i in range(1, 4):
        add_price = base_price + i * 0.5 * n_val
        status = "已过" if current_price >= add_price else "待触发"
        add_points.append({
            "price": add_price,
            "status": status,
        })
    return add_points


def fetch_latest_data(code, min_days=70):
    """
    获取股票最新数据并计算指标
    返回 (df, latest, name) 或 (None, None, None) 如果数据不足
    """
    current_date = datetime.now().strftime("%Y%m%d")
    start_date = "20230101"

    df = get_stock_data(code, start_date, current_date)

    if df is None or df.empty or len(df) < min_days:
        return None, None, None

    df = calculate_indicators(df)
    latest = df.iloc[-1]
    name = get_stock_name(code)

    return df, latest, name
