"""
实时股价获取模块
从新浪财经 API 获取 A股/港股/美股的盘前实时行情
"""
import logging
import re
import ssl
import time
import random
import requests
from requests.adapters import HTTPAdapter

from config import REQUEST_TIMEOUT

logger = logging.getLogger(__name__)

# 新浪财经行情 API
_SINA_QUOTE_URL = "https://hq.sinajs.cn/list={codes}"

_SINA_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/140.0.0.0 Safari/537.36"
    ),
    "Referer": "https://finance.sina.com.cn",
}


class _HTTP1Adapter(HTTPAdapter):
    """TLS 1.2+ / HTTP 1.1 only — 避免 HTTP/2 触发国内 CDN 的 SSL EOF"""
    def init_poolmanager(self, *args, **kwargs):
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        ctx.minimum_version = ssl.TLSVersion.TLSv1_2
        ctx.set_alpn_protocols(["http/1.1"])
        kwargs["ssl_context"] = ctx
        return super().init_poolmanager(*args, **kwargs)


_SESSION = requests.Session()
_SESSION.mount("https://", _HTTP1Adapter())

# 东方财富等 HTTP/2 CDN 用独立 session，不加 HTTP/1.1 适配器
_EM_SESSION = requests.Session()


def _http_get(url: str, timeout: int = 10) -> requests.Response:
    """带 SSL 重试的 HTTP GET"""
    last_err = None
    for attempt in range(3):
        try:
            return _SESSION.get(url, timeout=timeout, headers=_SINA_HEADERS)
        except requests.exceptions.SSLError:
            last_err = Exception()
            if attempt < 2:
                time.sleep(1.0 + random.random())
    raise last_err


def fetch_prices(codes: list[str]) -> dict[str, dict]:
    """
    从新浪财经获取实时行情

    codes: 新浪格式代码列表，如 ["sh600519", "sz000001", "hk00700", "gb_aapl"]
    返回: {code: {name, price, prev_close, change_pct, market, time}, ...}
    失败返回空 dict
    """
    if not codes:
        return {}

    url = _SINA_QUOTE_URL.format(codes=",".join(codes))

    try:
        resp = _http_get(url)
        resp.raise_for_status()
        resp.encoding = "gb2312"
        raw = resp.text
    except requests.RequestException as e:
        logger.warning(f"新浪财经行情获取失败: {e}")
        return {}
    except Exception as e:
        logger.warning(f"行情响应解析失败: {e}")
        return {}

    results = {}
    for line in raw.strip().split("\n"):
        line = line.strip()
        if not line or '=""' in line:
            continue

        m = re.match(r'var hq_str_(.+?)="(.+)"', line)
        if not m:
            continue

        code = m.group(1)
        fields = m.group(2).split(",")

        try:
            parsed = _parse_fields(code, fields)
            if parsed and parsed.get("price", 0) > 0:
                results[code] = parsed
        except Exception:
            logger.debug(f"解析 {code} 行情失败", exc_info=True)

    logger.info(f"获取到 {len(results)}/{len(codes)} 只股票实时行情")
    return results


def _parse_fields(code: str, fields: list[str]) -> dict | None:
    """根据代码前缀解析字段"""
    if not fields or not fields[0]:
        return None

    if code.startswith("sh") or code.startswith("sz"):
        return _parse_a_stock(fields)
    elif code.startswith("hk"):
        return _parse_hk_stock(fields)
    elif code.startswith("gb_"):
        return _parse_us_stock(code, fields)
    elif code.startswith("s_sh") or code.startswith("s_sz"):
        return _parse_cn_index(fields)
    return None


def _parse_a_stock(fields: list[str]) -> dict | None:
    """解析 A股个股
    字段: [0]名称 [1]今开 [2]昨收 [3]当前价 [4]最高 [5]最低
          [8]成交量 [30]日期 [31]时间
    """
    name = fields[0]
    price = _float(fields[3])
    prev_close = _float(fields[2])

    if price <= 0:
        return None

    change = price - prev_close
    change_pct = (change / prev_close * 100) if prev_close > 0 else 0

    return {
        "name": name,
        "price": round(price, 2),
        "prev_close": round(prev_close, 2),
        "open": _float(fields[1]),
        "high": _float(fields[4]),
        "low": _float(fields[5]),
        "change": round(change, 2),
        "change_pct": round(change_pct, 2),
        "volume": int(_float(fields[8])),
        "date": fields[30] if len(fields) > 30 else "",
        "time": fields[31] if len(fields) > 31 else "",
        "market": "A股",
    }


