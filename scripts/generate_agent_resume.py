from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas
from reportlab.platypus import Paragraph


PAGE_W, PAGE_H = A4
LEFT_BAR_W = 36
CONTENT_X = 68
CONTENT_W = PAGE_W - CONTENT_X - 34

BLACK = colors.HexColor("#1F1F1F")
TEXT = colors.HexColor("#4C4C4C")
LIGHT_TEXT = colors.HexColor("#888888")
SIDEBAR = colors.HexColor("#D6D6D6")
GOLD = colors.HexColor("#C7A45A")

ROOT = Path(__file__).resolve().parent.parent
OUTPUT = ROOT / "output" / "pdf" / "agent_resume_harness.pdf"


def register_fonts() -> None:
    pdfmetrics.registerFont(TTFont("HeitiLight", "/System/Library/Fonts/STHeiti Light.ttc"))
    pdfmetrics.registerFont(TTFont("HeitiMedium", "/System/Library/Fonts/STHeiti Medium.ttc"))


def make_styles() -> dict[str, ParagraphStyle]:
    return {
        "meta": ParagraphStyle(
            "meta",
            fontName="HeitiLight",
            fontSize=10.3,
            leading=14.2,
            textColor=TEXT,
        ),
        "body": ParagraphStyle(
            "body",
            fontName="HeitiLight",
            fontSize=10.2,
            leading=15.0,
            textColor=TEXT,
        ),
        "bullet": ParagraphStyle(
            "bullet",
            fontName="HeitiLight",
            fontSize=10.2,
            leading=15.0,
            textColor=TEXT,
            leftIndent=13,
            firstLineIndent=-13,
        ),
        "project_title": ParagraphStyle(
            "project_title",
            fontName="HeitiMedium",
            fontSize=16.8,
            leading=19,
            textColor=BLACK,
        ),
        "subhead": ParagraphStyle(
            "subhead",
            fontName="HeitiMedium",
            fontSize=10.8,
            leading=14,
            textColor=BLACK,
        ),
        "date": ParagraphStyle(
            "date",
            fontName="HeitiLight",
            fontSize=9.8,
            leading=12,
            textColor=LIGHT_TEXT,
            alignment=2,
        ),
        "body_small": ParagraphStyle(
            "body_small",
            fontName="HeitiLight",
            fontSize=9.8,
            leading=14.2,
            textColor=TEXT,
        ),
    }


def draw_bg(c: canvas.Canvas) -> None:
    c.setFillColor(SIDEBAR)
    c.rect(0, 0, LEFT_BAR_W, PAGE_H, stroke=0, fill=1)


def draw_label(c: canvas.Canvas, text: str, y_top: float, width: float = 128) -> None:
    x = 18
    h = 26
    y = y_top - h
    c.setFillColor(colors.HexColor("#262626"))
    c.rect(x, y, width, h, stroke=0, fill=1)
    tail = c.beginPath()
    tail.moveTo(x, y)
    tail.lineTo(x, y - 8)
    tail.lineTo(x + 10, y)
    tail.close()
    c.drawPath(tail, stroke=0, fill=1)
    c.setFillColor(colors.white)
    c.setFont("HeitiMedium", 11)
    c.drawCentredString(x + width / 2, y + 7, text)


def draw_para(
    c: canvas.Canvas,
    text: str,
    x: float,
    y_top: float,
    width: float,
    style: ParagraphStyle,
) -> float:
    para = Paragraph(text, style)
    _, h = para.wrap(width, 1000)
    para.drawOn(c, x, y_top - h)
    return y_top - h


def draw_project(
    c: canvas.Canvas,
    styles: dict[str, ParagraphStyle],
    x: float,
    y_top: float,
    title: str,
    date: str | None,
    stack: str,
    intro: str,
    bullets: list[str],
) -> float:
    y = draw_para(c, title, x, y_top, CONTENT_W - 96, styles["project_title"])
    if date:
        draw_para(c, date, x + CONTENT_W - 110, y_top + 2, 110, styles["date"])
    c.setStrokeColor(GOLD)
    c.setLineWidth(1)
    c.line(x, y - 4, x + 160, y - 4)

    y -= 8
    y = draw_para(
        c,
        f"<font name='HeitiMedium'>技术栈：</font>{stack}",
        x,
        y,
        CONTENT_W,
        styles["body_small"],
    )
    y -= 2
    y = draw_para(
        c,
        f"<font name='HeitiMedium'>项目简介：</font>{intro}",
        x,
        y,
        CONTENT_W,
        styles["body"],
    )
    y -= 2
    y = draw_para(c, "核心工作与成果", x, y, CONTENT_W, styles["subhead"])
    y -= 2
    for item in bullets:
        y = draw_para(c, f"• {item}", x + 2, y, CONTENT_W - 2, styles["bullet"])
        y -= 2
    return y - 8


