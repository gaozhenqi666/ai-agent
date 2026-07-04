"""
agents/intent_classifier.py
==========================================================
混合意图识别：正则快速命中 + 余弦相似度兜底

- 正则层：高置信度直接返回（零 API 调用）
- 余弦层：正则未命中时，embed 用户消息与预设意图向量做余弦匹配
- 预设向量在首次调用时 embed 一次，缓存在内存中

intent 类型：chat / search / blog / knowledge / rewrite / daily / feishu
==========================================================
"""

from __future__ import annotations
import re
import json
from pathlib import Path
from common import log, cosine_similarity

# 缓存目录（跨进程复用，避免每次重启都 embed）
CACHE_DIR = Path(__file__).resolve().parent.parent / "data" / "cache"
CACHE_FILE = CACHE_DIR / "intent_embeddings.json"

# ---------- 1. 预设意图模板（语义描述，非关键词） ----------
INTENT_TEMPLATES: dict[str, str] = {
    "search":    "搜索查找检索网络上最新的资料论文文章教程推荐资源",
    "blog":      "生成博客写文章创作撰写写一篇关于某个主题的博客文章",
    "knowledge": "保存存入知识库收藏存储爬取网页内容加入知识库",
    "feishu":    "飞书保存到飞书云文档存到飞书整理到飞书放到飞书文档里",
    "email":     "发邮件发送邮件通知邮件确认邮件日报邮件",
    "rewrite":   "改写润色重写修改文字优化改进文章表达",
    "daily":     "早报日报每日简报汇总今日要闻生成日报",
    "chat":      "对话聊天回答问题解释说明讨论一般的日常交流",
}

# ---------- 2. 正则快速命中层 ----------
def _regex_intent(message: str) -> tuple[str, float]:
    """正则快速匹配，返回 (intent, confidence)，confidence < 1.0 表示不确定"""
    msg = message.strip().lower()

    # 高置信度模式（confidence=1.0）
    if re.search(r'(帮我|给我|请).{0,8}(找|搜|查|推荐).{0,20}(文章|论文|资料|教程)', msg):
        return ("search", 1.0)
    if re.search(r'(搜索|搜一下|搜|查找|检索|search|find).{0,10}(关于|一下|一篇|几篇|文章|论文|资料)', msg):
        return ("search", 1.0)
    if re.search(r'(生成|写|创作|撰写|来一篇|出一篇)\s*(博客|文章|blog)', msg):
        return ("blog", 1.0)
    if re.search(r'(存|加入|存入|放到|放进|保存到|收藏到)\s*(知识库|knowledge)|(爬取|爬).*(知识库|存)', msg):
        return ("knowledge", 1.0)
    if re.search(r'(存|保存|放到|放进|整理).*飞书|飞书.*(存|保存|整理|文档|云)', msg):
        return ("feishu", 1.0)
    if re.search(r'(改写|润色|重写|修改|rewrite|polish)', msg):
        return ("rewrite", 1.0)
    if re.search(r'(早报|日报|每日|daily|简报|汇总)', msg):
        return ("daily", 1.0)
    if re.search(r'(发邮件|发送邮件|邮件通知|邮件确认|send.*mail|email)', msg):
        return ("email", 1.0)

    # 中置信度（confidence=0.8）
    if re.search(r'(搜索|查找|检索|search)', msg):
        return ("search", 0.8)
    if re.search(r'(博客|blog|写文章)', msg):
        return ("blog", 0.8)
    if re.search(r'(知识库|knowledge)', msg):
        return ("knowledge", 0.8)
    if re.search(r'(飞书|feishu)', msg):
        return ("feishu", 0.8)

    return ("chat", 0.0)


# ---------- 3. 余弦相似度兜底层 ----------
_embeddings_cache: dict[str, list[float]] | None = None


