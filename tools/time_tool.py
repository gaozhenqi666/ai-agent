"""
agents/time_tool.py
==========================================================
时间工具：让 agent 知道现在是几号

提供：
- get_current_time() - 返回格式化的当前时间字符串
- get_current_context() - 返回适合注入到 system prompt 的时间上下文
- needs_time() - 检测消息是否需要时间感知

不依赖网络，纯本地时间。
==========================================================
"""

from __future__ import annotations
import re
from datetime import datetime, timezone, timedelta

# 中国时区（UTC+8）
CST = timezone(timedelta(hours=8))


def get_current_time() -> dict:
    """
    获取当前时间（中国时区）
    返回:
      {
        "datetime": "2026-07-02 21:30:45",  # 完整时间
        "date": "2026-07-02",                # 日期
        "time": "21:30:45",                  # 时间
        "weekday": "星期三",                   # 中文星期
        "year": 2026,
        "month": 7,
        "day": 2,
        "hour": 21,
        "timestamp": 1751465445,             # Unix 时间戳
        "iso": "2026-07-02T21:30:45+08:00",  # ISO 8601
      }
    """
    now = datetime.now(CST)
    weekday_cn = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"][now.weekday()]

    return {
        "datetime":   now.strftime("%Y-%m-%d %H:%M:%S"),
        "date":       now.strftime("%Y-%m-%d"),
        "time":       now.strftime("%H:%M:%S"),
        "weekday":    weekday_cn,
        "year":       now.year,
        "month":      now.month,
        "day":        now.day,
        "hour":       now.hour,
        "timestamp":  int(now.timestamp()),
        "iso":        now.isoformat(),
    }


def get_current_context() -> str:
    """
    返回适合注入到 system prompt 的时间上下文
    格式简洁，让 LLM 知道当前日期
    """
    t = get_current_time()
    return (
        f"【当前时间】\n"
        f"- 完整时间: {t['datetime']} ({t['weekday']})\n"
        f"- 日期: {t['date']}\n"
        f"- 时区: 中国标准时间 (UTC+8)\n"
        f"- 年份: {t['year']} 年"
    )


def needs_time(message: str) -> bool:
    """
    检测消息是否需要时间感知
    - 显式询问时间
    - 询问"最新"、"现在"、"今年"、"今天"
    - 询问"X 发生了什么事"（新闻类）
    - 请求生成报告/总结
    """
    time_keywords = [
        # 显式时间
        "几号", "今天", "现在", "当前", "今年", "明年", "去年", "本月", "上月", "下月",
        "本周", "上周", "下周", "今年", "最近", "最新", "此刻", "当下",
        # 时间相关
        "新闻", "动态", "发生了", "发生的事", "今天", "2024", "2025", "2026", "2027",
        "Q1", "Q2", "Q3", "Q4", "H1", "H2",
        # 报告/总结
        "报告", "周报", "月报", "日报", "年报", "总结", "复盘",
        "今年", "上半年", "下半年", "季度",
        # 时效性
        "刚刚", "刚才", "今天", "今早", "今晚", "今晨",
        # 英文
        "today", "now", "current", "latest", "recent", "this year", "this month",
        "yesterday", "tomorrow",
    ]

    msg_lower = message.lower()
    return any(kw.lower() in msg_lower for kw in time_keywords)


# 单元测试
if __name__ == "__main__":
    import json
    print(json.dumps(get_current_time(), ensure_ascii=False, indent=2))
    print()
    print(get_current_context())
    print()
    print("needs_time('今天几号'):", needs_time("今天几号"))
    print("needs_time('推荐Transformer文章'):", needs_time("推荐Transformer文章"))
    print("needs_time('本周AI新闻'):", needs_time("本周AI新闻"))
