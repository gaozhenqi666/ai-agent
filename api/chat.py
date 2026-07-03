"""
api/chat.py
==========================================================
POST /api/chat        同步对话入口
POST /api/chat/stream 流式 SSE 对话入口
==========================================================
"""

from __future__ import annotations
import sys
from pathlib import Path

# 兼容 Vercel Serverless：把项目根加入 sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from flask import Blueprint, request, jsonify, Response
import json

from common import *
from common import log, E, ok, err
from master_agent import handle_request
from agents.chat_agent import handle_stream

chat_bp = Blueprint("chat", __name__)


@chat_bp.post("/api/chat")
def post_chat():
    """
    Body:
      {
        "session_id": "sess-xxx",  // 可选（空 = 新建）
        "message": "用户问题",
        "stream": false,            // 可选
        "options": { "model": "...", "temperature": 0.7 }
      }
    """
    payload = request.get_json(silent=True) or {}
    log.info(f"[api/chat] 收到请求 session_id={payload.get('session_id')} msg_len={len(payload.get('message') or '')}")

    result = handle_request(payload)

    # agent 内部错误
    if isinstance(result, dict) and result.get("error"):
        return jsonify(err(result.get("code", 5001), result.get("message", "unknown error"))), 500

    return jsonify(ok(result))


@chat_bp.post("/api/chat/stream")
def post_chat_stream():
    """
    流式 SSE 接口
    Body 同 /api/chat
    返回: text/event-stream
      event: start    → {session_id, user_message_id}
      event: content  → {delta: "一段文字"}
      event: done     → {session_id, assistant_message_id, duration_ms}
      event: error    → {message: "错误信息"}
    
    使用后台线程执行 handle_stream，客户端断开时后台线程继续完成
    （将回复存入数据库），用户返回后可继续查看对话。
    """
    payload = request.get_json(silent=True) or {}
    message = (payload.get("message") or "").strip()
    if not message:
        return jsonify(err(4002, "message 不能为空")), 400

    session_id = payload.get("session_id")
    options = payload.get("options") or {}

    log.info(f"[api/chat/stream] 收到流式请求 session_id={session_id}")

    import threading, queue

    event_queue: queue.Queue = queue.Queue()

    def worker():
        """后台线程：执行 handle_stream 到完成，即使客户端断开"""
        try:
            for event in handle_stream(message, session_id=session_id, options=options):
                event_queue.put(("event", event))
            event_queue.put(("done", None))
        except GeneratorExit:
            log.info("[api/chat/stream] 后台线程收到 GeneratorExit（客户端断开）")
            event_queue.put(("disconnected", None))
        except Exception as e:
            log.error(f"[api/chat/stream] 后台线程异常: {e}")
            event_queue.put(("error", str(e)))

    t = threading.Thread(target=worker, daemon=True)
    t.start()

    def generate():
        while True:
            try:
                typ, data = event_queue.get(timeout=0.1)
                if typ == "event":
                    yield f"event: {data['event']}\ndata: {json.dumps(data['data'], ensure_ascii=False)}\n\n"
                elif typ == "error":
                    yield f"event: error\ndata: {json.dumps({'message': str(data)}, ensure_ascii=False)}\n\n"
                    return
                elif typ in ("done", "disconnected"):
                    return
            except queue.Empty:
                if not t.is_alive():
                    break
                # 发送注释行作为 keep-alive（防止代理超时断开）
                yield ": keepalive\n\n"

    return Response(
        generate(),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


# 给 Vercel Python 入口
def handler(request):
    """Vercel 兼容入口"""
    return chat_bp.wsgi_app
