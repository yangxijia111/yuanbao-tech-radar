"""Phase 2：噪声过滤前后 A/B + 可视化证据页。

全部复用 Phase 1 缓存结果，**不发起任何 API 调用**（0 额度），
因此可以随时重跑、逐条复算，也方便征文里写「成本」这一节。

用法：
  python src/run_phase2.py

产出：
  evidence/phase2_ab.json        v1/v2 对照指标、规则命中、被过滤样例、误伤审计
  evidence/phase2_report.html    可截图的总览证据页
  reports/<日期>-clean.md        过滤后的正式简报
"""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import noise_filter as nf  # noqa: E402
import radar_config as cfg  # noqa: E402
import radar_metrics as met  # noqa: E402
from smoke import CSS, esc  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
EVIDENCE = ROOT / "evidence"
REPORTS = ROOT / "reports"

EXTRA_CSS = """
.two{display:grid;grid-template-columns:1fr 1fr;gap:16px}
@media(max-width:860px){.two{grid-template-columns:1fr}}
.pill{display:inline-block;padding:1px 8px;border-radius:10px;font-size:11px;
 border:1px solid #24313e;color:#8b98a5;margin-right:4px}
.pill.keep{color:#22d3ee;border-color:#1d5d6b}
.pill.warn{color:#EF9F27;border-color:#6b5220}
.delta{font-size:12px;color:#22d3ee;margin-left:6px}
.rule{font-size:12px;color:#aebbc8}
.small{font-size:11.5px;color:#7f8d9b}
"""


def by_dimension(items):
    grouped = {}
    for item in items:
        grouped.setdefault(item.get("_dimension", "other"), []).append(item)
    return {key: pages[:cfg.TOP_PER_DIMENSION] for key, pages in grouped.items()}


def build_clean_md(v2, removed, near_miss, hits, m1, m2, date_str):
    tops = by_dimension(v2)
    lines = [
        "# Unity / WebGL 毕设技术雷达 · 过滤版 · %s" % date_str,
        "",
        "> 由 `src/run_phase2.py` 基于 Phase 1 缓存的 80 条真实结果生成，"
        "**本次 0 次 API 调用**，条目未经手工增删。",
        "> v1（纯归一化排序）保留 %d 条 → v2（噪声过滤）保留 %d 条；"
        "Top10 权威源占比由 %.1f%% 变为 %.1f%%。"
        % (m1["total"], m2["total"],
           m1["top_trusted_share"] * 100, m2["top_trusted_share"] * 100),
        "> 每条保留原始链接、站点与发布时间；规则命中、被过滤条目与差点误伤条目"
        "见 `evidence/phase2_ab.json`。",
        "",
    ]
    for index, dim in enumerate(cfg.DIMENSIONS, 1):
        lines.append("## %d. %s" % (index, dim["name"]))
        lines.append("")
        lines.append("> 检索理由：%s" % dim["why"])
        lines.append("")
        pages = tops.get(dim["key"], [])
        if not pages:
            lines.append("_该维度在过滤后无保留条目。_")
            lines.append("")
            continue
        for i, page in enumerate(pages, 1):
            title = str(page.get("title") or page.get("url") or "无标题")
            url = str(page.get("url") or "")
            head = ("[%s](%s)" % (title, url)) if url.startswith("http") else title
            tag = "`权威源`" if met.is_trusted(url) else ""
            lines.append("%d. **%s** %s · %s · %s · score %s · 综合 %s"
                         % (i, head, tag, esc(page.get("site") or "站点未标注"),
                            esc(page.get("date") or "无发布时间"),
                            esc(page.get("score") or "n/a"),
                            esc(page.get("_final") or "n/a")))
            summary = str(page.get("passage") or page.get("content") or "").strip()
            if summary:
                lines.append("   %s" % summary[:120].replace("\n", " "))
        lines.append("")

    lines.extend(["## 附一：过滤规则与本次命中", "",
                  "| 规则 | 判定依据 | 命中数 |", "|---|---|---|"])
    labels = dict((r[0], r[1]) for r in nf.RULES)
    for key in nf.REASON_LABELS:
        lines.append("| %s | %s | %d |"
                     % (nf.REASON_LABELS[key], labels.get(key, ""), hits.get(key, 0)))
    lines.extend(["", "共过滤 %d 条，保留 %d 条。" % (len(removed), m2["total"]), ""])

    lines.extend(["## 附二：差点误伤（学术域名例外）", "",
                  "以下条目查询词零命中，若规则一刀切会被删除；"
                  "因域名属于学术白名单而保留，说明规则边界需要人工复核。", ""])
    for item in near_miss:
        lines.append("- %s · `%s` · 来自「%s」"
                     % (esc(str(item.get("title") or ""))[:90],
                        esc(item.get("_host")), esc(item.get("_query"))))
    if not near_miss:
        lines.append("- 本次无此类条目。")
    lines.extend([
        "", "> 取舍说明：本次增益主要来自「同域名限流」（命中 %d 条），不是垃圾内容识别。"
        "它会同时损失部分同站的相关文章，例如 blog.csdn.net 由 21 条限到 3 条；"
        "这是控制单一来源霸榜的代价，需要按实际效果持续调整。"
        % hits.get("domain_cap", 0),
        "", "---",
        "版权归原站点所有，引用前请点开原文核对。"
        "完整证据：`evidence/phase1_raw.json`、`phase2_ab.json`、`phase2_report.html`。",
        "",
    ])
    return "\n".join(lines)


