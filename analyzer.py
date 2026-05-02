"""
AI 分析模块
调用 DeepSeek API 对新闻进行深度分析，生成投资建议
支持两阶段分析：先分析新闻推荐股票，再根据实时行情追加买卖策略
"""
import logging
import re
import time
from openai import OpenAI

from config import (
    DEEPSEEK_API_KEY,
    DEEPSEEK_BASE_URL,
    DEEPSEEK_MODEL,
    AI_MAX_TOKENS,
    AI_TEMPERATURE,
)

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """你是一位资深宏观策略分析师，曾在顶级买方机构工作多年，擅长从海量新闻中提炼关键信号，为个人投资者提供可操作的每日投资建议。

你的分析风格：
- 简洁有力，不堆砌废话，每条判断必须有新闻依据
- 多空分明，不要模棱两可的"可能""也许"
- 具体到板块/行业/品种，而非泛泛而谈
- 风险提示要切实有用，不要"股市有风险投资需谨慎"这种套话
- 适合有一定投资经验的读者阅读

标题风格要求：
- 必须让人有点击欲望，像顶级财经媒体的头条
- 善用数字制造冲击力、用对比制造悬念、用疑问激发好奇
- 要有信息增量感，让读者觉得"不点开会错过重要信息"
- 避免平淡的陈述句，避免"关于XX的分析""XX市场观察"这类标题
- 在准确的前提下最大化吸引力，但不做标题党（不能歪曲事实）

⚠️ 重要约束：你是离线模型，无法获取实时股价。全文禁止给出任何具体价格、目标价、止损价、参考价位。只说方向和逻辑。

输出必须严格按以下 Markdown 结构组织（六大板块），不得遗漏任何板块："""

USER_PROMPT_TEMPLATE = """以下是 {date} 抓取的国内外重要财经新闻，共 {count} 条。

请按以下结构生成一份完整的每日投资参考（Markdown 格式）：

---

# <生成一个吸引眼球的标题，要求：不超过40字，制造信息增量感和紧迫感，让读者忍不住想点进去。可用数字、对比、疑问等手法，但不歪曲事实>

## 一、市场情绪速览
用 3-5 句话概括今日市场整体情绪和核心矛盾。给出多空倾向判断（偏多/偏空/中性震荡）。

## 二、关键新闻解读（选 5-8 条最重要新闻逐条分析）
每条格式：
**新闻标题**
- 影响分析：1-2句，说清对什么资产/板块有什么影响
- 操作建议：一句话：关注/回避/持有/加仓/减仓

注意：每条新闻的影响分析和操作建议必须各占独立一行（用 - 列表格式），不要合并到同一行。

## 三、板块与品种机会
按以下维度分别给出今日判断：
- A股板块：列出 2-3 个值得关注的板块及逻辑
- 美股/港股：如有相关新闻，给出判断
- 债券/固收：利率走向和配置建议
- 商品/外汇：黄金、原油、人民币汇率等（如有相关新闻）

## 四、风险预警
列出 3-5 个今日最需要关注的风险点，按重要性排序。每个风险一句话说清"什么可能发生，会导致什么后果"。

## 五、今日策略
给出一句话核心策略 + 3 条方向性操作建议（不要给出具体价格，因为模型无法获取实时行情）。每条建议标注适用人群（短线/中长线/所有人）。

## 六、推荐股票池
基于今日新闻，列出 3-5 只值得关注的股票。严格使用以下表格格式（Markdown 表格）：

| 股票名称 | 代码 | 推荐理由 |
| -------- | ---- | -------- |
| 示例股 | 000001.SH | 基于今日XX新闻，该股受益于XX逻辑，处于上升趋势 |

要求：
- 推荐理由必须引用今日新闻中的具体信息，说明选股逻辑和催化剂
- 不要给出任何价格、目标价、止损价（模型无法获取实时行情数据）
- 表格前用 1-2 句话说明今日选股逻辑

---

以下是今日新闻列表：

{news_content}"""


