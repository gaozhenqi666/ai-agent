"""
agents/scraper.py
==========================================================
网页正文抓取工具
- 支持主流新闻/博客/知乎/微信公众号等
- 自动提取标题、正文、作者
- 反爬检测并提示用户
==========================================================
"""

from __future__ import annotations
import re
import sys
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from common import log

# 需要安装: pip install httpx beautifulsoup4 lxml
try:
    import httpx
    from bs4 import BeautifulSoup
except ImportError:
    log.warning("[scraper] 缺少依赖: pip install httpx beautifulsoup4 lxml")
    httpx = None
    BeautifulSoup = None


# 常见 User-Agent
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)


def scrape_url(url: str) -> dict:
    """
    抓取 URL 的正文内容
    返回:
      {
        "success": True,
        "title": "文章标题",
        "content": "正文纯文本",
        "author": "作者",
        "source_url": "原始 URL",
        "domain": "example.com",
      }
      或
      {
        "success": False,
        "error": "错误信息",
        "anti_scraping": True/False,  # 是否反爬
      }
    """
    if not httpx or not BeautifulSoup:
        return {"success": False, "error": "缺少依赖: pip install httpx beautifulsoup4 lxml", "anti_scraping": False}

    domain = urlparse(url).netloc

    try:
        # 发送请求
        resp = httpx.get(
            url,
            headers={
                "User-Agent": USER_AGENT,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            },
            follow_redirects=True,
            timeout=15,
        )

        # 检查状态码
        if resp.status_code == 403:
            return {"success": False, "error": "访问被拒绝（403），该网站可能有反爬机制", "anti_scraping": True}
        if resp.status_code == 429:
            return {"success": False, "error": "请求过于频繁（429），请稍后再试", "anti_scraping": True}
        if resp.status_code >= 400:
            return {"success": False, "error": f"HTTP 错误: {resp.status_code}", "anti_scraping": False}

        # 检查是否是反爬页面（验证码、登录等）
        html_text = resp.text
        anti_patterns = [
            r"验证码", r"captcha", r"verify.*robot",
            r"登录后查看", r"login.*required",
            r"access.*denied", r"blocked.*access",
        ]
        for pattern in anti_patterns:
            if re.search(pattern, html_text, re.IGNORECASE):
                return {
                    "success": False,
                    "error": f"检测到反爬机制（{pattern}），该网站需要登录或验证码",
                    "anti_scraping": True,
                }

        # 解析 HTML
        soup = BeautifulSoup(html_text, "lxml")

        # 提取标题
        title = _extract_title(soup)

        # 提取正文
        content = _extract_content(soup, domain)

        # 基础长度检查（提高阈值到 500 字符）
        if not content or len(content) < 500:
            return {
                "success": False,
                "error": f"正文过短（{len(content) if content else 0} 字符），可能不是有效文章",
                "anti_scraping": False,
            }

        # 严格的内容质量检查
        quality = _validate_article_content(content)
        if not quality["valid"]:
            return {
                "success": False,
                "error": f"内容质量不合格：{quality['reason']}",
                "anti_scraping": quality.get("anti_scraping", False),
            }

        # 提取作者
        author = _extract_author(soup)

        return {
            "success": True,
            "title": title,
            "content": content,
            "author": author,
            "source_url": url,
            "domain": domain,
        }

    except httpx.TimeoutException:
        return {"success": False, "error": "请求超时（15秒），网站可能无法访问", "anti_scraping": False}
    except httpx.ConnectError:
        return {"success": False, "error": "连接失败，网站可能无法访问", "anti_scraping": False}
    except Exception as e:
        log.error(f"[scraper] 抓取失败: {e}")
        return {"success": False, "error": f"抓取失败: {str(e)}", "anti_scraping": False}


def _extract_title(soup: BeautifulSoup) -> str:
    """提取文章标题"""
    # 1. og:title
    og = soup.find("meta", property="og:title")
    if og and og.get("content"):
        return og["content"].strip()

    # 2. <h1>
    h1 = soup.find("h1")
    if h1:
        return h1.get_text(strip=True)

    # 3. <title>
    if soup.title:
        return soup.title.get_text(strip=True)

    return "未知标题"


def _extract_author(soup: BeautifulSoup) -> str:
    """提取作者"""
    # 1. meta author
    meta = soup.find("meta", attrs={"name": "author"})
    if meta and meta.get("content"):
        return meta["content"].strip()

    # 2. 常见作者选择器
    selectors = [
        ".author", ".byline", ".writer", '[rel="author"]',
        ".article-author", ".post-author", ".news-author",
    ]
    for sel in selectors:
        el = soup.select_one(sel)
        if el:
            return el.get_text(strip=True)[:50]

    return ""


