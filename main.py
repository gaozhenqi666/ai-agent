"""
main.py
==========================================================
本地开发入口
- Flask app
- 挂载所有 blueprint
- 自动初始化数据库（运行 schema.sql）
- 启动 HTTP 服务（默认 :8000）
==========================================================
"""

from __future__ import annotations
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from flask import Flask, jsonify, send_from_directory, request as flask_request
from flask_cors import CORS

from common import *
from common import log, ok, err, Config

# 导入 blueprint
from api.chat      import chat_bp
from api.sessions  import sessions_bp
from api.knowledge import knowledge_bp
from api.system    import system_bp
from api.articles  import articles_bp
from api.tasks     import tasks_bp
from api.digest    import digest_bp

# 静态前端目录
WEB_DIR = ROOT / "web"

# ---------- 1. 初始化数据库 ----------
def init_db():
    """运行 schema.sql 建表（已存在则跳过）"""
    schema_path = ROOT / "schema.sql"
    if not schema_path.exists():
        log.warning(f"schema.sql 不存在: {schema_path}")
        return
    sql = schema_path.read_text(encoding="utf-8")

    # 先去除所有注释行（-- 开头），再按 ; 分割
    sql_no_comments = "\n".join(
        line for line in sql.splitlines() if not line.strip().startswith("--")
    )
    statements = [s.strip() for s in sql_no_comments.split(";") if s.strip()]

    try:
        for stmt in statements:
            db_exec(stmt)
        log.info(f"[init_db] 初始化完成：{len(statements)} 条 DDL")
    except Exception as e:
        log.error(f"[init_db] 失败: {e}")


# ---------- 2. Flask app ----------
app = Flask(__name__, static_folder=str(WEB_DIR), static_url_path="")
CORS(app)  # 本地开发允许跨域

# 挂载所有 API
app.register_blueprint(chat_bp)
app.register_blueprint(sessions_bp)
app.register_blueprint(knowledge_bp)
app.register_blueprint(system_bp)
app.register_blueprint(articles_bp)
app.register_blueprint(tasks_bp)
app.register_blueprint(digest_bp)


# ---------- 3. 前端静态文件（默认 index.html） ----------
@app.route("/")
def index():
    return send_from_directory(WEB_DIR, "index.html")


@app.route("/<path:path>")
def static_file(path):
    """所有 web/ 下的静态文件（articles.html, knowledge.html, editor.html, styles.css, ...）"""
    full = WEB_DIR / path
    if full.exists() and full.is_file():
        return send_from_directory(WEB_DIR, path)
    return send_from_directory(WEB_DIR, "index.html")  # SPA fallback


# ---------- 4. 错误处理 ----------
@app.errorhandler(404)
def not_found(e):
    return jsonify(err(404, f"接口不存在: {flask_request.path}")), 404


@app.errorhandler(500)
def internal_error(e):
    log.error(f"500 错误: {e}")
    return jsonify(err(500, f"服务器内部错误: {e}")), 500


# ---------- 5. 启动 ----------
if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--no-init-db", action="store_true", help="跳过数据库初始化")
    parser.add_argument("--local-db", action="store_true", help="使用本地文件 DB（data/dev.db）")
    args = parser.parse_args()

    # 如果指定了 --local-db，覆盖 Config 中的 TURSO_URL
    if args.local_db:
        db_path = ROOT / "data" / "dev.db"
        db_path.parent.mkdir(parents=True, exist_ok=True)
        os.environ["TURSO_URL"] = str(db_path)
        Config.TURSO_URL = str(db_path)
        log.info(f"[启动] 本地 DB 模式: {db_path}")

    print("=" * 60)
    print("🚀 Harness — 个人 AI 知识助手")
    print("=" * 60)
    print(f"📁 静态目录: {WEB_DIR}")
    print(f"🤖 LLM 模型: {Config.LLM_MODEL} ({Config.LLM_BASE_URL})")
    print(f"🗄️  数据库:   {Config.TURSO_URL[:50]}...")
    print(f"🌐 监听地址: http://{args.host}:{args.port}")
    print("=" * 60)

    if not args.no_init_db:
        try:
            init_db()
        except Exception as e:
            log.warning(f"跳过 DB 初始化: {e}")

    app.run(host=args.host, port=args.port, debug=True, use_reloader=False)