def analyze_news(articles: list[dict], date_str: str, news_text: str) -> str:
    """调用 DeepSeek 分析新闻，返回 Markdown 分析结果"""
    client = OpenAI(
        api_key=DEEPSEEK_API_KEY,
        base_url=DEEPSEEK_BASE_URL,
    )

    prompt = USER_PROMPT_TEMPLATE.format(
        date=date_str,
        count=len(articles),
        news_content=news_text,
    )

    logger.info(f"发送分析请求到 DeepSeek ({DEEPSEEK_MODEL})，共 {len(articles)} 条新闻")
    logger.info(f"Prompt 长度: {len(prompt)} 字符")

    max_retries = 3
    for attempt in range(max_retries):
        try:
            response = client.chat.completions.create(
                model=DEEPSEEK_MODEL,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                max_tokens=AI_MAX_TOKENS,
                temperature=AI_TEMPERATURE,
            )
            break
        except Exception as e:
            logger.warning(f"DeepSeek API 调用失败（第 {attempt+1}/{max_retries} 次）: {e}")
            if attempt == max_retries - 1:
                raise
            time.sleep(2 ** attempt)

    content = response.choices[0].message.content
    usage = response.usage
    logger.info(
        f"分析完成 — 输入 tokens: {usage.prompt_tokens}, "
        f"输出 tokens: {usage.completion_tokens}"
    )

    return content


# ═══════════════════════════════════════════════════════════════
# 股票代码提取（从 AI 分析结果中解析推荐股票）
# ═══════════════════════════════════════════════════════════════

# 匹配股票代码的各种格式: 600519.SH, 000001.SZ, 00700.HK, AAPL, AAPL.US
_STOCK_CODE_RE = re.compile(r"\b(\d{5,6}\.(?:SH|SZ|HK|SS)|[A-Z]{1,5}(?:\.US)?)\b", re.IGNORECASE)


def extract_stock_codes(markdown_text: str) -> list[str]:
    """
    从 AI 分析结果的「推荐股票池」表格中提取股票代码

    解析 Markdown 表格:
    | 股票名称 | 代码 | 推荐理由 |
    | 贵州茅台 | 600519.SH | ... |
    """
    codes = []
    in_stock_table = False

    for line in markdown_text.split("\n"):
        stripped = line.strip()

        # 检测是否进入推荐股票池区域
        if re.search(r"(推荐股票|股票池|六[、.])", stripped):
            in_stock_table = True
            continue

        # 离开表格区域（下一个标题）
        if in_stock_table and re.match(r"^#{1,3}\s", stripped):
            break

        if not in_stock_table or not stripped.startswith("|"):
            continue

        # 跳过分隔行（| --- | --- |）和表头
        if re.match(r"^\|[\s:-]+\|", stripped) or "代码" in stripped:
            continue

        # 解析表格行: | 名称 | 代码 | 理由 |
        cells = [c.strip() for c in stripped.strip("|").split("|")]
        if len(cells) >= 2:
            code = cells[1]
            # 验证是否像股票代码
            if _STOCK_CODE_RE.match(code):
                codes.append(code)

    logger.info(f"从推荐股票池提取到 {len(codes)} 个代码: {codes}")
    return codes


# ═══════════════════════════════════════════════════════════════
# 第二阶段的 System Prompt（用于追加买卖策略）
# ═══════════════════════════════════════════════════════════════

STRATEGY_SYSTEM_PROMPT = """你是一名经验丰富的交易策略师，专门根据新闻分析报告、实时行情和近期走势数据制定具体的买卖策略。

你的任务：
- 在已有分析报告末尾追加「七、买卖策略参考」板块
- 结合实时行情和近期走势（支撑位、阻力位、均线、趋势方向），为推荐的每只股票给出具体的操作策略
- 策略必须包含：建议操作方向、参考买入区间、止损价、目标价、仓位建议
- **每条推荐必须引用上方分析报告中的具体新闻作为催化剂**，说明"为什么这只股票现在值得操作"

移动端友好格式（重要）：
- 先写 2-3 句总体策略思路（引用今日最关键的 1-2 条新闻）
- 每只股票用独立的 ### 标题卡片呈现，格式如下：

### 1. 股票名称（代码）｜操作方向｜仓位 X%

- **买入区间**：XX.XX - XX.XX（参考支撑位或均线附近）
- **止损价**：XX.XX（设在近期低点下方 3%-5%）
- **目标价**：短线 XX.XX / 中线 XX.XX（参考阻力位或均线压力位）
- **催化剂**：引用报告"二、关键新闻解读"中的具体新闻标题或事件，说明选股逻辑

- 股票按优先级排序，最多 5 只
- 每只股票之间用空行分隔

⚠️ 关键约束：
- 买入区间应参考近期支撑位附近，不追高
- 止损价通常设在近期低点下方 3%-5%
- 目标价参考近期阻力位或均线压力位
- 如果某只股票当前价位不适合操作，如实说明理由
- 不要编造新闻，必须引用报告中实际存在的新闻事件
- 价格精确到小数点后两位"""