def _extract_content(soup: BeautifulSoup, domain: str) -> str:
    """提取正文内容"""
    # 移除无关标签
    for tag in soup.find_all(["script", "style", "nav", "header", "footer", "aside", "iframe"]):
        tag.decompose()

    # 尝试多种正文提取策略
    content = ""

    # 策略1: 通用正文容器选择器
    selectors = [
        "article", "main", ".article-content", ".post-content",
        ".article-body", ".post-body", ".entry-content",
        ".content", "#content", ".markdown-body", ".rich_media_content",
        ".article", ".post", ".news-content",
    ]
    for sel in selectors:
        el = soup.select_one(sel)
        if el:
            text = el.get_text(separator="\n", strip=True)
            if len(text) > len(content):
                content = text

    # 策略2: 如果上面没找到，用 <p> 标签拼接
    if len(content) < 100:
        paragraphs = soup.find_all("p")
        content = "\n".join(p.get_text(strip=True) for p in paragraphs if len(p.get_text(strip=True)) > 20)

    # 清理内容
    content = _clean_text(content)

    return content


def _clean_text(text: str) -> str:
    """清理文本"""
    # 移除多余空行
    text = re.sub(r'\n{3,}', '\n\n', text)
    # 移除行首行尾空格
    lines = [line.strip() for line in text.split('\n')]
    text = '\n'.join(line for line in lines if line)
    return text.strip()


# ========== 反爬/低质内容检测 ==========

# 反爬挑战页关键词
ANTI_SCRAPING_KEYWORDS = [
    r"Just a moment",                  # Cloudflare
    r"Verifying you are human",        # Cloudflare Turnstile
    r"This site requires you to enable JavaScript",
    r"Attention Required! \| Cloudflare",
    r"Access Denied",
    r"Please enable cookies",
    r"Checking your browser",
    r"DDoS protection by",
    r"Security check",
    r"verify.?human",
    r"window\.location\.href",         # JS 重定向
    r"document\.cookie",               # JS 设置 cookie
]

# AI 话术 / 推荐文案黑名单（这些是 LLM 生成的话术，不是文章正文）
AI_PROMPT_KEYWORDS = [
    r"^好的，我来帮你",            # "好的，我来帮你加入知识库"
    r"^当然[，。]",
    r"以下是.{0,30}的内容",
    r"以下是.{0,30}的总结",
    r"以上是.{0,30}的内容",
    r"如果你觉得有用",
    r"需要吗？",
    r"需要吗\?",
    r"以下是这篇",
    r"以下是这篇文章",
    r"以下是这篇.{0,30}的主要内容",
    r"以下是这篇.{0,30}的摘要",
    r"以下是这篇.{0,30}的总结",
    r"以下是对.{0,30}的总结",
    r"以下是对.{0,30}的分析",
    r"这篇.{0,20}主要.{0,30}了",
    r"这篇.{0,20}讲.{0,30}了",
    r"这篇.{0,20}介绍.{0,30}了",
    r"✅\s*已加入",
    r"📎\s*预览链接",
    r"📝\s*已存入",
    r"💡\s*",
    r"如果你后续想",
    r"随时告诉我",
    r"以下是.{0,30}的.{0,30}：",
    r"### \d+\. ",                  # AI 列表格式 "### 1. xxx"
    r"^###\s*OpenAI",                # 章节标题
    r"^###\s*Martin Fowler",
    r"^---$",                       # 分隔线（AI 输出常见）
    r"^##\s*\d+\.",                 # 章节编号
]

# 网站导航/页脚常见关键词（出现密度过高说明是导航不是文章）
NAV_KEYWORDS = [
    r"^(Privacy Policy|Terms of Service|Cookie Policy|About|Contact|Sign in|Sign up)$",
    r"^(Home|首页|关于|联系|登录|注册)$",
    r"© \d{4}",
    r"All rights reserved",
    r"Back to top",
    r"Skip to content",
    r"Press \w+ to open menu",
]


