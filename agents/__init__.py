"""
agents package

  master_agent 管理的（通过意图路由）:
  - chat_agent.py        对话 + 搜索 + 知识库 + 博客（实现层）
  - plan_executor.py     Plan-Execute 编排引擎
  - intent_classifier.py 混合意图识别（正则 + 余弦）
  - email_agent.py       邮件发送

  独立 agent（不经过 master_agent，直接 API 调用）:
  - editor_agent.py      文章编辑（只操作 articles 表）

  工具模块：
  - scraper.py           网页爬取
  - chunker.py           文本切片
  - retriever.py         向量检索 + 切片管理
  - embedder.py          embedding
  - feishu_doc.py        飞书云文档
  - security.py          安全护栏
  - operation_guard.py   操作级安全护栏
  - keyword_extractor.py 关键词提取
  - time_tool.py         时间工具

  后续（脚本调度，非 agent）:
  - 日报定时任务 → GitHub Action / cron 调用 search → feishu → email
"""
