"""Phase 2 噪声过滤：规则透明、可解释、可复现，全部基于 Phase 1 缓存数据。

设计原则（写进征文的那一节）：
  1) 不靠主观黑名单，优先用可计算的特征；
  2) 学术域名对「查询词零命中」设例外，因为 Industry=acad 会把中文查询召回英文论文；
  3) 「同域名限流」是去冗余而非删除，避免单一采集站霸榜；
  4) 所有被过滤条目与「差点误伤」条目都留痕，可逐条人工复核。

本模块不发起任何 API 调用。
"""

from __future__ import annotations

import re
from collections import Counter

from radar_config import TRUSTED_SUFFIXES
from radar_metrics import host_of, is_trusted, rank

FREE_HOSTING_SUFFIXES = (
    ".web.app", ".firebaseapp.com", ".pages.dev",
    ".vercel.app", ".netlify.app", ".onrender.com",
)

ACADEMIC_HOST_SUFFIXES = (
    "doi.org", "arxiv.org", "acm.org", "ieee.org", "springer.com",
    "sciencedirect.com", "cnki.net", "researchgate.net",
    "tandfonline.com", "sagepub.com", "wiley.com",
    "fachportal-paedagogik.de", "semanticscholar.org", "ncbi.nlm.nih.gov",
)

HOST_CAP = 3
MIN_SUMMARY_LEN = 40
JUNK_PATTERNS = (
    r"博彩", r"彩票", r"赌场", r"开户送", r"注册送",
    r"成人影片", r"兼职日结", r"\bSEO\b.*\b优化排名\b",
)

REASON_LABELS = {
    "free_hosting": "免费托管域名",
    "junk_keyword": "标题/摘要含垃圾特征",
    "short_summary": "摘要过短",
    "zero_query_hit": "查询词零命中（跨语种跑题）",
    "domain_cap": "同域名限流（去冗余）",
}

RULES = [
    ("free_hosting", "URL 命中免费托管后缀（.web.app 等）",
     "个人临时站点，缺乏可追溯的发布主体"),
    ("junk_keyword", "标题或摘要命中博彩 / 软文特征词",
     "与毕设技术主题无关的流量内容"),
    ("short_summary", "摘要短于 40 字",
     "信息量不足以判断相关性；本次实测摘要均在 719–803 字，预期 0 命中"),
    ("zero_query_hit", "查询词在标题 + 摘要中零命中，且域名不属于学术白名单",
     "跨语种跑题；学术文献设例外，避免误伤 Industry=acad 召回的英文论文"),
    ("domain_cap", "同一非权威域名只保留综合分最高的 3 条",
     "避免单一采集站霸榜；权威白名单域名不参与限流"),
]


def _tokens(query):
    return [t for t in str(query).split() if len(t) >= 2]


def _text(page):
    return "%s %s %s" % (
        str(page.get("title") or ""),
        str(page.get("passage") or ""),
        str(page.get("content") or ""),
    )


def _is_academic(host):
    return any(host == suffix or host.endswith("." + suffix)
               for suffix in ACADEMIC_HOST_SUFFIXES)


def filter_rows(rows):
    """过滤 Phase 1 的 8 路结果。

    Returns: (kept_sorted, removed, near_miss, hits)
      kept_sorted : 已按综合分排序的保留条目（已含 _final 等字段）
      removed     : 被过滤条目，每条带 _reason
      near_miss   : 零命中但因学术域名被保留的「差点误伤」条目
      hits        : 各规则命中数 dict
    """
    kept, removed, near_miss, hits = [], [], [], Counter()

    for row in rows:
        query = row["query"]
        tokens = _tokens(query)
        for page in row["pages"]:
            item = dict(page)
            item["_query"] = query
            item["_dimension"] = row["key"]
            item["_host"] = host_of(page.get("url", ""))
            text = _text(page)
            reason = None

            if any(item["_host"].endswith(s) for s in FREE_HOSTING_SUFFIXES):
                reason = "free_hosting"
            elif any(re.search(pattern, text) for pattern in JUNK_PATTERNS):
                reason = "junk_keyword"
            elif len(text) < MIN_SUMMARY_LEN:
                reason = "short_summary"
            elif tokens and not any(t.lower() in text.lower() for t in tokens):
                if _is_academic(item["_host"]):
                    near_miss.append(item)
                else:
                    reason = "zero_query_hit"

            if reason:
                hits[reason] += 1
                item["_reason"] = reason
                removed.append(item)
            else:
                kept.append(item)

    ranked = rank(kept)
    per_host = Counter()
    capped, capped_out = [], []
    for item in ranked:
        host = item["_host"]
        if is_trusted(item.get("url", "")):
            capped.append(item)
            continue
        per_host[host] += 1
        if per_host[host] > HOST_CAP:
            item["_reason"] = "domain_cap"
            hits["domain_cap"] += 1
            capped_out.append(item)
        else:
            capped.append(item)
    removed.extend(capped_out)
    return capped, removed, near_miss, dict(hits)


def top_metrics(items, n=10):
    """Top N 的可核验质量指标。"""
    top = items[:n]
    if not top:
        return {"total": 0, "top_n": 0, "top_trusted": 0,
                "top_trusted_share": 0.0, "top_avg_authority": 0.0,
                "top_avg_final": 0.0}
    trusted = sum(1 for item in top if is_trusted(item.get("url", "")))
    authority = sum(1.0 if is_trusted(item.get("url", "")) else 0.4
                    for item in top)
    final = sum(float(item.get("_final") or 0) for item in top)
    return {
        "total": len(items),
        "top_n": len(top),
        "top_trusted": trusted,
        "top_trusted_share": round(trusted / len(top), 3),
        "top_avg_authority": round(authority / len(top), 3),
        "top_avg_final": round(final / len(top), 4),
    }


def removed_summary(removed, limit=20):
    out = []
    for item in removed[:limit]:
        out.append({
            "reason": item.get("_reason"),
            "title": str(item.get("title") or "")[:100],
            "host": item.get("_host"),
            "query": item.get("_query"),
        })
    return out