def _validate_article_content(content: str) -> dict:
    """
    严格验证内容是否为有效文章正文。
    返回 {"valid": True/False, "reason": "...", "anti_scraping": True/False}
    """
    if not content:
        return {"valid": False, "reason": "内容为空", "anti_scraping": False}

    text = content.strip()

    # 1. 反爬挑战页检测
    for pattern in ANTI_SCRAPING_KEYWORDS:
        m = re.search(pattern, text, re.IGNORECASE | re.MULTILINE)
        if m:
            log.warning(f"[scraper] 检测到反爬关键词: {pattern} → {m.group(0)[:50]}")
            return {
                "valid": False,
                "reason": f"检测到反爬/挑战页（{m.group(0)[:30]}），该网站阻止爬取",
                "anti_scraping": True,
            }

    # 2. AI 话术检测（开头或大量出现）
    # 检查开头 200 字符是否命中 AI 话术
    head = text[:300]
    for pattern in AI_PROMPT_KEYWORDS:
        m = re.search(pattern, head, re.IGNORECASE | re.MULTILINE)
        if m:
            log.warning(f"[scraper] 检测到 AI 话术: {pattern} → {m.group(0)[:50]}")
            return {
                "valid": False,
                "reason": f"内容看起来是 AI 生成的话术而非文章正文（{m.group(0)[:30]}）",
                "anti_scraping": False,
            }
    # 全文统计 AI 话术关键词密度
    ai_hits = 0
    for pattern in AI_PROMPT_KEYWORDS:
        ai_hits += len(re.findall(pattern, text, re.IGNORECASE | re.MULTILINE))
    if ai_hits >= 2:
        log.warning(f"[scraper] AI 话术关键词命中 {ai_hits} 次，疑似 AI 输出")
        return {
            "valid": False,
            "reason": f"内容包含 {ai_hits} 处 AI 话术模式，不是文章正文",
            "anti_scraping": False,
        }

    # 3. 段落结构检查
    paragraphs = [p.strip() for p in text.split('\n') if p.strip()]
    if len(paragraphs) < 2:
        return {
            "valid": False,
            "reason": f"段落数过少（{len(paragraphs)} 段），不像文章",
            "anti_scraping": False,
        }

    # 平均段落长度
    avg_len = sum(len(p) for p in paragraphs) / len(paragraphs)
    if avg_len < 40:
        return {
            "valid": False,
            "reason": f"平均段落长度过短（{avg_len:.0f} 字符），可能是导航/列表/页脚",
            "anti_scraping": False,
        }

    # 短行比例
    short_lines = sum(1 for p in paragraphs if len(p) < 20)
    short_ratio = short_lines / len(paragraphs)
    if short_ratio > 0.6:
        return {
            "valid": False,
            "reason": f"短行比例过高（{short_ratio:.0%}），可能是导航菜单",
            "anti_scraping": False,
        }

    # 4. 导航/页脚关键词密度
    nav_hits = 0
    for pattern in NAV_KEYWORDS:
        nav_hits += len(re.findall(pattern, text, re.MULTILINE))
    nav_density = nav_hits / max(1, len(paragraphs))
    if nav_density > 0.3:
        return {
            "valid": False,
            "reason": f"导航/页脚关键词密度过高（{nav_hits} 处），不是文章正文",
            "anti_scraping": False,
        }

    # 5. 中英文比例检查（如果几乎全是导航词，认为是英文导航页）
    # 正常文章应该有不少长段落
    long_paragraphs = sum(1 for p in paragraphs if len(p) >= 100)
    if long_paragraphs < 1:
        return {
            "valid": False,
            "reason": f"长段落数过少（{long_paragraphs} 段），不是有效文章",
            "anti_scraping": False,
        }

    return {"valid": True, "reason": "ok", "anti_scraping": False}


if __name__ == "__main__":
    # 测试内容验证
    test_cases = [
        # 有效文章
        ("机器学习是人工智能的一个分支。\n\n" * 10 + "深度学习是机器学习的一个子集，使用神经网络进行特征学习。" * 5, True),
        # 反爬页
        ("Just a moment...\nVerifying you are human", False),
        # AI 话术
        ("好的，我来帮你加入知识库。\n\n以下是这篇文档的主要内容。\n如果你觉得有用，需要吗？", False),
        # 导航/页脚
        ("Home\nAbout\nPrivacy Policy\nContact\n© 2024 All rights reserved", False),
    ]
    for content, should_pass in test_cases:
        result = _validate_article_content(content)
        status = "✓" if result["valid"] == should_pass else "✗"
        print(f"{status} 预期 {'通过' if should_pass else '拒绝'} | 实际 {'通过' if result['valid'] else '拒绝'} | {result['reason'][:60]}")
        if not result['valid']:
            print(f"    reason: {result['reason']}")


if __name__ == "__main__":
    # 测试爬取
    import json
    url = "https://jalammar.github.io/illustrated-transformer/"
    result = scrape_url(url)
    print(json.dumps({k: v[:200] if isinstance(v, str) and len(v) > 200 else v for k, v in result.items()}, ensure_ascii=False, indent=2))