def build_html(v1, v2, removed, near_miss, hits, m1, m2, date_str):
    parts = [
        "<!DOCTYPE html><html lang=\"zh-CN\"><head><meta charset=\"utf-8\">",
        "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">",
        "<title>Phase 2 · 噪声过滤前后 A/B</title><style>", CSS, EXTRA_CSS,
        "</style></head><body><div class=\"wrap\">",
        "<h1>Phase 2 · 噪声过滤前后 A/B</h1>",
        "<p class=\"sub\">v1 纯归一化排序 vs v2 加噪声过滤；全部复用 Phase 1 缓存结果，"
        "<b>本次 0 次 API 调用</b>，可随时重跑复算。密钥已脱敏。</p>",
    ]
    chips = [
        ("生成时间", date_str + " " + datetime.now().strftime("%H:%M:%S")),
        ("数据源", "phase1_radar.json"),
        ("原始条目", "80 条 / 8 路"),
        ("额外调用", "0 次"),
    ]
    parts.append("<div class=\"meta\">")
    for key, value in chips:
        parts.append("<span class=\"chip\">%s <b>%s</b></span>" % (esc(key), esc(value)))
    parts.append("</div>")

    d_trusted = (m2["top_trusted_share"] - m1["top_trusted_share"]) * 100
    cards = [
        ("v1 保留", str(m1["total"]), ""),
        ("v2 保留", str(m2["total"]), "过滤 %d 条" % len(removed)),
        ("v1 Top10 权威占比", "%.1f%%" % (m1["top_trusted_share"] * 100), ""),
        ("v2 Top10 权威占比", "%.1f%%" % (m2["top_trusted_share"] * 100),
         "%+.1f pp" % d_trusted),
    ]
    parts.append("<div class=\"grid\">")
    for key, value, delta in cards:
        parts.append("<div class=\"metric\"><div class=\"k\">%s</div>"
                     "<div class=\"v\">%s<span class=\"delta\">%s</span></div></div>"
                     % (esc(key), esc(value), esc(delta)))
    parts.append("</div>")

    parts.append("<h2>过滤规则与本次命中</h2><div class=\"card\"><table><thead><tr>"
                 "<th>规则</th><th>判定依据</th><th>设计理由</th><th>命中</th>"
                 "</tr></thead><tbody>")
    for key, basis, why in nf.RULES:
        parts.append("<tr><td>%s</td><td class=\"rule\">%s</td>"
                     "<td class=\"rule\">%s</td><td>%d</td></tr>"
                     % (esc(nf.REASON_LABELS[key]), esc(basis), esc(why),
                        hits.get(key, 0)))
    parts.append("</tbody></table></div>")

    parts.append("<h2>v1 vs v2 · Top 10 对照</h2><div class=\"two\">")
    for label, items, cls in (("v1 · 纯归一化排序", v1, ""),
                              ("v2 · 加噪声过滤", v2, "keep")):
        parts.append("<div class=\"card\"><h2 style=\"margin-top:0\">%s</h2>" % label)
        parts.append("<table><thead><tr><th style=\"width:30px\">#</th><th>标题</th>"
                     "<th style=\"width:110px\">站点</th><th style=\"width:70px\">综合分</th>"
                     "</tr></thead><tbody>")
        for i, item in enumerate(items[:10], 1):
            title = str(item.get("title") or item.get("url") or "—")
            url = str(item.get("url") or "")
            link = ("<a href=\"%s\" target=\"_blank\" rel=\"noopener\">%s</a>"
                    % (esc(url), esc(title[:54]))) if url.startswith("http") else esc(title[:54])
            if met.is_trusted(url):
                link = "<span class=\"pill keep\">权威</span>" + link
            parts.append("<tr><td>%d</td><td>%s</td><td>%s</td><td>%s</td></tr>"
                         % (i, link, esc((item.get("site") or "—")[:16]),
                            esc(item.get("_final") or "—")))
        parts.append("</tbody></table></div>")
    parts.append("</div>")

    parts.append("<h2>被过滤样例（可逐条复核）</h2><div class=\"card\">"
                 "<table><thead><tr><th>标题</th><th>域名</th><th>规则</th>"
                 "</tr></thead><tbody>")
    for item in nf.removed_summary(removed, limit=12):
        parts.append("<tr><td>%s</td><td>%s</td><td><span class=\"pill warn\">%s</span></td></tr>"
                     % (esc(item["title"][:70]), esc(item["host"]),
                        esc(nf.REASON_LABELS.get(item["reason"], item["reason"]))))
    parts.append("</tbody></table></div>")

    parts.append("<h2>差点误伤 · 学术域名例外</h2><div class=\"card\">")
    parts.append("<p class=\"sub\">以下条目查询词零命中，若不做例外会被当成跨语种跑题删掉；"
                 "它们其实是 <code>Industry=acad</code> 召回的英文论文。"
                 "规则边界必须人工复核，这一层不做自动化替人拍板。</p>")
    parts.append("<table><thead><tr><th>标题</th><th>域名</th><th>来源检索式</th>"
                 "</tr></thead><tbody>")
    for item in near_miss:
        parts.append("<tr><td>%s</td><td>%s</td><td class=\"small\">%s</td></tr>"
                     % (esc(str(item.get("title") or ""))[:80],
                        esc(item.get("_host")), esc(item.get("_query"))[:36]))
    if not near_miss:
        parts.append("<tr><td colspan=\"3\">本次无此类条目</td></tr>")
    parts.append("</tbody></table></div>")

    parts.append(
        "<div class=\"foot\">取舍说明：本次增益主要来自「同域名限流」（命中 %d 条），"
        "并非垃圾内容识别；它会同时损失部分同站的相关文章，"
        "例如 blog.csdn.net 由 21 条限到 3 条。规则需按实际效果持续维护，"
        "不是一次写完就完事。<br><br>"
        "证据说明：v1 为 <code>rank(dedupe(all))</code>，"
        "v2 为 <code>filter_rows()</code> 后再排序，规则源码见 "
        "<code>src/noise_filter.py</code>。全部数字可由 "
        "<code>phase1_radar.json</code> + <code>phase2_ab.json</code> 复算，"
        "本次未新增任何接口调用。</div>"
        % hits.get("domain_cap", 0)
    )
    parts.append("</div></body></html>")
    return "".join(parts)