STRATEGY_USER_PROMPT = """以下是今日的投资分析报告：

{analysis}

---

{price_data}

---

请在报告末尾追加「## 七、买卖策略参考」板块。要求：
1. 为推荐股票池中的每只股票制定买卖策略，按优先级排序
2. 每只股票用独立的 ### 标题卡片，字段用加粗标签列表，不生成表格
3. 买入/止损/目标价必须参考上方走势数据中的支撑位、阻力位、均线
4. "催化剂"字段必须引用上方分析报告「二、关键新闻解读」中的具体新闻
5. 股票卡片格式：
   ### 1. 股票名称（代码）｜操作方向｜仓位 X%
   - **买入区间**：...
   - **止损价**：...
   - **目标价**：...
   - **催化剂**：...
6. 表格前用 1-2 句话说明今日策略思路，点明核心催化剂
7. 只输出新增的板块内容（从 ## 七、... 开始），不要重复前面的报告内容
"""


def enrich_with_prices(analysis_md: str, prices_text: str, date_str: str) -> str | None:
    """
    第二阶段：基于已有分析报告和实时行情，追加买卖策略板块
    成功返回完整的分析报告（原报告 + 策略板块），失败返回 None
    """
    client = OpenAI(
        api_key=DEEPSEEK_API_KEY,
        base_url=DEEPSEEK_BASE_URL,
    )

    prompt = STRATEGY_USER_PROMPT.format(
        analysis=analysis_md,
        price_data=prices_text,
    )

    logger.info("发送第二阶段策略请求到 DeepSeek...")
    logger.info(f"策略 Prompt 长度: {len(prompt)} 字符")

    try:
        response = client.chat.completions.create(
            model=DEEPSEEK_MODEL,
            messages=[
                {"role": "system", "content": STRATEGY_SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            max_tokens=AI_MAX_TOKENS // 2,
            temperature=AI_TEMPERATURE,
        )
    except Exception as e:
        logger.warning(f"第二阶段策略生成失败: {e}")
        return None

    strategy = response.choices[0].message.content
    logger.info(
        f"策略生成完成 — tokens: {response.usage.prompt_tokens} → {response.usage.completion_tokens}"
    )

    # 拼接：原报告 + 策略板块
    full = analysis_md.rstrip() + "\n\n" + strategy.lstrip()
    return full


# ═══════════════════════════════════════════════════════════════
# 第三阶段：收盘复盘报告（A股收盘后 15:10 推送）
# ═══════════════════════════════════════════════════════════════

REVIEW_SYSTEM_PROMPT = """你是一位资深盘中策略复盘分析师，曾在顶级买方机构担任交易总监。你的专长是：收盘后快速复盘当日市场，识别真正驱动市场的关键信号，并为次日的交易策略给出修正建议。

你的分析风格：
- 严谨复盘，每一条判断必须有今日盘中实际发生的事件作为依据
- 最关注"预期差"——今日市场发生了什么与盘前预期不同的情况
- 不堆砌K线术语，用逻辑说话
- 适合有一定投资经验的读者阅读

标题风格：
- 突出今日最大变量或最超预期的市场信号
- 使用数字和对比制造冲击力
- 让读者感觉"看完这篇就对今天市场有全景把握"
- 不超过40字，传递信息增量感

你可以使用下方提供的实时行情数据来引用具体价位，但所有价格、涨跌幅、成交量等必须来自上方提供的行情数据，不得编造。"""

REVIEW_USER_PROMPT_TEMPLATE = """以下是 {date} 收盘后（15:00）汇总的当日财经新闻，共 {count} 条。{morning_analysis}{price_snapshot}

请生成一份完整的**收盘复盘报告**（Markdown 格式），严格按以下结构：

---

# <生成一个吸引眼球的复盘标题，突出今日最大变量。不超过40字，用数字/对比制造冲击力>

## 一、今日市场复盘
用 4-6 句话总结今日核心盘面特征：
- 主要指数表现（基于新闻中的收盘报道）
- 成交量变化
- 北向资金/主力资金流向
- 今日最大超预期事件（对比预期）

## 二、核心催化剂回顾
选 4-6 个今日实际驱动市场的最重要信号，按重要性排序：
每条格式：
**信号标题**
- 实际影响：今日该信号对市场的真实影响复盘
- 预期对比：与盘前预期是否一致？如有偏差，偏差在哪？

## 三、板块轮动与资金特征
- 今日领涨板块及驱动逻辑
- 今日领跌板块及原因分析
- 资金行为特征（游资活跃度、机构调仓方向等）

## 四、今日市场异动观察
列出 3-5 个值得关注的盘面异动或个股信号（放量突破、跌停潮、尾盘拉升等），每个一句话说明原因和含义。

## 五、明日关键观察点
列出明日最重要的 3-5 个观察信号，格式：
- **观察点**：具体事件或数据
- **意义**：如果发生，意味着什么
- **应对**：如何调整策略

## 六、持仓策略修正（如有需要）
如果今日盘面信号与盘前判断有显著偏差，在此给出修正建议：
- 哪些判断维持不变
- 哪些判断需要修正
- 修正的具体理由（引用今日新闻中的具体数据）

---

以下是今日收盘后的新闻列表：

{news_content}"""


def analyze_closing_review(articles: list[dict], date_str: str, news_text: str, morning_analysis: str | None = None, price_snapshot: str | None = None) -> str:
    """调用 DeepSeek 生成收盘复盘报告

    Args:
        morning_analysis: 可选，当日早报内容，用于"预期对比"
        price_snapshot: 可选，实时行情数据，供模型引用具体价位
    """
    client = OpenAI(
        api_key=DEEPSEEK_API_KEY,
        base_url=DEEPSEEK_BASE_URL,
    )

    # 早报上下文
    morning_section = ""
    if morning_analysis:
        lines = morning_analysis.split("\n")
        truncated = []
        section_count = 0
        for line in lines:
            truncated.append(line)
            if line.startswith("## 五") or line.startswith("## 六") or line.startswith("## 七"):
                section_count += 1
                if section_count >= 2:
                    break
        morning_text = "\n".join(truncated).strip()
        morning_section = f"""

今日早报的核心判断如下（供预期对比参考）：

{morning_text}"""

    # 实时行情数据
    snapshot_section = ""
    if price_snapshot:
        snapshot_section = f"""

{price_snapshot}"""

    prompt = REVIEW_USER_PROMPT_TEMPLATE.format(
        date=date_str,
        count=len(articles),
        morning_analysis=morning_section,
        price_snapshot=snapshot_section,
        news_content=news_text,
    )

    logger.info(f"发送复盘分析请求到 DeepSeek ({DEEPSEEK_MODEL})，共 {len(articles)} 条新闻")
    logger.info(f"复盘 Prompt 长度: {len(prompt)} 字符")

    max_retries = 3
    for attempt in range(max_retries):
        try:
            response = client.chat.completions.create(
                model=DEEPSEEK_MODEL,
                messages=[
                    {"role": "system", "content": REVIEW_SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                max_tokens=AI_MAX_TOKENS,
                temperature=AI_TEMPERATURE,
            )
            break
        except Exception as e:
            logger.warning(f"DeepSeek 复盘 API 调用失败（第 {attempt+1}/{max_retries} 次）: {e}")
            if attempt == max_retries - 1:
                raise
            time.sleep(2 ** attempt)

    content = response.choices[0].message.content
    logger.info(f"复盘分析完成 — tokens: {response.usage.prompt_tokens} → {response.usage.completion_tokens}")

    return content


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    # Quick test with dummy data
    articles = [
        {"title": "美联储维持利率不变", "source": "Reuters", "summary": "美联储宣布维持基准利率在5.25%-5.5%不变"},
    ]
    text = "1. [Reuters] 美联储维持利率不变\n   摘要: 美联储宣布维持基准利率不变\n"
    result = analyze_news(articles, "2026-05-01", text)
    print(result)