def draw_work_rows(c: canvas.Canvas, styles: dict[str, ParagraphStyle], x: float, y_top: float) -> float:
    left_w = 108
    mid_w = 170
    role_w = 118
    rows = [
        ("2026.01 - 2026.03", "重庆沈括科技有限公司", "前端开发实习生"),
    ]
    y = y_top
    for left, middle, right in rows:
        draw_para(c, left, x, y, left_w, styles["body"])
        draw_para(c, middle, x + 160, y, mid_w, styles["body"])
        draw_para(c, right, x + 360, y, role_w, styles["body"])
        y -= 21
    y -= 3
    details = [
        "• 负责 CRM 平台前端页面开发，完成业务表单、列表展示与交互页面落地。",
        "• 参与企业级 Agent 智能顾问能力开发，协助对话交互与业务接入实现。",
    ]
    for item in details:
        y = draw_para(c, item, x + 2, y, CONTENT_W - 2, styles["bullet"])
        y -= 2
    return y


def page_one(c: canvas.Canvas, styles: dict[str, ParagraphStyle]) -> None:
    draw_bg(c)

    c.setFillColor(BLACK)
    c.setFont("HeitiMedium", 31)
    c.drawString(CONTENT_X, 760, "高振淇")
    c.setFillColor(LIGHT_TEXT)
    c.setFont("HeitiLight", 19)
    c.drawString(CONTENT_X + 106, 762, "智能体应用开发工程师")

    y = 720
    y = draw_para(
        c,
        "电话：15320532995　　邮箱：3556045497@qq.com",
        CONTENT_X,
        y,
        CONTENT_W,
        styles["meta"],
    )
    y -= 3
    y = draw_para(
        c,
        "城市：重庆　　院校：重庆邮电大学·软件工程本科在读　　求职方向：Agent 应用开发",
        CONTENT_X,
        y,
        CONTENT_W,
        styles["meta"],
    )

    draw_label(c, "教育背景", 676)
    y = 636
    y = draw_para(
        c,
        "2023.09 - 至今　重庆邮电大学　软件工程（本科）　GPA 3.06",
        CONTENT_X,
        y,
        CONTENT_W,
        styles["body"],
    )
    y -= 2
    y = draw_para(
        c,
        "主修课程：数据结构、计算机网络、计算机系统、软件测试与维护、需求工程、Java 编程、C/C++、软件项目管理、技术文档编写。",
        CONTENT_X,
        y,
        CONTENT_W,
        styles["body_small"],
    )

    draw_label(c, "能力概述", y - 8)
    y -= 44
    ability_bullets = [
        "聚焦 Agent 应用开发，能够围绕“任务理解 - 路径规划 - 检索增强 - 工具执行 - 结果回传”设计完整智能体工作流。",
        "熟悉 Python、Flask、SQLite/libSQL、REST API 与 SSE 流式输出，可快速实现轻量 AI 应用后端与任务编排服务。",
        "具备多 Agent / Workflow 实践，理解 Master 调度、Plan-Executor、上下文裁剪、状态同步、人工确认与异常回退设计。",
        "熟悉知识库构建与 RAG 链路：网页清洗、正文切片、向量嵌入、混合检索、相关性过滤、重排与上下文注入。",
        "能够接入 Tavily、飞书 OpenAPI、Resend、GitHub Actions 等外部服务，搭建搜索、沉淀、推送一体化流程。",
        "关注缓存去重、安全护栏、任务可观测性与用户反馈体验，重视 AI 应用在真实场景中的稳定性与可维护性。",
    ]
    for item in ability_bullets:
        y = draw_para(c, f"• {item}", CONTENT_X + 2, y, CONTENT_W, styles["bullet"])
        y -= 3

    draw_label(c, "实践经历", y - 4)
    y -= 40
    y = draw_para(
        c,
        "2026.01 - 2026.03　重庆沈括科技有限公司　AI 应用开发实习生",
        CONTENT_X,
        y,
        CONTENT_W,
        styles["body"],
    )
    y -= 4
    y = draw_project(
        c,
        styles,
        CONTENT_X,
        y,
        "企业级智能顾问项目",
        None,
        "Python / Flask / 大模型 API / 企业知识库 / 工作流编排 / CRM 系统集成",
        "面向企业 CRM 场景搭建智能顾问能力，为销售和客服提供产品问答、客户沟通建议、线索分析与流程指引，减少人工查资料与重复回复成本。",
        [
            "参与智能顾问整体方案设计，梳理产品知识问答、客户异议处理、销售话术推荐、线索跟进建议等核心使用场景，并拆解为可执行工作流。",
            "负责知识整理与对话链路设计，将产品文档、常见问题、内部 SOP 等内容结构化处理后接入知识库，提升问答结果的准确性与可追溯性。",
            "设计多轮对话上下文管理与权限边界控制，避免模型直接输出不确定结论，在高风险问题上增加兜底提示与人工确认节点。",
            "推进智能顾问与 CRM 业务页面联动，实现客户信息辅助分析、跟进建议生成与常见咨询自动回复，缩短一线人员处理时长。",
            "结合真实业务反馈持续优化提示词、检索策略与结果呈现方式，帮助团队完成从 Demo 到可用内部工具的落地验证。",
        ],
    )