def _load_cache() -> dict[str, list[float]] | None:
    """从磁盘加载预设向量缓存"""
    global _embeddings_cache
    if _embeddings_cache is not None:
        return _embeddings_cache
    if CACHE_FILE.exists():
        try:
            data = json.loads(CACHE_FILE.read_text())
            _embeddings_cache = {k: v for k, v in data.items()}
            log.info(f"[intent] 从缓存加载 {len(_embeddings_cache)} 个预设向量")
            return _embeddings_cache
        except Exception:
            pass
    return None


def _save_cache(embeddings: dict[str, list[float]]):
    """保存预设向量到磁盘"""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    CACHE_FILE.write_text(json.dumps(embeddings, ensure_ascii=False))
    global _embeddings_cache
    _embeddings_cache = embeddings
    log.info(f"[intent] 预设向量已缓存")


def _embed_intents() -> dict[str, list[float]]:
    """Embed 所有预设意图模板（只调用一次，结果缓存）"""
    cached = _load_cache()
    if cached and len(cached) == len(INTENT_TEMPLATES):
        return cached

    from tools.embedder_tool import embed_texts
    texts = list(INTENT_TEMPLATES.values())
    keys = list(INTENT_TEMPLATES.keys())

    log.info(f"[intent] 正在 embed {len(texts)} 个预设意图模板...")
    vectors = embed_texts(texts)
    result = {k: v for k, v in zip(keys, vectors)}
    _save_cache(result)
    return result


def _cosine_intent(message: str) -> tuple[str, float]:
    """余弦相似度匹配，返回 (best_intent, best_score)"""
    from tools.embedder_tool import embed_one

    embeddings = _embed_intents()
    msg_vec = embed_one(message)

    best_intent = "chat"
    best_score = 0.0

    for intent, vec in embeddings.items():
        score = cosine_similarity(msg_vec, vec)
        if score > best_score:
            best_score = score
            best_intent = intent

    log.info(f"[intent] 余弦匹配: {best_intent} (score={best_score:.3f})")
    return best_intent, best_score


# ---------- 4. 混合检测入口 ----------
def detect_intent_hybrid(message: str) -> dict:
    """
    混合意图检测：正则 + 余弦
    返回: {"intent": "search", "confidence": 0.95, "method": "regex|cosine|fallback"}
    """
    if not message or not message.strip():
        return {"intent": "chat", "confidence": 1.0, "method": "fallback"}

    # 第一层：正则
    intent, conf = _regex_intent(message)
    if conf >= 1.0:
        return {"intent": intent, "confidence": conf, "method": "regex"}

    # 第二层：余弦相似度（仅在正则不确定时）
    cosine_intent, cosine_score = _cosine_intent(message)

    # 合并：余弦分数 > 阈值 且 正则无明确匹配 → 用余弦结果
    if conf < 0.8 and cosine_score >= 0.75:
        return {"intent": cosine_intent, "confidence": cosine_score, "method": "cosine"}

    # 正则有一定置信度但不高 → 看余弦是否更强
    if cosine_score > conf + 0.1 and cosine_score >= 0.75:
        return {"intent": cosine_intent, "confidence": cosine_score, "method": "cosine"}

    # 兜底
    if conf > 0:
        return {"intent": intent, "confidence": conf, "method": "regex"}
    if cosine_score >= 0.45:  # 降低阈值：0.6 → 0.45，捕更多匹配
        return {"intent": cosine_intent, "confidence": cosine_score, "method": "cosine"}

    return {"intent": "chat", "confidence": 0.0, "method": "fallback"}


# ---------- 5. 独立测试 ----------
if __name__ == "__main__":
    tests = [
        "帮我搜索两篇关于AI的论文",
        "有没有最新的Transformer资料推荐",
        "帮我写一篇关于Python异步编程的博客",
        "把这个文字润色一下",
        "帮我把这篇文章存到知识库",
        "把刚才的搜索结果放到飞书云文档上",
        "今天有什么新闻",
        "你好，今天天气怎么样",
        "推荐几篇论文然后存到知识库里",
    ]
    for msg in tests:
        r = detect_intent_hybrid(msg)
        print(f"  [{r['method']:7s}] {r['intent']:10s} (conf={r['confidence']:.2f}) ← {msg[:50]}")
