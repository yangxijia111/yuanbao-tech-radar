"""Phase 1 主程序：8 路检索 + 参数 A/B 实测 + 带来源与日期的简报。

用法（项目根目录执行）：
  python src/run_phase1.py --dry-run    # 只列出将要发起的调用，不联网、不耗额度
  python src/run_phase1.py --ab         # 只跑参数 A/B 实测
  python src/run_phase1.py --radar      # 只跑 8 路检索与简报
  python src/run_phase1.py --all        # 默认，两者都跑

产出：
  evidence/phase1_raw.json      全部真实调用的完整响应（逐条可核对）
  evidence/phase1_ab.json       A/B 各组量化指标
  evidence/phase1_radar.json    8 路检索结果
  evidence/phase1_report.html   可截图的总览证据页
  reports/<日期>.md             带来源与时间的资讯简报
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import radar_config as cfg  # noqa: E402
import radar_metrics as met  # noqa: E402
import wsa_client as wsa  # noqa: E402
from smoke import CSS, esc  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
EVIDENCE = ROOT / "evidence"
REPORTS = ROOT / "reports"
LITE_UNSUPPORTED = {"Mode", "Cnt", "Industry", "Deeplinks"}
CALL_GAP = 0.12


def detect_version():
    """复用 Phase 0 已探测到的档位，不额外消耗额度。"""
    path = EVIDENCE / "phase0_run.json"
    if path.is_file():
        try:
            rows = json.loads(path.read_text(encoding="utf-8"))
            return rows[0].get("version") if rows else None
        except (json.JSONDecodeError, IndexError, OSError):
            pass
    return None


def clip_params(params, version):
    if version == "lite":
        return {k: v for k, v in params.items() if k not in LITE_UNSUPPORTED}
    return dict(params)


def call(query, params, raw_sink):
    """一次真实调用；失败不中断流水线，如实记录错误码。"""
    try:
        res, raw = wsa.search(query, params=params)
    except wsa.WSAError as err:
        return {"ok": False, "error": str(err), "result": None}
    raw_sink.append({"query": query, "params": params, "response": raw})
    return {"ok": True, "error": None, "result": res}


def run_ab(raw_sink, version):
    rows = []
    print("\n[A/B] 固定查询：%s" % cfg.AB_QUERY)
    for item in cfg.AB_VARIANTS:
        params = clip_params(item["params"], version)
        outcome = call(cfg.AB_QUERY, params, raw_sink)
        if not outcome["ok"]:
            rows.append({"label": item["label"], "params": params,
                         "error": outcome["error"], "metrics": {}})
            print("  FAIL  %-26s %s" % (item["label"], outcome["error"]))
            time.sleep(CALL_GAP)
            continue
        res = outcome["result"]
        metrics = met.measure(res["pages"], res["latency_ms"])
        rows.append({
            "label": item["label"], "params": params, "error": None,
            "metrics": metrics, "request_id": res["request_id"],
            "version": res["version"],
            "raw_count": res["raw_count"], "bad_pages": res["bad_pages"],
        })
        print("  %-26s %2d 条 | date %2d/%2d | 权威 %.0f%% | score %s | %.0f ms"
              % (item["label"], metrics["count"], metrics["date_coverage"],
                 metrics["count"], metrics["trusted_share"] * 100,
                 metrics["score_avg"], metrics["latency_ms"]))
        time.sleep(CALL_GAP)
    return rows


def run_radar(raw_sink, version):
    rows, all_pages = [], []
    print("\n[Radar] 8 路检索")
    for dim in cfg.DIMENSIONS:
        for item in dim["queries"]:
            params = clip_params({**cfg.BASE_PARAMS, **item["params"]}, version)
            outcome = call(item["q"], params, raw_sink)
            if not outcome["ok"]:
                print("  FAIL  [%s] %s -> %s" % (dim["key"], item["q"], outcome["error"]))
                rows.append({"dimension": dim["name"], "key": dim["key"],
                             "why": dim["why"], "query": item["q"], "params": params,
                             "error": outcome["error"], "pages": [], "metrics": {}})
                time.sleep(CALL_GAP)
                continue
            res = outcome["result"]
            pages = res["pages"]
            all_pages.extend(pages)
            metrics = met.measure(pages, res["latency_ms"])
            rows.append({
                "dimension": dim["name"], "key": dim["key"], "why": dim["why"],
                "query": item["q"], "params": params, "error": None,
                "pages": pages, "metrics": metrics,
                "request_id": res["request_id"], "version": res["version"],
            })
            print("  [%s] %-42s %2d 条 | date %2d/%2d | 权威 %.0f%% | %.0f ms"
                  % (dim["key"], item["q"][:42], metrics["count"],
                     metrics["date_coverage"], metrics["count"],
                     metrics["trusted_share"] * 100, metrics["latency_ms"]))
            time.sleep(CALL_GAP)
    return rows, all_pages


def top_by_dimension(radar_rows):
    grouped = {}
    for row in radar_rows:
        pages = row.get("pages") or []
        for page in pages:
            page = dict(page)
            page["_dimension"] = row["key"]
            grouped.setdefault(row["key"], []).append(page)
    result = {}
    for key, pages in grouped.items():
        result[key] = met.rank(met.dedupe(pages))[:cfg.TOP_PER_DIMENSION]
    return result


def build_markdown(radar_rows, ab_rows, tops, date_str, version, total_calls):
    raw_total = sum((r.get("metrics") or {}).get("count", 0) for r in radar_rows)
    dedup_total = len(met.dedupe(
        [p for r in radar_rows for p in (r.get("pages") or [])]))
    lines = [
        "# Unity / WebGL 毕设技术雷达 · %s" % date_str,
        "",
        "> 本简报由 `src/run_phase1.py` 调用元宝搜索 SearchPro **真实生成**，条目未经手工增删。",
        "> 账号档位 `%s`；本次共 %d 次调用、%d 路检索、%d 条原始结果、去重后 %d 条。"
        % (version or "unknown", total_calls, len(radar_rows), raw_total, dedup_total),
        "> 每条保留原始链接、站点与发布时间，可逐条点开核对；无日期的条目如实标注。",
        "",
    ]
    for index, dim in enumerate(cfg.DIMENSIONS, 1):
        lines.append("## %d. %s" % (index, dim["name"]))
        lines.append("")
        lines.append("> 检索理由：%s" % dim["why"])
        lines.append("")
        pages = tops.get(dim["key"], [])
        if not pages:
            lines.append("_本次该维度未返回结果，见 evidence 中的原始响应。_")
            lines.append("")
            continue
        for i, page in enumerate(pages, 1):
            title = str(page.get("title") or page.get("url") or "无标题")
            url = str(page.get("url") or "")
            head = ("[%s](%s)" % (title, url)) if url.startswith("http") else title
            tag = "`权威源`" if page.get("_trusted") else ""
            lines.append("%d. **%s** %s · %s · %s · score %s · 综合 %s"
                         % (i, head, tag, esc(page.get("site") or "站点未标注"),
                            esc(page.get("date") or "无发布时间"),
                            esc(page.get("score") or "n/a"),
                            esc(page.get("_final") or "n/a")))
            summary = str(page.get("passage") or page.get("content") or "").strip()
            if summary:
                lines.append("   %s" % summary[:120].replace("\n", " "))
        lines.append("")

    lines.extend(["## 附一：本次检索式", "",
                  "| 维度 | 检索词 | 参数 | 返回条数 |", "|---|---|---|---|"])
    for row in radar_rows:
        lines.append("| %s | %s | `%s` | %s |"
                     % (esc(row["dimension"]), esc(row["query"]),
                        esc(json.dumps(row["params"], ensure_ascii=False)),
                        (row.get("metrics") or {}).get("count", 0)))
    lines.extend(["", "## 附二：参数 A/B 实测要点", ""])
    for note in met.ab_notes(ab_rows):
        lines.append("- %s" % note)
    lines.extend([
        "",
        "---",
        "证据文件：`evidence/phase1_raw.json`（完整响应）、`phase1_ab.json`、"
        "`phase1_radar.json`、`phase1_report.html`。",
        "版权归原站点所有，引用前请点开原文核对。",
        "",
    ])
    return "\n".join(lines)


def build_html(radar_rows, ab_rows, tops, notes, date_str, version, total_calls):
    parts = [
        "<!DOCTYPE html><html lang=\"zh-CN\"><head><meta charset=\"utf-8\">",
        "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">",
        "<title>Phase 1 · 8 路检索与参数 A/B 实测</title><style>", CSS,
        "</style></head><body><div class=\"wrap\">",
        "<h1>Phase 1 · 8 路检索与参数 A/B 实测</h1>",
        "<p class=\"sub\">全部数据来自本次真实调用，未经手工增删；完整响应见 "
        "<code>evidence/phase1_raw.json</code>，密钥已脱敏。</p>",
    ]
    chips = [
        ("生成时间", date_str + " " + datetime.now().strftime("%H:%M:%S")),
        ("账号档位", version or "unknown"),
        ("本次调用", "%d 次" % total_calls),
        ("检索路数", "%d 路" % len(radar_rows)),
        ("A/B 组数", "%d 组" % len(ab_rows)),
    ]
    parts.append("<div class=\"meta\">")
    for key, value in chips:
        parts.append("<span class=\"chip\">%s <b>%s</b></span>" % (esc(key), esc(value)))
    parts.append("</div>")

    parts.append("<h2>参数 A/B 实测（固定查询：%s）</h2>" % esc(cfg.AB_QUERY))
    parts.append("<div class=\"card\"><table><thead><tr>"
                 "<th>变体</th><th>条数</th><th>date 覆盖</th><th>权威源占比</th>"
                 "<th>近 30 天占有日期</th><th>score 均值</th><th>score 最大</th>"
                 "<th>耗时</th></tr></thead><tbody>")
    for row in ab_rows:
        m = row.get("metrics") or {}
        if row.get("error"):
            parts.append("<tr><td>%s</td><td colspan=\"7\">调用失败：%s</td></tr>"
                         % (esc(row["label"]), esc(row["error"])))
            continue
        fresh = m.get("fresh30_share_of_dated")
        parts.append(
            "<tr><td>%s</td><td>%s</td><td>%s/%s</td><td>%.1f%%</td>"
            "<td>%s</td><td>%s</td><td>%s</td><td>%.0f ms</td></tr>"
            % (esc(row["label"]), m.get("count", 0),
               m.get("date_coverage", 0), m.get("count", 0),
               (m.get("trusted_share") or 0) * 100,
               ("%.1f%%" % (fresh * 100)) if fresh is not None else "n/a",
               esc(m.get("score_avg")), esc(m.get("score_max")),
               m.get("latency_ms", 0))
        )
    parts.append("</tbody></table></div>")

    parts.append("<h2>从数据里直接读出的结论</h2><div class=\"card\"><ul>")
    for note in notes:
        parts.append("<li style=\"margin:6px 0;color:#c9d4de\">%s</li>" % esc(note))
    parts.append("</ul></div>")

    parts.append("<h2>8 路检索式与返回情况</h2><div class=\"card\"><table><thead><tr>"
                 "<th>维度</th><th>检索理由</th><th>检索词</th><th>参数</th>"
                 "<th>条数</th><th>耗时</th></tr></thead><tbody>")
    for row in radar_rows:
        m = row.get("metrics") or {}
        parts.append("<tr><td>%s</td><td>%s</td><td>%s</td><td><code>%s</code></td>"
                     "<td>%s</td><td>%.0f ms</td></tr>"
                     % (esc(row["dimension"]), esc(row["why"]), esc(row["query"]),
                        esc(json.dumps(row["params"], ensure_ascii=False)),
                        m.get("count", 0), m.get("latency_ms", 0)))
    parts.append("</tbody></table></div>")

    parts.append("<h2>简报 Top 结果（含来源与日期）</h2>")
    for dim in cfg.DIMENSIONS:
        pages = tops.get(dim["key"], [])
        parts.append("<div class=\"card\"><h2 style=\"margin-top:0\">%s</h2>"
                     % esc(dim["name"]))
        parts.append("<p class=\"sub\">%s</p>" % esc(dim["why"]))
        parts.append("<table><thead><tr><th style=\"width:34px\">#</th><th>标题</th>"
                     "<th style=\"width:120px\">站点</th><th style=\"width:150px\">发布时间</th>"
                     "<th style=\"width:80px\">score</th><th style=\"width:80px\">综合分</th>"
                     "</tr></thead><tbody>")
        for i, page in enumerate(pages, 1):
            title = str(page.get("title") or page.get("url") or "—")
            url = str(page.get("url") or "")
            link = ("<a href=\"%s\" target=\"_blank\" rel=\"noopener\">%s</a>"
                    % (esc(url), esc(title))) if url.startswith("http") else esc(title)
            if page.get("_trusted"):
                link = "<span style=\"color:#22d3ee\">[权威]</span> " + link
            summary = str(page.get("passage") or page.get("content") or "")[:100]
            parts.append(
                "<tr><td>%d</td><td>%s<div class=\"sum\">%s</div></td>"
                "<td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>"
                % (i, link, esc(summary), esc(page.get("site") or "—"),
                   esc(page.get("date") or "—"), esc(page.get("score") or "—"),
                   esc(page.get("_final") or "—"))
            )
        if not pages:
            parts.append("<tr><td colspan=\"6\">该维度本次无结果</td></tr>")
        parts.append("</tbody></table></div>")

    parts.append(
        "<div class=\"foot\">说明：权威源按公开的白名单域名判定，规则见 "
        "<code>src/radar_config.py</code>；综合分在同一次响应内对 score 做 "
        "min-max 归一化后按 0.6/0.25/0.15 加权，规则见 <code>src/radar_metrics.py</code>。"
        "所有数字均可用 <code>phase1_raw.json</code> 复算。</div>"
    )
    parts.append("</div></body></html>")
    return "".join(parts)


def main():
    parser = argparse.ArgumentParser(description="Phase 1 检索式与 A/B 实测")
    parser.add_argument("--ab", action="store_true")
    parser.add_argument("--radar", action="store_true")
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--render-only", action="store_true",
                        help="从已有 evidence 重新生成 HTML 与简报，不联网、不耗额度")
    args = parser.parse_args()
    if args.render_only:
        ab_rows, radar_rows, raw_sink = [], [], []
        for name, kind in (("phase1_ab.json", "ab"),
                           ("phase1_radar.json", "radar"),
                           ("phase1_raw.json", "raw")):
            path = EVIDENCE / name
            if not path.is_file():
                continue
            data = json.loads(path.read_text(encoding="utf-8"))
            if kind == "ab":
                ab_rows = data
            elif kind == "radar":
                radar_rows = data
            else:
                raw_sink = data
        version = detect_version()
        date_str = datetime.now().strftime("%Y-%m-%d")
        tops = top_by_dimension(radar_rows) if radar_rows else {}
        notes = met.ab_notes(ab_rows) if ab_rows else []
        EVIDENCE.mkdir(parents=True, exist_ok=True)
        REPORTS.mkdir(parents=True, exist_ok=True)
        (EVIDENCE / "phase1_report.html").write_text(
            build_html(radar_rows, ab_rows, tops, notes, date_str, version,
                       len(raw_sink)), encoding="utf-8")
        if radar_rows:
            (REPORTS / (date_str + ".md")).write_text(
                build_markdown(radar_rows, ab_rows, tops, date_str, version,
                               len(raw_sink)), encoding="utf-8")
        print("render-only：未发起任何调用，已重新生成报告，实测结论 %d 条。" % len(notes))
        for note in notes:
            print("  - " + note)
        return 0

    do_ab = args.dry_run or args.ab or args.all or not args.radar
    do_radar = args.dry_run or args.radar or args.all or not args.ab

    ab_count = len(cfg.AB_VARIANTS) if do_ab else 0
    radar_count = sum(len(d["queries"]) for d in cfg.DIMENSIONS) if do_radar else 0
    planned = ab_count + radar_count
    print("Phase 1 计划：A/B %d 组 + 雷达 %d 路 = %d 次调用"
          % (ab_count, radar_count, planned))
    if args.dry_run:
        if do_ab:
            for item in cfg.AB_VARIANTS:
                print("  [A/B] %-26s %s" % (item["label"], item["params"]))
        if do_radar:
            for dim in cfg.DIMENSIONS:
                for item in dim["queries"]:
                    print("  [Radar] %-12s %s %s"
                          % (dim["key"], item["q"], item["params"]))
        print("dry-run 结束：未联网、未消耗额度。")
        return 0

    wsa.load_dotenv(str(ROOT / ".env"))
    if not os.environ.get("TENCENTCLOUD_WSA_APIKEY"):
        print("缺少 TENCENTCLOUD_WSA_APIKEY，请先按 .env.example 配置。")
        return 2

    version = detect_version()
    print("账号档位：%s（来自 Phase 0 证据）" % (version or "unknown"))
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    REPORTS.mkdir(parents=True, exist_ok=True)

    raw_sink, ab_rows, radar_rows = [], [], []
    if do_ab:
        ab_rows = run_ab(raw_sink, version)
    if do_radar:
        radar_rows, _ = run_radar(raw_sink, version)

    date_str = datetime.now().strftime("%Y-%m-%d")
    tops = top_by_dimension(radar_rows) if radar_rows else {}
    notes = met.ab_notes(ab_rows) if ab_rows else []

    (EVIDENCE / "phase1_raw.json").write_text(
        json.dumps(raw_sink, ensure_ascii=False, indent=2), encoding="utf-8")
    if ab_rows:
        (EVIDENCE / "phase1_ab.json").write_text(
            json.dumps(ab_rows, ensure_ascii=False, indent=2), encoding="utf-8")
    if radar_rows:
        (EVIDENCE / "phase1_radar.json").write_text(
            json.dumps(radar_rows, ensure_ascii=False, indent=2), encoding="utf-8")
        (REPORTS / (date_str + ".md")).write_text(
            build_markdown(radar_rows, ab_rows, tops, date_str, version, len(raw_sink)),
            encoding="utf-8")
    (EVIDENCE / "phase1_report.html").write_text(
        build_html(radar_rows, ab_rows, tops, notes, date_str, version, len(raw_sink)),
        encoding="utf-8")

    print("\n实测结论：")
    for note in notes:
        print("  - " + note)
    print("\n产出：evidence/phase1_{raw,ab,radar}.json、phase1_report.html"
          + ("、reports/%s.md" % date_str if radar_rows else ""))
    print("实际调用 %d 次。" % len(raw_sink))
    return 0


if __name__ == "__main__":
    sys.exit(main())