def _parse_cn_index(fields: list[str]) -> dict | None:
    """解析 A股指数
    字段: [0]名称 [1]当前点数 [2]涨跌点数 [3]涨跌幅%
    """
    name = fields[0]
    price = _float(fields[1])
    change = _float(fields[2])
    change_pct = _float(fields[3])

    if price <= 0:
        return None

    prev_close = price - change

    return {
        "name": name,
        "price": round(price, 2),
        "prev_close": round(prev_close, 2),
        "open": 0,
        "high": 0,
        "low": 0,
        "change": round(change, 2),
        "change_pct": round(change_pct, 2),
        "volume": 0,
        "date": "",
        "time": "",
        "market": "指数",
    }


def _parse_hk_stock(fields: list[str]) -> dict | None:
    """解析港股 (hk 前缀)
    字段: [0]英文名 [1]中文名 [2]今开 [3]昨收 [4]最高 [5]最低
          [6]当前价 [7]涨跌额 [8]涨跌幅% [9]买一 [10]卖一
    """
    name_en = fields[0].strip()
    name_cn = fields[1].strip() if len(fields) > 1 else ""
    name = name_cn if name_cn and name_cn != "0.000" else name_en

    price = _float(fields[6]) if len(fields) > 6 else 0
    if price <= 0:
        return None

    prev_close = _float(fields[3]) if len(fields) > 3 else 0
    change = _float(fields[7]) if len(fields) > 7 else 0
    change_pct = _float(fields[8]) if len(fields) > 8 else 0

    # 如果涨跌额合理但与价差不符，以价差为准
    if change != 0 and abs(change - (price - prev_close)) > 0.1:
        change = round(price - prev_close, 2)
        change_pct = round(change / prev_close * 100, 2) if prev_close > 0 else 0

    if prev_close <= 0:
        prev_close = round(price - change, 2)
    if change_pct == 0 and prev_close > 0:
        change_pct = round(change / prev_close * 100, 2)

    return {
        "name": name,
        "price": round(price, 2),
        "prev_close": round(prev_close, 2),
        "open": _float(fields[2]) if len(fields) > 2 else 0,
        "high": _float(fields[4]) if len(fields) > 4 else 0,
        "low": _float(fields[5]) if len(fields) > 5 else 0,
        "change": round(change, 2),
        "change_pct": round(change_pct, 2),
        "volume": 0,
        "date": fields[17] if len(fields) > 17 else "",
        "time": fields[18] if len(fields) > 18 else "",
        "market": "港股",
    }


def _parse_us_stock(code: str, fields: list[str]) -> dict | None:
    """解析美股 (gb_ 前缀)
    字段: [0]名称 [1]当前价 [2]涨跌额 [3]涨跌幅% [4]日期时间
          [5]今开? ... 后续字段因数据源不同差异较大
    改用 价格±涨跌额 反推昨收，避免字段位置漂移
    """
    name = fields[0]
    price = _float(fields[1])
    change = _float(fields[2])

    if price <= 0:
        return None

    # 从价格和涨跌额推算昨收
    prev_close = round(price - change, 2)
    change_pct = round(change / prev_close * 100, 2) if prev_close > 0 else 0

    return {
        "name": name,
        "price": round(price, 2),
        "prev_close": prev_close,
        "open": 0,
        "high": 0,
        "low": 0,
        "change": round(change, 2),
        "change_pct": change_pct,
        "volume": 0,
        "date": fields[4] if len(fields) > 4 and ":" in str(fields[4]) else "",
        "time": "",
        "market": "美股",
    }


def _float(val: str) -> float:
    """安全转 float"""
    try:
        return float(val)
    except (ValueError, TypeError):
        return 0.0


# ═══════════════════════════════════════════════════════════════
# 股票代码转换：AI 输出格式 → 新浪 API 格式
# ═══════════════════════════════════════════════════════════════

def codes_to_sina(codes: list[str]) -> list[str]:
    """
    将 AI 分析中出现的股票代码转换为新浪 API 格式

    AI 输出示例: 600519.SH, 000001.SZ, 00700.HK, AAPL.US, AAPL
    Sina 格式: sh600519, sz000001, hk00700, gb_aapl

    无法识别的代码会被跳过
    """
    sina_codes = []
    for raw in codes:
        raw = raw.strip().upper()
        if not raw:
            continue

        code = _convert_single(raw)
        if code:
            sina_codes.append(code)
        else:
            logger.debug(f"无法转换股票代码: {raw}")

    return sina_codes


def _convert_single(raw: str) -> str | None:
    """转换单个股票代码"""
    # 去掉可能的前后缀中的点号
    # 600519.SH → sh600519, AAPL.US → gb_aapl
    if "." in raw:
        parts = raw.split(".")
        ticker = parts[0]
        market = parts[1] if len(parts) > 1 else ""
    else:
        ticker = raw
        market = ""

    # 纯数字 → A股/港股
    if ticker.isdigit():
        if market in ("SH", "SS"):
            return f"sh{ticker}"
        elif market in ("SZ",):
            return f"sz{ticker}"
        elif market == "HK":
            return f"hk{ticker}"
        elif len(ticker) == 5:
            # 5位数字 → 港股
            return f"hk{ticker}"
        elif len(ticker) == 6:
            # 6位数字，按首位判断沪深
            if ticker[0] in ("6", "5", "9"):
                return f"sh{ticker}"
            else:
                return f"sz{ticker}"
        else:
            return None

    # 字母 → 美股
    if ticker.isalpha():
        return f"gb_{ticker.lower()}"

    return None