def main():
    source = EVIDENCE / "phase1_radar.json"
    if not source.is_file():
        print("缺少 evidence/phase1_radar.json，请先运行 python src/run_phase1.py --all")
        return 2

    rows = json.loads(source.read_text(encoding="utf-8"))
    all_pages = [p for r in rows for p in r["pages"]]
    v1 = met.rank(met.dedupe(all_pages))
    v2, removed, near_miss, hits = nf.filter_rows(rows)
    v2 = met.rank(v2)
    m1, m2 = nf.top_metrics(v1), nf.top_metrics(v2)
    date_str = datetime.now().strftime("%Y-%m-%d")

    payload = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "source": "evidence/phase1_radar.json",
        "extra_api_calls": 0,
        "raw_items": len(all_pages),
        "v1": m1,
        "v2": m2,
        "delta": {
            "kept": m2["total"] - m1["total"],
            "top_trusted_share_pp": round(
                (m2["top_trusted_share"] - m1["top_trusted_share"]) * 100, 1),
            "top_avg_authority": round(
                m2["top_avg_authority"] - m1["top_avg_authority"], 3),
        },
        "filter_hits": hits,
        "removed_count": len(removed),
        "removed_sample": nf.removed_summary(removed, limit=20),
        "near_miss_count": len(near_miss),
        "near_miss": [
            {"title": str(i.get("title") or "")[:120], "host": i.get("_host"),
             "query": i.get("_query")}
            for i in near_miss
        ],
        "rules": [
            {"key": k, "label": nf.REASON_LABELS[k], "basis": b, "why": w}
            for k, b, w in nf.RULES
        ],
    }

    EVIDENCE.mkdir(parents=True, exist_ok=True)
    REPORTS.mkdir(parents=True, exist_ok=True)
    (EVIDENCE / "phase2_ab.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    (REPORTS / (date_str + "-clean.md")).write_text(
        build_clean_md(v2, removed, near_miss, hits, m1, m2, date_str),
        encoding="utf-8")
    (EVIDENCE / "phase2_report.html").write_text(
        build_html(v1, v2, removed, near_miss, hits, m1, m2, date_str),
        encoding="utf-8")

    print("Phase 2 完成（0 次 API 调用，全部复用 Phase 1 缓存）")
    print("  原始 %d 条 -> v1 保留 %d 条 -> v2 保留 %d 条（过滤 %d 条）"
          % (len(all_pages), m1["total"], m2["total"], len(removed)))
    print("  Top10 权威源占比：%.1f%% -> %.1f%% (%+.1f pp)"
          % (m1["top_trusted_share"] * 100, m2["top_trusted_share"] * 100,
             payload["delta"]["top_trusted_share_pp"]))
    print("  Top10 平均权威度：%.3f -> %.3f (%+.3f)"
          % (m1["top_avg_authority"], m2["top_avg_authority"],
             payload["delta"]["top_avg_authority"]))
    print("  规则命中：%s" % hits)
    print("  差点误伤（学术例外保留）：%d 条" % len(near_miss))
    print("产出：evidence/phase2_ab.json、phase2_report.html、reports/%s-clean.md"
          % date_str)
    return 0


if __name__ == "__main__":
    sys.exit(main())
