"""
agents/email_agent.py
==========================================================
邮件发送 Agent

职责：
  1. 发送邮件（SMTP）
  2. 日报确认邮件（daily_agent 调用）
  3. 通知邮件（其他 agent 调用）

配置（.env）：
  SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASS, SMTP_FROM

不交给 master_agent 管理 — 直接由 daily_agent / 其他模块调用。
==========================================================
"""

from __future__ import annotations
import smtplib
import sys
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from pathlib import Path

try:
    from common import log, Config
except ImportError:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from common import log, Config


def _get_smtp_config() -> dict:
    """从环境变量读取 SMTP 配置"""
    return {
        "host": Config("SMTP_HOST", "smtp.qq.com"),
        "port": int(Config("SMTP_PORT", "587")),
        "user": Config("SMTP_USER", ""),
        "password": Config("SMTP_PASS", ""),
        "from_addr": Config("SMTP_FROM", Config("SMTP_USER", "")),
    }


def send_email(
    to: str | list[str],
    subject: str,
    body: str,
    html: bool = False,
) -> dict:
    """
    发送邮件。

    返回:
      {"success": True, "message_id": "..."}
      {"success": False, "error": "..."}
    """
    cfg = _get_smtp_config()

    if not cfg["user"] or not cfg["password"]:
        return {"success": False, "error": "SMTP 未配置（缺少 SMTP_USER / SMTP_PASS）"}

    try:
        if html:
            msg = MIMEMultipart("alternative")
            msg.attach(MIMEText(body, "html", "utf-8"))
        else:
            msg = MIMEText(body, "plain", "utf-8")

        msg["Subject"] = subject
        msg["From"] = cfg["from_addr"]
        msg["To"] = to if isinstance(to, str) else ", ".join(to)

        with smtplib.SMTP(cfg["host"], cfg["port"], timeout=30) as server:
            server.starttls()
            server.login(cfg["user"], cfg["password"])
            server.send_message(msg)

        log.info(f"[email] 已发送: {subject} → {to}")
        return {"success": True}

    except smtplib.SMTPAuthenticationError:
        return {"success": False, "error": "SMTP 认证失败，请检查 SMTP_USER / SMTP_PASS"}
    except smtplib.SMTPConnectError:
        return {"success": False, "error": f"无法连接 SMTP 服务器 {cfg['host']}:{cfg['port']}"}
    except Exception as e:
        log.error(f"[email] 发送失败: {e}")
        return {"success": False, "error": str(e)}


def send_daily_confirmation(
    to: str,
    date_str: str,
    articles: list[dict],
    feishu_url: str = "",
) -> dict:
    """
    发送日报确认邮件。

    articles: [{title, url, snippet}, ...]
    """
    article_lines = "\n".join([
        f"  {i+1}. [{r['title']}]({r['url']})\n     {r.get('snippet', '')[:100]}..."
        for i, r in enumerate(articles)
    ])

    body = f"""
日报确认 — {date_str}

今日推荐文章：

{article_lines}

飞书文档：{feishu_url if feishu_url else '（生成中...）'}

---
此邮件由 Harness 自动生成，请勿回复。
"""
    return send_email(to=to, subject=f"日报确认 — {date_str}", body=body)


# ---------- 测试 ----------
if __name__ == "__main__":
    import json
    result = send_email(
        to=Config("TEST_EMAIL", ""),
        subject="Harness 邮件测试",
        body="这是一封来自 Harness 的测试邮件。",
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