def format_prices_for_ai(prices: dict[str, dict]) -> str:
    """将行情数据格式化为 AI 可读文本"""
    if not prices:
        return ""

    lines = ["## 实时行情数据（盘前参考）", ""]
    lines.append("| 股票 | 代码 | 当前价 | 昨收 | 涨跌幅 | 市场 |")
    lines.append("| ---- | ---- | ------ | ---- | ------ | ---- |")

    for code, info in prices.items():
        name = info["name"]
        price = info["price"]
        prev = info["prev_close"]
        change_str = f"{info['change']:+.2f}"
        pct_str = f"{info['change_pct']:+.2f}%"
        market = info["market"]

        direction = "🔴" if info["change"] < 0 else ("🟢" if info["change"] > 0 else "⚪")
        lines.append(
            f"| {name} | {code} | {price:.2f} | {prev:.2f} | "
            f"{direction} {change_str} ({pct_str}) | {market} |"
        )

    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════
# 日K线走势数据（东方财富 API）
# ═══════════════════════════════════════════════════════════════

_EM_KLINE_URL = (
    "https://push2his.eastmoney.com/api/qt/stock/kline/get"
    "?secid={secid}&fields1=f1,f2,f3,f4,f5,f6"
    "&fields2=f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61"
    "&klt=101&fqt=0&end=20500101&lmt=15"
)

# 新浪代码 → 东方财富 secid 映射
def _sina_to_eastmoney(sina_code: str) -> str | None:
    """sh600519 → 1.600519, sz300750 → 0.300750, hk00700 → 116.00700, gb_aapl → 105.AAPL"""
    if sina_code.startswith("sh"):
        return f"1.{sina_code[2:]}"
    elif sina_code.startswith("sz"):
        return f"0.{sina_code[2:]}"
    elif sina_code.startswith("hk"):
        return f"116.{sina_code[2:]}"
    elif sina_code.startswith("gb_"):
        ticker = sina_code[3:].upper()
        return f"105.{ticker}"  # NASDAQ，大部分中概/科技股
    return None


def fetch_daily_trends(sina_codes: list[str]) -> dict[str, list[dict]]:
    """
    获取近15个交易日的日K线数据

    返回: {sina_code: [{date, open, close, high, low, volume, change_pct}, ...], ...}
    """
    if not sina_codes:
        return {}

    trends = {}
    for sc in sina_codes:
        secid = _sina_to_eastmoney(sc)
        if not secid:
            continue

        url = _EM_KLINE_URL.format(secid=secid)
        data = None
        for attempt in range(2):
            try:
                resp = _EM_SESSION.get(url, headers=_SINA_HEADERS, timeout=10)
                resp.raise_for_status()
                data = resp.json()
                break
            except Exception as e:
                if attempt == 0:
                    logger.debug(f"获取 {sc} K线失败(重试): {e}")
                    time.sleep(0.5)
                    continue
                logger.debug(f"获取 {sc} K线数据失败: {e}")

        if data is None:
            continue

        klines = data.get("data", {}).get("klines", [])
        if not klines:
            continue

        days = []
        for k in klines:
            parts = k.split(",")
            if len(parts) < 9:
                continue
            # f51=日期 f52=开盘 f53=收盘 f54=最高 f55=最低 f56=成交量 f57=成交额 f58=振幅 f59=涨跌幅
            days.append({
                "date": parts[0],
                "open": _float(parts[1]),
                "close": _float(parts[2]),
                "high": _float(parts[3]),
                "low": _float(parts[4]),
                "volume": int(_float(parts[5])),
                "change_pct": _float(parts[8]),
            })
        trends[sc] = days

    logger.info(f"获取到 {len(trends)}/{len(sina_codes)} 只股票的K线走势")
    return trends


