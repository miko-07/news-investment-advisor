"""
历史报告查看器 — Flask 可视化页面
用法: python3 viewer.py
访问: http://localhost:8899
"""
import re
from datetime import datetime
from pathlib import Path

from flask import Flask, render_template_string, send_file, abort

from config import OUTPUT_DIR

app = Flask(__name__)

OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# ── 静态页面模板 ──────────────────────────────────────────

INDEX_TEMPLATE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>每日投资参考 · 历史报告</title>
<style>
  :root {
    --bg: #f5f5f5;
    --card: #fff;
    --text: #333;
    --muted: #999;
    --accent: #c0392b;
    --accent2: #e74c3c;
    --border: #e8e8e8;
    --shadow: 0 2px 12px rgba(0,0,0,.06);
  }
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body {
    font-family: -apple-system, BlinkMacSystemFont, "PingFang SC", "Microsoft YaHei", sans-serif;
    background: var(--bg);
    color: var(--text);
    line-height: 1.6;
    min-height: 100vh;
  }
  .header {
    background: linear-gradient(135deg, #1a1a2e 0%, #16213e 50%, #c0392b 100%);
    color: #fff;
    padding: 32px 24px 28px;
    text-align: center;
  }
  .header h1 { font-size: 26px; font-weight: 700; letter-spacing: 1px; }
  .header p { margin-top: 6px; opacity: .7; font-size: 14px; }
  .container { max-width: 800px; margin: 0 auto; padding: 20px 16px 40px; }
  .report-card {
    background: var(--card);
    border-radius: 10px;
    padding: 20px 24px;
    margin-bottom: 14px;
    box-shadow: var(--shadow);
    border: 1px solid var(--border);
    cursor: pointer;
    transition: transform .15s, box-shadow .15s;
    text-decoration: none;
    display: block;
    color: inherit;
  }
  .report-card:hover {
    transform: translateY(-2px);
    box-shadow: 0 6px 20px rgba(0,0,0,.10);
  }
  .report-date {
    font-size: 13px;
    color: var(--accent);
    font-weight: 600;
    margin-bottom: 4px;
  }
  .report-time {
    font-size: 12px;
    color: #999;
    margin-left: 8px;
    font-weight: 400;
  }
  .report-title {
    font-size: 18px;
    font-weight: 700;
    color: #2c3e50;
    margin-bottom: 6px;
  }
  .report-sentiment {
    font-size: 14px;
    color: #555;
    display: -webkit-box;
    -webkit-line-clamp: 2;
    -webkit-box-orient: vertical;
    overflow: hidden;
  }
  .tag {
    display: inline-block;
    padding: 2px 10px;
    border-radius: 12px;
    font-size: 12px;
    font-weight: 600;
    margin-right: 6px;
    vertical-align: middle;
  }
  .tag-bullish { background: #ffe0e0; color: #c0392b; }
  .tag-bearish { background: #e0f0e0; color: #27ae60; }
  .tag-neutral { background: #fff3e0; color: #e67e22; }
  .tag-test {
    display: inline-block;
    padding: 2px 10px;
    border-radius: 12px;
    font-size: 11px;
    font-weight: 600;
    background: #f0f0f0;
    color: #999;
    margin-left: 6px;
    vertical-align: middle;
  }
  .tag-review {
    display: inline-block;
    padding: 2px 10px;
    border-radius: 12px;
    font-size: 11px;
    font-weight: 600;
    background: #e3f2fd;
    color: #1565c0;
    margin-left: 6px;
    vertical-align: middle;
  }
  .tag-auto {
    display: inline-block;
    padding: 2px 10px;
    border-radius: 12px;
    font-size: 11px;
    font-weight: 600;
    background: #e8f5e9;
    color: #388e3c;
    margin-left: 6px;
    vertical-align: middle;
  }
  .empty {
    text-align: center;
    padding: 80px 20px;
    color: #999;
  }
  .empty .icon { font-size: 64px; margin-bottom: 16px; }
  .footer {
    text-align: center;
    padding: 24px;
    color: #bbb;
    font-size: 12px;
  }
  .refresh {
    text-align: right;
    padding: 0 0 12px;
  }
  .refresh a {
    color: var(--accent);
    text-decoration: none;
    font-size: 13px;
  }
</style>
</head>
<body>
<div class="header">
  <h1>📊 每日投资参考</h1>
  <p>AI 驱动的财经新闻分析 · 历史报告归档</p>
</div>
<div class="container">
  <div class="refresh">
    <span style="color:#999;font-size:12px;">共 {{ reports|length }} 份报告</span>
  </div>

  {% if reports %}
    {% for r in reports %}
    <a class="report-card" href="/report/{{ r.filename }}">
      <div class="report-date">
        {{ r.date_display }}<span class="report-time">{{ r.time_display }}</span>
        {% if r.is_review %}<span class="tag tag-review">复盘</span>{% endif %}
        {% if r.is_test %}<span class="tag tag-test">测试</span>{% else %}<span class="tag tag-auto">定时</span>{% endif %}
      </div>
      <div class="report-title">
        {% if r.sentiment_tag == 'bullish' %}<span class="tag tag-bullish">偏多</span>{% endif %}
        {% if r.sentiment_tag == 'bearish' %}<span class="tag tag-bearish">偏空</span>{% endif %}
        {% if r.sentiment_tag == 'neutral' %}<span class="tag tag-neutral">震荡</span>{% endif %}
        {{ r.title }}
      </div>
      <div class="report-sentiment">{{ r.sentiment }}</div>
    </a>
    {% endfor %}
  {% else %}
    <div class="empty">
      <div class="icon">📭</div>
      <p>还没有生成任何报告</p>
      <p style="margin-top:8px;">运行 python3 main.py 来生成第一份报告</p>
    </div>
  {% endif %}
</div>
<div class="footer">
  <p>数据由 DeepSeek AI 自动生成 · 仅供参考，不构成投资建议</p>
</div>
</body>
</html>"""

DETAIL_TEMPLATE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{{ title }}</title>
<style>
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body {
    font-family: -apple-system, BlinkMacSystemFont, "PingFang SC", "Microsoft YaHei", sans-serif;
    background: #f5f5f5;
  }
  .topbar {
    background: #fff;
    border-bottom: 1px solid #e8e8e8;
    padding: 14px 20px;
    display: flex;
    align-items: center;
    gap: 16px;
    position: sticky;
    top: 0;
    z-index: 10;
  }
  .topbar a {
    color: #c0392b;
    text-decoration: none;
    font-size: 14px;
    font-weight: 600;
  }
  .topbar span { color: #999; font-size: 13px; }
  .content {
    max-width: 700px;
    margin: 20px auto;
    background: #fff;
    border-radius: 8px;
    box-shadow: 0 2px 12px rgba(0,0,0,.06);
    padding: 32px 28px;
  }
  /* 复用原 WeChat 样式 */
  .content h1 { font-size: 22px; text-align: center; color: #c0392b; border-bottom: 2px solid #c0392b; padding-bottom: 12px; margin-bottom: 24px; }
  .content h2 { font-size: 18px; color: #2c3e50; border-left: 4px solid #c0392b; padding-left: 10px; margin-top: 28px; margin-bottom: 14px; }
  .content h3 { font-size: 16px; color: #444; margin-top: 20px; }
  .content p { margin: 8px 0; line-height: 1.8; font-size: 15px; }
  .content ul, .content ol { padding-left: 20px; }
  .content li { margin: 4px 0; line-height: 1.8; font-size: 15px; }
  .content strong { color: #c0392b; }
  .content blockquote { background: #fdf2f2; border-left: 4px solid #e74c3c; padding: 10px 14px; margin: 12px 0; color: #666; font-size: 14px; }
  .content a { color: #2980b9; text-decoration: none; }
  .content .divider, .content p[class="divider"] { text-align: center; color: #ccc; margin: 20px 0; font-size: 12px; letter-spacing: 4px; }
  .content .disclaimer { background: #f8f9fa; border-radius: 6px; padding: 12px 16px; font-size: 12px; color: #999; margin-top: 24px; }
  .content .footer { text-align: center; color: #bbb; font-size: 12px; margin-top: 20px; }
  .nav-bottom {
    text-align: center;
    padding: 20px;
  }
  .nav-bottom a {
    display: inline-block;
    padding: 10px 28px;
    background: #c0392b;
    color: #fff;
    text-decoration: none;
    border-radius: 6px;
    font-size: 14px;
  }
</style>
</head>
<body>
<div class="topbar">
  <a href="/">← 返回列表</a>
  <span>{{ date_display }}</span>
</div>
<div class="content">
  {{ content|safe }}
</div>
<div class="nav-bottom">
  <a href="/">← 返回报告列表</a>
</div>
</body>
</html>"""


# ── 报告元数据解析 ────────────────────────────────────────

def _parse_report_meta(md_path: Path) -> dict:
    """从 Markdown 文件中提取标题、市场情绪等预览信息"""
    text = md_path.read_text(encoding="utf-8")

    # 提取 H1 标题
    title_match = re.search(r"^# (.+)$", text, re.MULTILINE)
    title = title_match.group(1).strip() if title_match else "每日投资参考"

    # 提取市场情绪速览（## 一、... 后的第一段）
    sentiment = ""
    sentiment_tag = ""
    section_match = re.search(r"## 一、(?:市场情绪速览|今日市场复盘)\s*\n+(.+?)(?=\n##|\Z)", text, re.DOTALL)
    if section_match:
        raw = section_match.group(1).strip()
        # 去掉 ** 等标记
        raw = re.sub(r"\*\*", "", raw)
        sentiment = raw[:200]

        # 判断多空
        if any(w in raw for w in ["偏多", "看多", "乐观", "bullish"]):
            sentiment_tag = "bullish"
        elif any(w in raw for w in ["偏空", "看空", "悲观", "bearish"]):
            sentiment_tag = "bearish"
        else:
            sentiment_tag = "neutral"

    return {
        "title": title,
        "sentiment": sentiment,
        "sentiment_tag": sentiment_tag,
    }


def _list_reports() -> list[dict]:
    """列出所有历史报告，按日期倒序"""
    reports = []
    # 同时扫描正式报告和测试报告
    for f in sorted(OUTPUT_DIR.glob("*.md"), reverse=True):
        name = f.stem
        if name.startswith("."):
            continue

        # 提取日期: analysis_20260501, test_analysis_20260501, review_20260503
        is_test = name.startswith("test_")
        is_review = name.startswith("review_")
        date_key = (name
                    .replace("test_analysis_", "")
                    .replace("analysis_", "")
                    .replace("review_", ""))
        if not date_key:
            continue
        try:
            dt = datetime.strptime(date_key, "%Y%m%d")
            date_display = dt.strftime("%Y年%m月%d日")
        except ValueError:
            date_display = date_key

        # 文件修改时间作为生成时间
        mtime = f.stat().st_mtime
        gen_dt = datetime.fromtimestamp(mtime)
        time_display = gen_dt.strftime("%H:%M:%S")

        meta = _parse_report_meta(f)
        html_file = f.with_suffix(".html")

        reports.append({
            "filename": f.stem,
            "date_key": date_key,
            "date_display": date_display,
            "time_display": time_display,
            "title": meta["title"],
            "sentiment": meta["sentiment"],
            "sentiment_tag": meta["sentiment_tag"],
            "has_html": html_file.exists(),
            "is_test": is_test,
            "is_review": is_review,
        })

    return reports


# ── Flask 路由 ────────────────────────────────────────────

@app.route("/")
def index():
    reports = _list_reports()
    return render_template_string(INDEX_TEMPLATE, reports=reports)


@app.route("/report/<filename>")
def report(filename: str):
    # 安全检查：确保访问路径在 OUTPUT_DIR 内
    target = (OUTPUT_DIR / f"{filename}.md").resolve()
    if not str(target).startswith(str(OUTPUT_DIR.resolve())):
        abort(404)

    md_path = OUTPUT_DIR / f"{filename}.md"
    html_path = OUTPUT_DIR / f"{filename}.html"

    if not md_path.exists():
        abort(404)

    # 优先使用已生成的 HTML，提取 body 内容
    if html_path.exists():
        html = html_path.read_text(encoding="utf-8")
        # 提取 <body> 内容
        body_match = re.search(r"<body>(.*?)</body>", html, re.DOTALL)
        content = body_match.group(1).strip() if body_match else html
    else:
        # 降级：显示纯文本
        md_text = md_path.read_text(encoding="utf-8")
        content = f"<pre>{md_text}</pre>"

    # 提取日期和标题
    meta = _parse_report_meta(md_path)
    try:
        date_key = filename.replace("analysis_", "").replace("test_analysis_", "").replace("review_", "")
        dt = datetime.strptime(date_key, "%Y%m%d")
        date_display = dt.strftime("%Y年%m月%d日")
    except ValueError:
        date_display = filename

    return render_template_string(
        DETAIL_TEMPLATE,
        title=meta["title"],
        date_display=date_display,
        content=content,
    )


def main():
    import sys
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8899
    print(f"\n  📊 投资参考查看器 → http://localhost:{port}\n")
    app.run(host="0.0.0.0", port=port, debug=True)


if __name__ == "__main__":
    main()
