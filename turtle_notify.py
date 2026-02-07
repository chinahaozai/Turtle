"""
海龟交易系统 - 飞书通知脚本
通过飞书 Webhook 推送每日持仓分析结果（Interactive Card 格式）
用法: FEISHU_WEBHOOK=<url> python turtle_notify.py
"""

import os
import json
import requests
from datetime import datetime

from turtle_config import TOTAL_CAPITAL, RISK_RATIO
from turtle_tech import HOLDINGS, analyze_stock


def build_card(results, date_str):
    """将分析结果构建为飞书消息卡片"""

    # 汇总数据
    total_value = 0
    total_cost = 0
    total_pnl = 0
    buy_signals = []
    sell_signals = []
    filtered_signals = []
    valid_results = []

    for r in results:
        if r is None:
            continue
        if r["cost"] > 0 and r["shares"] > 0:
            total_value += r["price"] * r["shares"]
            total_cost += r["cost"] * r["shares"]
            total_pnl += r["profit_loss"]
            valid_results.append(r)

        if r["signal_type"] == "BUY":
            if r["filter_reasons"]:
                filtered_signals.append(r)
            else:
                buy_signals.append(r)
        elif r["signal_type"] == "SELL":
            sell_signals.append(r)

    pnl_pct = (total_value - total_cost) / total_cost * 100 if total_cost > 0 else 0
    pnl_emoji = "📈" if total_pnl >= 0 else "📉"

    # 标题
    header_title = f"{pnl_emoji} 海龟监控日报 | {date_str} | 总盈亏 {total_pnl:+,.0f} 元 ({pnl_pct:+.2f}%)"
    header_color = "green" if total_pnl >= 0 else "red"

    elements = []

    # 持仓概览
    elements.append({
        "tag": "div",
        "text": {
            "tag": "lark_md",
            "content": (
                f"**持仓概览**\n"
                f"总市值: **{total_value:,.0f}** 元 | "
                f"总成本: **{total_cost:,.0f}** 元 | "
                f"总盈亏: **{total_pnl:+,.0f}** 元 (**{pnl_pct:+.2f}%**)"
            ),
        },
    })

    elements.append({"tag": "hr"})

    # 盈亏排名 + 止盈止损
    if valid_results:
        sorted_results = sorted(valid_results, key=lambda x: x["profit_pct"], reverse=True)
        ranking_lines = []
        for i, r in enumerate(sorted_results, 1):
            icon = "🟢" if r["profit_pct"] >= 0 else "🔴"
            ranking_lines.append(
                f"{icon} {r['name']}({r['code']})  "
                f"**{r['profit_pct']:+.2f}%**  "
                f"{r['profit_loss']:+,.0f}元  "
                f"收盘:{r['price']:.3f}\n"
                f"     止损:{r['stop_loss']:.3f}({r['stop_loss_pct']:+.1f}%) {r['stop_type']}"
            )
        elements.append({
            "tag": "div",
            "text": {
                "tag": "lark_md",
                "content": "**盈亏排名**\n" + "\n".join(ranking_lines),
            },
        })
        elements.append({"tag": "hr"})

    # 买入信号
    if buy_signals:
        lines = []
        for r in buy_signals:
            lines.append(f"🟢 **{r['name']}**({r['code']}) - {r['signal_msg']}")
            lines.append(f"  建议买入 {r['unit_shares']} 股 @ {r['price']:.3f}")
        elements.append({
            "tag": "div",
            "text": {
                "tag": "lark_md",
                "content": "**有效买入信号**\n" + "\n".join(lines),
            },
        })

    # 卖出信号
    if sell_signals:
        lines = []
        for r in sell_signals:
            lines.append(f"🔴 **{r['name']}**({r['code']}) - {r['signal_msg']}")
            if r["shares"] > 0:
                lines.append(f"  持仓 {r['shares']} 股, 止损位: {r['stop_loss']:.3f}")
        elements.append({
            "tag": "div",
            "text": {
                "tag": "lark_md",
                "content": "**卖出信号**\n" + "\n".join(lines),
            },
        })

    # 被过滤信号
    if filtered_signals:
        lines = []
        for r in filtered_signals:
            lines.append(f"⚠️ **{r['name']}**({r['code']}) - {r['signal_msg']}")
            lines.append(f"  过滤: {'; '.join(r['filter_reasons'])}")
        elements.append({
            "tag": "div",
            "text": {
                "tag": "lark_md",
                "content": "**被过滤信号（谨慎对待）**\n" + "\n".join(lines),
            },
        })

    # 无信号
    if not buy_signals and not sell_signals and not filtered_signals:
        elements.append({
            "tag": "div",
            "text": {
                "tag": "lark_md",
                "content": "今日无明确信号，继续观察 🔍",
            },
        })

    # 底部备注
    elements.append({"tag": "hr"})
    elements.append({
        "tag": "note",
        "elements": [
            {
                "tag": "plain_text",
                "content": "数据来源: AkShare | 仅供学习参考，实盘请以券商为准",
            }
        ],
    })

    # 组装卡片
    card = {
        "msg_type": "interactive",
        "card": {
            "header": {
                "title": {
                    "tag": "plain_text",
                    "content": header_title,
                },
                "template": header_color,
            },
            "elements": elements,
        },
    }
    return card


def send_feishu(webhook_url, card):
    """发送飞书 Webhook 消息"""
    resp = requests.post(
        webhook_url,
        headers={"Content-Type": "application/json"},
        data=json.dumps(card),
        timeout=10,
    )
    resp.raise_for_status()
    body = resp.json()
    if body.get("code") != 0:
        raise RuntimeError(f"飞书返回错误: {body}")
    return body


def main():
    webhook_url = os.environ.get("FEISHU_WEBHOOK")
    if not webhook_url:
        print("[错误] 未设置环境变量 FEISHU_WEBHOOK")
        raise SystemExit(1)

    date_str = datetime.now().strftime("%Y-%m-%d")
    print(f"海龟交易监控 - 飞书通知 ({date_str})")
    print(f"持仓数量: {len(HOLDINGS)}")
    print()

    # 分析所有持仓
    results = []
    for stock in HOLDINGS:
        result = analyze_stock(stock, TOTAL_CAPITAL, RISK_RATIO)
        results.append(result)

    # 构建卡片并发送
    card = build_card(results, date_str)
    print("\n正在发送飞书通知...")
    send_feishu(webhook_url, card)
    print("发送成功!")


if __name__ == "__main__":
    main()
