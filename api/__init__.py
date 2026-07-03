"""
api package

按 API.md 模块划分：
- chat.py         POST /api/chat, /api/chat/stream
- sessions.py     GET/POST/DELETE /api/sessions, /api/sessions/{id}, /api/sessions/{id}/messages, ...
- knowledge.py    GET/POST/PATCH/DELETE /api/knowledge/articles, /api/knowledge/search, ...
- system.py       GET /api/health, /api/system/config, /api/system/stats
"""
