"""
格式化模块
将 AI 分析结果（Markdown）转换为微信公众号兼容的 HTML 格式
"""
import re
from datetime import datetime, timezone, timedelta

CST = timezone(timedelta(hours=8))

# ── CSS 样式（内联，适配邮件和微信编辑器）────────────────
BASE_STYLE = """
<style>
  body { max-width: 680px; margin: 0 auto; padding: 20px; font-family: -apple-system, BlinkMacSystemFont, "PingFang SC", "Microsoft YaHei", sans-serif; color: #333; line-height: 1.8; font-size: 15px; }
  h1 { font-size: 22px; text-align: center; color: #c0392b; border-bottom: 2px solid #c0392b; padding-bottom: 12px; margin-bottom: 24px; }
  h2 { font-size: 18px; color: #2c3e50; border-left: 4px solid #c0392b; padding-left: 10px; margin-top: 28px; margin-bottom: 14px; }
  h3 { font-size: 16px; color: #444; margin-top: 20px; }
  p { margin: 8px 0; }
  ul, ol { padding-left: 20px; }
  li { margin: 4px 0; }
  strong { color: #c0392b; }
  code { background: #f4f4f4; padding: 2px 6px; border-radius: 3px; font-family: "SF Mono", "Menlo", monospace; font-size: 13px; }
  pre { background: #f8f8f8; border: 1px solid #e8e8e8; border-radius: 4px; padding: 12px 16px; overflow-x: auto; font-size: 13px; line-height: 1.5; }
  pre code { background: none; padding: 0; border-radius: 0; font-size: inherit; }
  blockquote { background: #fdf2f2; border-left: 4px solid #e74c3c; padding: 10px 14px; margin: 12px 0; color: #666; font-size: 14px; }
  .highlight { background: linear-gradient(180deg, transparent 60%, #ffeaa7 60%); font-weight: bold; }
  .tag-long { display: inline-block; background: #e74c3c; color: #fff; padding: 1px 8px; border-radius: 3px; font-size: 12px; margin-right: 4px; }
  .tag-short { display: inline-block; background: #27ae60; color: #fff; padding: 1px 8px; border-radius: 3px; font-size: 12px; margin-right: 4px; }
  .tag-warn { display: inline-block; background: #f39c12; color: #fff; padding: 1px 8px; border-radius: 3px; font-size: 12px; margin-right: 4px; }
  .divider { text-align: center; color: #ccc; margin: 20px 0; font-size: 12px; letter-spacing: 4px; }
  .disclaimer { background: #f8f9fa; border-radius: 6px; padding: 12px 16px; font-size: 12px; color: #999; margin-top: 24px; }
  .footer { text-align: center; color: #bbb; font-size: 12px; margin-top: 20px; }
  a { color: #2980b9; text-decoration: none; }
  table { width: 100%; border-collapse: collapse; margin: 14px 0; font-size: 14px; }
  th { background: #f8f9fa; padding: 10px 12px; border: 1px solid #ddd; text-align: left; font-weight: 700; color: #2c3e50; }
  td { padding: 10px 12px; border: 1px solid #e8e8e8; text-align: left; vertical-align: top; }
  @media screen and (max-width: 480px) {
    body { padding: 12px; font-size: 14px; }
    h1 { font-size: 19px; }
    h2 { font-size: 16px; }
    h3 { font-size: 15px; }
    table { font-size: 12px; }
    th, td { padding: 6px 8px; }
  }
</style>
"""


def markdown_to_wechat_html(md_text: str, date_str: str) -> str:
    """
    将 DeepSeek 输出的 Markdown 转换为微信公众号 HTML
    """
    # ── 预处理：清理 DeepSeek 输出的首尾空白 ──
    md_text = md_text.strip()

    # ── 处理 Markdown 元素 ──
    html_body = _convert_markdown(md_text)

    # ── 包装为完整 HTML ──
    full_html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
{BASE_STYLE}
</head>
<body>
{html_body}

<div class="divider">◆ ◆ ◆</div>
<div class="footer">
  <p>由 DeepSeek 自动生成 · {date_str}</p>
  <p>每日早 7:00 发送 · 仅供参考，不构成投资建议</p>
