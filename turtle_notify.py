"""
海龟交易系统 - 飞书通知脚本
通过飞书 Webhook 推送每日持仓分析结果（Interactive Card 格式）
支持从飞书电子表格读取持仓数据

环境变量:
  FEISHU_WEBHOOK         - 飞书机器人 Webhook URL（必填）
  FEISHU_APP_ID          - 飞书应用 App ID（可选，用于读取表格）
  FEISHU_APP_SECRET      - 飞书应用 App Secret（可选）
  FEISHU_SPREADSHEET     - 飞书表格 token（可选，从表格 URL 中获取）
"""

import os
import json
import requests
from datetime import datetime

from turtle_config import TOTAL_CAPITAL, RISK_RATIO
from turtle_tech import HOLDINGS as DEFAULT_HOLDINGS, analyze_stock


# ================= 飞书表格读取 =================

def _get_tenant_token(app_id, app_secret):
    """获取飞书 tenant_access_token"""
    resp = requests.post(
        "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
        json={"app_id": app_id, "app_secret": app_secret},
        timeout=10,
    )
    resp.raise_for_status()
    data = resp.json()
    if data.get("code") != 0:
        raise RuntimeError(f"获取飞书 token 失败: {data}")
    return data["tenant_access_token"]


def _get_first_sheet_id(token, spreadsheet_token):
    """获取电子表格第一个工作表的 sheet_id"""
    resp = requests.get(
        f"https://open.feishu.cn/open-apis/sheets/v3/spreadsheets/{spreadsheet_token}/sheets/query",
        headers={"Authorization": f"Bearer {token}"},
        timeout=10,
    )
    resp.raise_for_status()
    data = resp.json()
    sheets = data.get("data", {}).get("sheets", [])
    if not sheets:
        raise RuntimeError("表格中没有工作表")
    return sheets[0]["sheet_id"]


def _read_sheet_values(token, spreadsheet_token, sheet_id):
    """读取工作表全部数据"""
    resp = requests.get(
        f"https://open.feishu.cn/open-apis/sheets/v2/spreadsheets/{spreadsheet_token}/values/{sheet_id}",
        headers={"Authorization": f"Bearer {token}"},
        timeout=10,
    )
    resp.raise_for_status()
    data = resp.json()
    return data.get("data", {}).get("valueRange", {}).get("values", [])


def _resolve_wiki_token(token, wiki_token):
    """如果是知识库链接，解析出实际的电子表格 token"""
    resp = requests.get(
        f"https://open.feishu.cn/open-apis/wiki/v2/spaces/get_node?token={wiki_token}",
        headers={"Authorization": f"Bearer {token}"},
        timeout=10,
    )
    resp.raise_for_status()
    data = resp.json()
    if data.get("code") != 0:
        return None
    node = data.get("data", {}).get("node", {})
    if node.get("obj_type") == "sheet":
        return node["obj_token"]
    return None


def fetch_holdings_from_feishu():
    """
    从飞书电子表格读取持仓数据
    表格列: A=代码, B=名称, C=成本价, D=持仓数量, E=最后加仓价(可选)
    第一行为表头，自动跳过
    """
    app_id = os.environ.get("FEISHU_APP_ID", "")
    app_secret = os.environ.get("FEISHU_APP_SECRET", "")
    spreadsheet_token = os.environ.get("FEISHU_SPREADSHEET", "")

    if not all([app_id, app_secret, spreadsheet_token]):
        return None

    print("正在从飞书表格读取持仓数据...")
    token = _get_tenant_token(app_id, app_secret)

    # 尝试解析知识库 token 为实际表格 token
    resolved = _resolve_wiki_token(token, spreadsheet_token)
    if resolved:
        print(f"  已从知识库解析表格 token")
        spreadsheet_token = resolved

    sheet_id = _get_first_sheet_id(token, spreadsheet_token)
    rows = _read_sheet_values(token, spreadsheet_token, sheet_id)

    if len(rows) < 2:
        print("  [警告] 表格数据不足，使用默认持仓")
        return None

    holdings = []
    for row in rows[1:]:  # 跳过表头
        if not row or not row[0]:
            continue
        code = str(row[0]).strip()
        name = str(row[1]).strip() if len(row) > 1 and row[1] else code
        cost = float(row[2]) if len(row) > 2 and row[2] else 0
        shares = int(float(row[3])) if len(row) > 3 and row[3] else 0
        last_add_price = float(row[4]) if len(row) > 4 and row[4] else 0

        entry = {"code": code, "name": name, "cost": cost, "shares": shares}
        if last_add_price > 0:
            entry["last_add_price"] = last_add_price
        holdings.append(entry)

    print(f"  读取到 {len(holdings)} 只持仓")
    return holdings


# ================= 飞书卡片构建 =================

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
            line = (
                f"{icon} {r['name']}({r['code']})  "
                f"**{r['profit_pct']:+.2f}%**  "
                f"{r['profit_loss']:+,.0f}元  "
                f"收盘:{r['price']:.3f}\n"
                f"     止损:{r['stop_loss']:.3f}({r['stop_loss_pct']:+.1f}%) {r['stop_type']}"
            )
            # 当实际止损与基准止损不同时，附加基准参考
            if abs(r["base_stop"] - r["stop_loss"]) > 0.001:
                line += f"  |  基准(价-2N):{r['base_stop']:.3f}"
            ranking_lines.append(line)
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

    # 优先从飞书表格读取，失败则用默认持仓
    holdings = fetch_holdings_from_feishu()
    if holdings is None:
        print("使用代码中的默认持仓配置")
        holdings = DEFAULT_HOLDINGS

    date_str = datetime.now().strftime("%Y-%m-%d")
    print(f"海龟交易监控 - 飞书通知 ({date_str})")
    print(f"持仓数量: {len(holdings)}")
    print()

    # 分析所有持仓
    results = []
    for stock in holdings:
        result = analyze_stock(stock, TOTAL_CAPITAL, RISK_RATIO)
        results.append(result)

    # 构建卡片并发送
    card = build_card(results, date_str)
    print("\n正在发送飞书通知...")
    send_feishu(webhook_url, card)
    print("发送成功!")


if __name__ == "__main__":
    main()
