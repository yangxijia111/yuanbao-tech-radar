"""Phase 1 指标与容错工具：把 SearchPro 的原始结果变成可核验的量化证据。

三个真实存在的问题在这里处理：
  1) date 字段有多种形态且经常缺失，解析必须容错；
  2) 同一篇文章在不同站点重复出现，需要 URL 归一化去重；
  3) 传 Industry 后 score 会偏离文档标称的 0~1，跨组比较前需组内归一化。
"""

from __future__ import annotations

from datetime import datetime, timezone
from urllib.parse import urlsplit

from radar_config import TRUSTED_SUFFIXES

DATE_FORMATS = (
    "%Y/%m/%d %H:%M:%S", "%Y-%m-%d %H:%M:%S",
    "%Y/%m/%d", "%Y-%m-%d", "%Y.%m.%d", "%Y年%m月%d日",
    "%Y/%m/%d %H:%M", "%Y-%m-%d %H:%M",
)


def parse_date(value):
    """返回 naive datetime；无法解析一律返回 None，绝不让脏日期中断整条流水线。"""
    if value in (None, "", [], {}):
        return None
    if isinstance(value, (int, float)) or (isinstance(value, str) and value.isdigit()):
        number = int(float(value))
        if number > 10 ** 12:
            number //= 1000
        try:
            return datetime.fromtimestamp(number, timezone.utc).replace(tzinfo=None)
        except (OSError, ValueError, OverflowError):
            return None
    text = str(value).strip()
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None


def normalized_url(url):
    """去掉 query / hash / www. / 尾部斜杠，用于跨站点去重。"""
    if not url:
        return ""
    try:
        parts = urlsplit(str(url))
    except ValueError:
        return str(url).strip().lower()
    host = (parts.hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    path = parts.path.rstrip("/")
    return (host + path).lower()


def host_of(url):
    try:
        host = (urlsplit(str(url)).hostname or "").lower()
    except ValueError:
        return ""
    return host[4:] if host.startswith("www.") else host


def is_trusted(url):
    host = host_of(url)
    if not host:
        return False
    return any(host == suffix or host.endswith("." + suffix)
               for suffix in TRUSTED_SUFFIXES)


def measure(pages, latency_ms, now=None):
    """一组结果的量化指标。所有比例同时给出分子，避免"覆盖率"被误读。"""
    now = now or datetime.now()
    scores = [p["score"] for p in pages
              if isinstance(p.get("score"), (int, float))]
    dates = [parse_date(p.get("date")) for p in pages]
    dated = [d for d in dates if d is not None]
    fresh30 = sum(1 for d in dated if 0 <= (now - d).days <= 30)
    trusted = sum(1 for p in pages if is_trusted(p.get("url", "")))
    count = len(pages)
    return {
        "count": count,
        "date_coverage": len(dated),
        "date_missing": count - len(dated),
        "trusted_count": trusted,
        "trusted_share": round(trusted / count, 3) if count else 0.0,
        "fresh30_count": fresh30,
        "fresh30_share_of_dated": round(fresh30 / len(dated), 3) if dated else None,
        "score_n": len(scores),
        "score_avg": round(sum(scores) / len(scores), 4) if scores else None,
        "score_min": round(min(scores), 4) if scores else None,
        "score_max": round(max(scores), 4) if scores else None,
        "latency_ms": latency_ms,
    }


def dedupe(pages):
    """按归一化 URL 去重；同 URL 保留 score 更高的一条。"""
    seen = {}
    for page in pages:
        key = normalized_url(page.get("url", "")) or str(page.get("title", ""))
        if not key:
            continue
        old = seen.get(key)
        if old is None or (page.get("score") or 0) > (old.get("score") or 0):
            seen[key] = page
    return list(seen.values())


def rank(pages, now=None):
    """组内 min-max 归一化后再加权，避免 Industry 组因量纲不同整体霸榜。

    final = rel * 0.6 + authority * 0.25 + freshness * 0.15
    """
    now = now or datetime.now()
    values = [p["score"] for p in pages
              if isinstance(p.get("score"), (int, float))]
    low, high = (min(values), max(values)) if values else (0.0, 1.0)
    spread = high - low
    out = []
    for page in pages:
        item = dict(page)
        raw = item.get("score")
        if isinstance(raw, (int, float)):
            rel = 0.5 if spread < 1e-6 else (raw - low) / spread
        else:
            rel = 0.5
        authority = 1.0 if is_trusted(item.get("url", "")) else 0.4
        parsed = parse_date(item.get("date"))
        if parsed is None:
            fresh = 0.30
        else:
            days = (now - parsed).days
            fresh = 1.0 if days <= 90 else 0.6 if days <= 365 else 0.3
        item["_rel"] = round(rel, 4)
        item["_authority"] = authority
        item["_fresh"] = fresh
        item["_final"] = round(rel * 0.6 + authority * 0.25 + fresh * 0.15, 4)
        item["_trusted"] = authority == 1.0
        out.append(item)
    return sorted(out, key=lambda x: x["_final"], reverse=True)


def ab_notes(rows):
    """从 A/B 数据里自动提取可写进文章的实测结论（只陈述数字，不做推测）。"""
    notes = []
    base = rows[0]["metrics"] if rows else {}
    for row in rows:
        label, m = row["label"], row["metrics"]
        if row.get("error"):
            notes.append("%s：调用失败（%s）" % (label, row["error"]))
            continue
        if m["count"] == 0:
            notes.append("%s：正常返回但结果为 0 条，该参数不宜当过滤器用" % label)
        if m["score_max"] is not None and m["score_max"] > 1.05:
            notes.append("%s：score 最高 %.4f，超出文档标称的 0~1，跨组排序前必须组内归一化"
                         % (label, m["score_max"]))
        if m["count"] > 0 and m["date_coverage"] == 0:
            notes.append("%s：召回 %d 条、权威源占比 %.1f%%，但 date 覆盖 0/%d，时效性打分会整体失效"
                         % (label, m["count"], m["trusted_share"] * 100, m["count"]))
        if label.startswith("Cnt") and base.get("count") and m["count"] > base["count"]:
            notes.append("%s：条数由 %d 增至 %d，权威源占比由 %.1f%% 变为 %.1f%%（尾部质量被稀释）"
                         % (label, base["count"], m["count"],
                            base.get("trusted_share", 0) * 100,
                            m["trusted_share"] * 100))
    for row in rows[1:]:
        label, m = row["label"], row["metrics"]
        if not row.get("error") and label.startswith("Freshness"):
            if m["fresh30_share_of_dated"] is not None:
                notes.append("%s：有日期结果中近 30 天占比 %.1f%%，date 覆盖 %d/%d"
                             % (label, m["fresh30_share_of_dated"] * 100,
                                m["date_coverage"], m["count"]))
            tb = base.get("trusted_share")
            if tb and m["trusted_share"] < tb:
                notes.append("%s：权威源占比由基线 %.1f%% 降至 %.1f%%，收紧时效会牺牲权威度"
                             % (label, tb * 100, m["trusted_share"] * 100))

    def find(prefix):
        for row in rows:
            if row["label"].startswith(prefix) and not row.get("error"):
                return row["metrics"]
        return None

    m0, m2 = find("Mode=0"), find("Mode=2")
    if m0 and m2 and (m0["count"], m0["score_avg"], m0["trusted_share"]) == (
            m2["count"], m2["score_avg"], m2["trusted_share"]):
        notes.append("Mode=2 与 Mode=0 指标完全一致：标准版下「混合」并未额外拼入权威垂直结果")
    return notes