</div>
</body>
</html>"""

    return full_html


def _convert_markdown(text: str) -> str:
    """Markdown → HTML 核心转换"""
    lines = text.split("\n")
    out = []
    in_list = False
    list_type = None  # "ul" or "ol"

    def close_list():
        nonlocal in_list, list_type
        if in_list:
            out.append(f"</{list_type}>")
            in_list = False
            list_type = None

    i = 0
    while i < len(lines):
        line = lines[i]

        # ── 空行 ──
        if not line.strip():
            close_list()
            i += 1
            continue

        # ── 代码块（``` 围栏）──
        if line.strip().startswith("```"):
            close_list()
            lang = line.strip()[3:].strip()
            code_lines = []
            i += 1
            while i < len(lines) and not lines[i].strip().startswith("```"):
                code_lines.append(lines[i])
                i += 1
            i += 1  # 跳过结束围栏
            code_html = _escape_html("\n".join(code_lines))
            lang_attr = f' class="language-{lang}"' if lang else ""
            out.append(f'<pre><code{lang_attr}>{code_html}</code></pre>')
            continue

        # ── 表格（连续 | 开头的行）──
        if line.strip().startswith("|") and line.strip().endswith("|"):
            close_list()
            table_rows = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                table_rows.append(lines[i].strip())
                i += 1
            out.append(_convert_table(table_rows))
            continue

        # ── 水平线 ──
        if re.match(r"^[-*_]{3,}\s*$", line.strip()):
            close_list()
            out.append('<p class="divider">◆ ◆ ◆</p>')
            i += 1
            continue

        # ── H1 (# 开头) ──
        m = re.match(r"^# (.+)", line)
        if m:
            close_list()
            out.append(f"<h1>{_inline(m.group(1))}</h1>")
            i += 1
            continue

        # ── H2 (## 开头) ──
        m = re.match(r"^## (.+)", line)
        if m:
            close_list()
            out.append(f"<h2>{_inline(m.group(1))}</h2>")
            i += 1
            continue

        # ── H3 (### 开头) ──
        m = re.match(r"^### (.+)", line)
        if m:
            close_list()
            out.append(f"<h3>{_inline(m.group(1))}</h3>")
            i += 1
            continue

        # ── 引用 (> 开头) ──
        if line.startswith("> "):
            close_list()
            out.append(f"<blockquote>{_inline(line[2:])}</blockquote>")
            i += 1
            continue

        # ── 无序列表 ──
        m = re.match(r"^[-*]\s+(.+)", line)
        if m:
            if not in_list or list_type != "ul":
                close_list()
                out.append("<ul>")
                in_list = True
                list_type = "ul"
            content = _inline(m.group(1))
            i += 1
            # 处理多行列表项（缩进续行）
            while i < len(lines) and re.match(r"^\s{2,}\S", lines[i]):
                content += "<br>" + _inline(lines[i].strip())
                i += 1
            out.append(f"<li>{content}</li>")
            continue

        # ── 有序列表 ──
        m = re.match(r"^\d+[.)]\s+(.+)", line)
        if m:
            if not in_list or list_type != "ol":
                close_list()
                out.append("<ol>")
                in_list = True
                list_type = "ol"
            content = _inline(m.group(1))
            i += 1
            # 处理多行列表项（缩进续行）
            while i < len(lines) and re.match(r"^\s{2,}\S", lines[i]):
                content += "<br>" + _inline(lines[i].strip())
                i += 1
            out.append(f"<li>{content}</li>")
            continue

        # ── 普通段落 ──
        close_list()
        out.append(f"<p>{_inline(line)}</p>")
        i += 1

    close_list()
    return "\n".join(out)


def _convert_table(rows: list[str]) -> str:
    """将 Markdown 表格行列表转换为 HTML <table>"""
    html = ['<table style="width:100%;border-collapse:collapse;margin:14px 0;font-size:14px;">']
    for idx, row in enumerate(rows):
        cells = [c.strip() for c in row.strip().strip("|").split("|")]
        tag = "th" if idx == 0 else "td"
        cell_style = (
            'style="padding:10px 12px;border:1px solid #ddd;text-align:left;'
            'background:#f8f9fa;font-weight:700;color:#2c3e50;white-space:nowrap;"'
            if idx == 0 else
            'style="padding:10px 12px;border:1px solid #e8e8e8;text-align:left;'
            'vertical-align:top;"'
        )
        html.append("<tr>")
        for cell in cells:
            # 跳过纯分隔符行（如 -----）
            if re.match(r"^[-: ]+$", cell):
                html.append("</tr>")
                break
            html.append(f"<{tag} {cell_style}>{_inline(cell)}</{tag}>")
        html.append("</tr>")
    html.append("</table>")
    return "\n".join(html)


def _inline(text: str) -> str:
    """处理行内元素：粗体、斜体、高亮、标签、链接、代码、转义"""
    # 行内代码 `code`（优先处理，避免与粗体/斜体冲突）
    text = re.sub(r"`([^`]+)`", r"<code>\1</code>", text)
    # 转义字符
    text = re.sub(r"\\([*#_`\[\]()\\])", r"\1", text)
    # 链接 [text](url)
    text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<a href="\2" target="_blank">\1</a>', text)
    # 粗体 **text**
    text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
    # 斜体 *text*（避免干扰已处理的标签）
    text = re.sub(r"(?<!\*)\*([^*\n]+?)\*(?!\*)", r"<em>\1</em>", text)
    # 高亮 ==text==
    text = re.sub(r"==(.+?)==", r'<span class="highlight">\1</span>', text)

    return text


def _escape_html(text: str) -> str:
    """转义 HTML 特殊字符（用于代码块内容）"""
    text = text.replace("&", "&amp;")
    text = text.replace("<", "&lt;")
    text = text.replace(">", "&gt;")
    return text


if __name__ == "__main__":
    sample = """# 📊 每日投资参考 — 2026-05-01

## 一、市场情绪速览
今日市场呈**偏多**格局。美联储鸽派信号提振全球风险偏好，A股节前最后一个交易日缩量震荡但北向资金持续流入。

## 二、关键新闻解读

**美联储维持利率不变，暗示年内降息**
→ 影响分析：利好全球流动性和成长股估值修复
→ 操作建议：**关注**科技成长板块反弹机会

## 三、风险预警
- 五一假期期间海外市场波动风险
- 美联储官员讲话可能修正市场预期
- 日元持续贬值引发亚洲货币竞争性贬值担忧

## 五、今日策略
> 核心策略：**持股过节，仓位控制在6成**。

⚠️ 以上内容由 AI 基于公开新闻自动生成，仅供参考。
"""
    html = markdown_to_wechat_html(sample, "2026年5月1日")
    print(html)