def page_two(c: canvas.Canvas, styles: dict[str, ParagraphStyle]) -> None:
    draw_bg(c)

    y = 764
    draw_label(c, "项目经历", y)
    y -= 38
    y = draw_project(
        c,
        styles,
        CONTENT_X,
        y,
        "Harness 个人 AI 知识助手",
        "2026.06 - 至今",
        "Python / Flask / JavaScript / SQLite / libSQL / SSE / Tavily / 飞书 OpenAPI / Resend",
        "围绕“读 - 存 - 写 - 推送”打造个人知识助手，支持多 Agent 对话、知识库沉淀、文章整理、飞书协作与邮件提醒。",
        [
            "设计 Master Agent + 专职 Agent / Tool 架构，将搜索、知识库、飞书整理、邮件推送、文章改写等能力拆分为独立节点，并通过任务规划按需组合。",
            "实现“先知识库检索，再联网补足，再根据用户明确指令执行入库或发飞书”的任务链路，减少误触发和顺序混乱带来的副作用。",
            "搭建知识库后端，支持文章入库、正文切片、嵌入存储、关键词模糊查文与向量混合检索，为专业问题提供可追溯上下文。",
            "完成任务状态展示、跨页面持续执行、异常中断提示与 Markdown 编辑联动等交互优化，提升 AI 应用可用性。",
            "结合飞书云文档、Resend 与 GitHub Actions 设计内容整理和定时推送方案，推动个人知识沉淀闭环。",
        ],
    )

    draw_label(c, "获奖经历", y - 4)
    y -= 40
    honors = [
        "• 英语四级，具备英文技术文档阅读与日常交流能力。",
        "• 第十六届蓝桥杯全国软件和信息技术专业人才大赛重庆赛区 C/C++ 程序设计 B 组三等奖。",
    ]
    for item in honors:
        y = draw_para(c, item, CONTENT_X + 2, y, CONTENT_W, styles["bullet"])
        y -= 4

    draw_label(c, "自我评价", y + 6)
    y -= 30
    summary = [
        "• 明确以 Agent 应用开发为长期方向，关注的不只是模型能否回答，更重视系统是否能稳定执行、可控调用工具并给出过程反馈。",
        "• 习惯把模糊需求拆成任务步骤、接口协议与状态流转，愿意围绕检索、工作流、知识沉淀和外部服务接入持续补强工程能力。",
        "• 做事认真，重视结果交付与代码可维护性，希望在真实业务场景中持续深耕 AI 应用工程化与智能体产品落地。",
    ]
    for item in summary:
        y = draw_para(c, item, CONTENT_X + 2, y, CONTENT_W, styles["bullet"])
        y -= 2


def build_pdf() -> Path:
    register_fonts()
    styles = make_styles()
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)

    c = canvas.Canvas(str(OUTPUT), pagesize=A4)
    c.setTitle("高振淇 - Agent 应用开发简历")

    page_one(c, styles)
    c.showPage()
    page_two(c, styles)
    c.save()
    return OUTPUT


if __name__ == "__main__":
    out = build_pdf()
    print(out)