def compute_trend_summary(trends: dict[str, list[dict]]) -> dict[str, dict]:
    """
    基于日K线计算趋势摘要

    返回: {sina_code: {d5_chg, d10_chg, d5_high, d5_low, d10_high, d10_low,
                       trend_desc, ma5, ma10, support, resistance}, ...}
    """
    summaries = {}
    for code, days in trends.items():
        if len(days) < 3:
            continue

        closes = [d["close"] for d in days]
        highs = [d["high"] for d in days]
        lows = [d["low"] for d in days]
        latest = closes[-1]

        # 5日/10日/15日涨跌
        n = len(closes)
        d5_chg = (closes[-1] / closes[-min(n, 6)] - 1) * 100 if n >= 6 else 0
        d10_chg = (closes[-1] / closes[-min(n, 11)] - 1) * 100 if n >= 11 else 0

        # 近期高低点
        lookback5 = min(5, n)
        d5_high = max(highs[-lookback5:])
        d5_low = min(lows[-lookback5:])
        lookback10 = min(10, n)
        d10_high = max(highs[-lookback10:])
        d10_low = min(lows[-lookback10:])

        # 均线
        ma5 = sum(closes[-min(5, n):]) / min(5, n)
        ma10 = sum(closes[-min(10, n):]) / min(10, n)

        # 趋势描述
        if d5_chg > 3:
            trend_desc = "短线强势上涨"
        elif d5_chg > 0:
            trend_desc = "短线温和上行"
        elif d5_chg > -3:
            trend_desc = "短线震荡整理"
        elif d5_chg > -8:
            trend_desc = "短线偏弱下行"
        else:
            trend_desc = "短线加速下跌"

        # 支撑/阻力
        support = round(ma10, 2) if latest > ma10 else round(d10_low, 2)
        resistance = round(d10_high, 2)

        summaries[code] = {
            "d5_chg": round(d5_chg, 2),
            "d10_chg": round(d10_chg, 2),
            "d5_high": round(d5_high, 2),
            "d5_low": round(d5_low, 2),
            "d10_high": round(d10_high, 2),
            "d10_low": round(d10_low, 2),
            "ma5": round(ma5, 2),
            "ma10": round(ma10, 2),
            "trend_desc": trend_desc,
            "support": support,
            "resistance": resistance,
            "latest_close": round(latest, 2),
        }
    return summaries


def format_trends_for_ai(prices: dict[str, dict], trends: dict[str, dict]) -> str:
    """将实时行情 + 趋势摘要格式化为 AI 可读的综合表格"""
    if not prices:
        return ""

    lines = ["## 行情走势数据", ""]
    lines.append("| 股票 | 现价 | 今涨跌 | 5日涨跌 | 10日涨跌 | 5日区间 | 10日区间 | MA5 | 支撑 | 阻力 | 趋势 |")
    lines.append("| ---- | ---- | ------ | ------- | -------- | ------- | -------- | --- | ---- | ---- | ---- |")

    for code, info in prices.items():
        name = info["name"]
        price = info["price"]
        chg_str = f"{info['change_pct']:+.2f}%"
        direction = "🔴" if info["change_pct"] < 0 else ("🟢" if info["change_pct"] > 0 else "⚪")

        ts = trends.get(code)
        if ts:
            d5 = f"{ts['d5_chg']:+.2f}%"
            d10 = f"{ts['d10_chg']:+.2f}%"
            d5_range = f"{ts['d5_low']:.2f}-{ts['d5_high']:.2f}"
            d10_range = f"{ts['d10_low']:.2f}-{ts['d10_high']:.2f}"
            ma5 = f"{ts['ma5']:.2f}"
            support = f"{ts['support']:.2f}"
            resistance = f"{ts['resistance']:.2f}"
            trend = ts["trend_desc"]
        else:
            d5 = d10 = d5_range = d10_range = ma5 = support = resistance = "-"
            trend = "数据不足"

        lines.append(
            f"| {name} | {price:.2f} | {direction} {chg_str} | {d5} | {d10} | "
            f"{d5_range} | {d10_range} | {ma5} | {support} | {resistance} | {trend} |"
        )

    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════
# 收盘复盘专用：市场行情快照
# ═══════════════════════════════════════════════════════════════

MARKET_INDEX_CODES = [
    "000001.SH",  # 上证指数
    "399001.SZ",  # 深证成指
    "399006.SZ",  # 创业板指
    "000016.SH",  # 上证50
    "000300.SH",  # 沪深300
    "000688.SH",  # 科创50
]


def fetch_market_snapshot() -> str:
    """获取主要市场指数行情并格式化为文本，供复盘 AI 引用"""
    sina_codes = codes_to_sina(MARKET_INDEX_CODES)
    prices = fetch_prices(sina_codes)
    if not prices:
        return ""

    lines = ["## 今日收盘行情数据（实时爬取）", ""]
    lines.append("| 指数名称 | 最新点位 | 涨跌点数 | 涨跌幅 |")
    lines.append("| -------- | ------- | -------- | ------ |")

    for code in sina_codes:
        info = prices.get(code)
        if not info:
            continue
        arrow = "↑" if info["change"] > 0 else ("↓" if info["change"] < 0 else "→")
        lines.append(
            f"| {info['name']} | {info['price']:.2f} | "
            f"{arrow} {info['change']:+.2f} | {info['change_pct']:+.2f}% |"
        )

    lines.append("")
    return "\n".join(lines)
