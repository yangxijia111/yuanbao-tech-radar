"""生成征文 5 张配图与「可直接发布」的排版文件。

开发辅助脚本，仅本脚本依赖 pillow / markdown；参赛代码本身仍是零第三方依赖。
  pip install pillow markdown
  python src/make_figures.py

流程：从 evidence/*.json 读真实数据 -> 渲染 5 张深色截图页 ->
Chrome 无头截图 -> 自动裁掉底部空白 -> 生成 csdn_final.md 与 preview.html。
"""

from __future__ import annotations

import base64
import json
import re
import subprocess
import sys
import tempfile
from datetime import datetime
from html import escape as esc
from pathlib import Path

import markdown
from PIL import Image, ImageChops

sys.path.insert(0, str(Path(__file__).resolve().parent))
import noise_filter as nf  # noqa: E402
import radar_config as cfg  # noqa: E402
import radar_metrics as met  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
EVIDENCE = ROOT / "evidence"
ARTICLES = ROOT / "articles"
IMAGES = ARTICLES / "images"
TMP = Path(tempfile.gettempdir()) / "yb_figures"
CHROME = Path("C:/Program Files/Google/Chrome/Application/chrome.exe")
WIDTH = 1200
SHOT_HEIGHT = 2600
BG = (11, 16, 22)

CAPTIONS = {
    1: "图 1　首次真实调用：两次 HTTP 200，账号档位 standard",
    2: "图 2　面向毕设四个信息需求的 8 路检索式及返回情况",
    3: "图 3　最终简报（过滤版）：每条保留原始链接、站点与发布时间",
    4: "图 4　固定查询下 10 组参数 A/B 实测结果",
    5: "图 5　噪声过滤前后对照、规则命中与差点误伤清单",
}
FILES = {
    1: "01-first-call.png", 2: "02-queries.png", 3: "03-brief.png",
    4: "04-ab.png", 5: "05-filter.png",
}

CSS = """
html,body{margin:0;padding:0;background:#0b1016;color:#e6edf3;
 font-family:"Microsoft YaHei","Segoe UI",sans-serif}
.sheet{box-sizing:border-box;width:1200px;padding:34px 40px 26px}
h1{font-size:27px;font-weight:500;color:#22d3ee;margin:0 0 6px}
h2{font-size:16px;font-weight:500;margin:24px 0 10px;color:#e6edf3}
.sub{font-size:13px;color:#8b98a5;margin:0 0 20px;line-height:1.7}
.ct{font-size:16px;color:#22d3ee;margin-bottom:8px}
.grid2{display:grid;grid-template-columns:1fr 1fr;gap:16px}
.grid4{display:grid;grid-template-columns:repeat(4,1fr);gap:12px}
.card{background:#111a23;border:1px solid #24313e;border-radius:10px;padding:15px 18px}
.metric{background:#0c151e;border-radius:8px;padding:12px 14px}
.metric .k{font-size:11px;color:#7d8b99}
.metric .v{font-size:22px;color:#e6edf3;margin-top:3px}
.metric .d{font-size:12px;color:#22d3ee}
.kv{font-size:12.5px;color:#aebbc8;line-height:1.85}
.kv b{color:#e6edf3;font-weight:500}
table{width:100%;border-collapse:collapse;font-size:12.5px}
th{text-align:left;color:#8b98a5;font-weight:500;border-bottom:1px solid #24313e;padding:9px 8px}
td{border-bottom:1px solid #1a2530;padding:9px 8px;color:#c9d4de;vertical-align:top}
table.fixed{table-layout:fixed;word-break:break-word}
table.mini{font-size:11.5px;margin-top:12px}
table.mini th,table.mini td{padding:6px 6px}
code{background:#0a1219;padding:1px 5px;border-radius:4px;color:#9fd8e8;font-size:11.5px}
.tag{display:inline-block;padding:1px 7px;border-radius:9px;font-size:11px;
 border:1px solid #1d5d6b;color:#22d3ee;margin-right:5px}
.tag.warn{color:#EF9F27;border-color:#6b5220}
ul{margin:8px 0;padding-left:20px;font-size:12.5px;color:#c9d4de;line-height:1.85}
.foot{margin-top:20px;padding-top:13px;border-top:1px solid #24313e;
 font-size:11.5px;color:#7d8b99;line-height:1.75}
"""

PREVIEW_CSS = """
body{background:#fff;color:#24292f;font:16px/1.8 "Microsoft YaHei","Segoe UI",sans-serif;
 max-width:900px;margin:0 auto;padding:36px 28px 80px}
h1{font-size:27px;line-height:1.45;border-bottom:1px solid #eaecef;padding-bottom:12px}
h2{font-size:21px;margin:34px 0 12px;border-bottom:1px solid #eaecef;padding-bottom:8px}
h3{font-size:18px;margin:26px 0 10px}
p{margin:12px 0}
blockquote{border-left:4px solid #22d3ee;background:#f5fbfd;margin:14px 0;
 padding:8px 16px;color:#57606a;font-size:14px}
table{border-collapse:collapse;width:100%;font-size:14px;margin:14px 0}
th,td{border:1px solid #dfe2e5;padding:8px 10px;text-align:left}
th{background:#f6f8fa}
pre{background:#f6f8fa;border-radius:6px;padding:14px;overflow:auto;font-size:13px}
code{background:#f6f8fa;border-radius:4px;padding:1px 5px;font-size:13px;color:#c7254e}
img{display:block;max-width:100%;height:auto;margin:18px auto 6px;
 border:1px solid #dfe2e5;border-radius:6px}
a{color:#0969da}
ul,ol{padding-left:24px}
hr{border:0;border-top:1px solid #eaecef;margin:30px 0}
"""


def page(title, subtitle, body):
    return ('<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8">'
            '<style>' + CSS + '</style></head><body><div class="sheet">'
            '<h1>' + esc(title) + '</h1><p class="sub">' + subtitle + '</p>'
            + body + '</div></body></html>')


def foot(text):
    return '<div class="foot">' + text + '</div>'


def cut(text, n):
    text = str(text if text not in (None, "") else "—")
    return esc(text[:n] + ("…" if len(text) > n else ""))


def fig1(rows):
    body = ['<div class="grid2">']
    for r in rows:
        f = r["fields"]
        body.append('<div class="card">')
        body.append('<div class="ct">%s</div>' % esc(r["query"]))
        body.append('<div class="kv">')
        body.append('请求 <code>POST %s</code><br>' % esc(r["endpoint"]))
        body.append('鉴权 <b>%s</b>（%s，已脱敏）　HTTP <b>%s</b><br>'
                    % (esc(r["auth"]), esc(r["credential"]), r["http_status"]))
        body.append('耗时 <b>%.1f ms</b>　账号档位 <b>%s</b><br>'
                    % (r["latency_ms"], esc(r["version"] or "n/a")))
        body.append('RequestId <code>%s</code><br>' % esc(r["request_id"]))
        body.append('Pages <b>%d / %d / %d</b>（原始 / 解析 / 脏数据）<br>'
                    % (r["raw_count"], r["parsed_count"], r["bad_pages"]))
        body.append('字段覆盖 title %d, url %d, date %d, content %d, score %d（共 %d 条）'
                    % (f["title"], f["url"], f["date"], f["content"], f["score"], f["_total"]))
        body.append('</div>')
        body.append('<table class="mini fixed"><colgroup><col style="width:22%">'
                    '<col style="width:44%"><col style="width:24%"><col style="width:10%">'
                    '</colgroup><tr><th>站点</th><th>标题</th>'
                    '<th>发布时间</th><th>score</th></tr>')
        for p in r["pages"][:3]:
            body.append('<tr><td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>'
                        % (cut(p.get("site"), 12), cut(p.get("title"), 30),
                           cut(p.get("date"), 10), cut(p.get("score"), 6)))
        body.append('</table></div>')
    body.append('</div>')
    body.append(foot('数据来源：<code>evidence/phase0_run.json</code> 与 '
                     '<code>phase0_raw.json</code>；完整响应逐条可核对，密钥已脱敏。'
                     '两次调用共消耗 2 次免费额度。'))
    return page('Phase 0 · 首次真实调用「搜索 → 结果」',
                '服务 API KEY 方式 · 元宝搜索 SearchPro · 2026-11-12 实测',
                ''.join(body))


def fmt_params(params):
    if not params:
        return "—"
    return " · ".join("%s=%s" % (k, v) for k, v in params.items())


def fig2(rows):
    body = ['<table class="fixed"><colgroup><col style="width:13%">'
            '<col style="width:22%"><col style="width:27%"><col style="width:17%">'
            '<col style="width:6%"><col style="width:8%"><col style="width:7%">'
            '</colgroup><tr><th>维度</th><th>检索理由</th><th>检索词</th>'
            '<th>参数</th><th>条数</th><th>date 覆盖</th><th>耗时</th></tr>']
    for r in rows:
        m = r["metrics"]
        body.append('<tr><td>%s</td><td>%s</td><td>%s</td><td><code>%s</code></td>'
                    '<td>%d</td><td>%d/%d</td><td>%.0f ms</td></tr>'
                    % (esc(r["dimension"]), cut(r["why"], 48), cut(r["query"], 44),
                       esc(fmt_params(r["params"])), m["count"], m["date_coverage"],
                       m["count"], m["latency_ms"]))
    body.append('</table>')
    body.append(foot('检索式与「为什么查它」写在 <code>src/radar_config.py</code>；'
                     '每路 10 条，共 80 条原始结果、41 个域名。'
                     '参数不是越多越好，必须与检索理由对得上。'))
    return page('Phase 1 · 面向毕设四个信息需求的 8 路检索式',
                '4 个业务维度 × 2 路检索 · 全部来自真实调用 · 数据源 evidence/phase1_radar.json',
                ''.join(body))


def fig3(radar_rows):
    v2, _, _, _ = nf.filter_rows(radar_rows)
    v2 = met.rank(v2)
    grouped = {}
    for item in v2:
        grouped.setdefault(item.get("_dimension"), []).append(item)
    body = []
    for dim in cfg.DIMENSIONS:
        pages = grouped.get(dim["key"], [])[:2]
        body.append('<h2>%s　<span class="sub" style="font-size:12px">%s</span></h2>'
                    % (esc(dim["name"]), esc(dim["why"])))
        body.append('<div class="card"><table><tr><th>标题</th><th>来源域名</th>'
                    '<th>站点</th><th>发布时间</th><th>score</th><th>综合分</th></tr>')
        for p in pages:
            tag = '<span class="tag">权威</span>' if p.get("_trusted") else ''
            body.append('<tr><td>%s%s</td><td>%s</td><td>%s</td><td>%s</td>'
                        '<td>%s</td><td>%s</td></tr>'
                        % (tag, cut(p.get("title"), 58),
                           cut(met.host_of(p.get("url", "")), 26),
                           cut(p.get("site"), 16), cut(p.get("date"), 10),
                           cut(p.get("score"), 6), cut(p.get("_final"), 6)))
        if not pages:
            body.append('<tr><td colspan="6">该维度无保留条目</td></tr>')
        body.append('</table></div>')
    body.append(foot('过滤版简报 <code>reports/2026-11-12-clean.md</code>，'
                     '每个维度展示综合分最高的 2 条；完整版共 16 条，'
                     '每条都保留可点击的原始链接、站点名与发布时间。'))
    return page('最终成果 · 带来源与时间的技术资料简报',
                '由 8 路真实检索结果去重、排序、噪声过滤后生成 · 条目未经手工增删',
                ''.join(body))


def fig4(ab_rows):
    body = ['<table><tr><th>变体</th><th>条数</th><th>date 覆盖</th>'
            '<th>权威源占比</th><th>近 30 天占有日期</th><th>score 均值</th><th>耗时</th></tr>']
    for r in ab_rows:
        m = r["metrics"]
        fresh = m.get("fresh30_share_of_dated")
        body.append('<tr><td>%s</td><td>%s</td><td>%s/%s</td><td>%.1f%%</td>'
                    '<td>%s</td><td>%s</td><td>%.0f ms</td></tr>'
                    % (esc(r["label"]), m.get("count", 0),
                       m.get("date_coverage", 0), m.get("count", 0),
                       (m.get("trusted_share") or 0) * 100,
                       ("%.1f%%" % (fresh * 100)) if fresh is not None else "n/a",
                       cut(m.get("score_avg"), 10), m.get("latency_ms", 0)))
    body.append('</table>')
    body.append('<h2>从数据里直接读出的结论</h2><ul>')
    for note in met.ab_notes(ab_rows)[:6]:
        body.append('<li>%s</li>' % esc(note))
    body.append('</ul>')
    body.append(foot('固定查询「%s」，每组只改一个参数，共 10 组、10 次调用；'
                     '所有指标由脚本从原始 Pages 复算，'
                     '见 <code>evidence/phase1_ab.json</code> 与 <code>phase1_raw.json</code>。'
                     % esc(cfg.AB_QUERY)))
    return page('Phase 1 · 10 组参数 A/B 实测',
                '验证 Freshness / Industry / Cnt / Site / Mode 是否真的生效，以及代价',
                ''.join(body))


def fig5(p2):
    m1, m2, d = p2["v1"], p2["v2"], p2["delta"]
    body = ['<div class="grid4">']
    for k, v, delta in (
        ("v1 保留", "%d 条" % m1["total"], ""),
        ("v2 保留", "%d 条" % m2["total"], "过滤 %d 条" % p2["removed_count"]),
        ("v1 Top10 权威", "%.1f%%" % (m1["top_trusted_share"] * 100), ""),
        ("v2 Top10 权威", "%.1f%%" % (m2["top_trusted_share"] * 100),
         "%+.1f pp" % d["top_trusted_share_pp"]),
    ):
        body.append('<div class="metric"><div class="k">%s</div><div class="v">%s</div>'
                    '<div class="d">%s</div></div>' % (k, v, delta))
    body.append('</div>')
    body.append('<h2>过滤规则与本次命中</h2><table><tr><th>规则</th>'
                '<th>判定依据</th><th>命中数</th></tr>')
    for rule in p2["rules"]:
        body.append('<tr><td>%s</td><td>%s</td><td>%d</td></tr>'
                    % (esc(rule["label"]), esc(rule["basis"]),
                       p2["filter_hits"].get(rule["key"], 0)))
    body.append('</table>')
    body.append('<h2>差点误伤 · 学术域名例外保留 %d 条</h2>' % p2["near_miss_count"])
    body.append('<div class="card"><table><tr><th>标题</th><th>域名</th>'
                '<th>来源检索式</th></tr>')
    for item in p2["near_miss"][:4]:
        body.append('<tr><td>%s</td><td>%s</td><td>%s</td></tr>'
                    % (cut(item["title"], 62), cut(item["host"], 24),
                       cut(item["query"], 30)))
    body.append('</table></div>')
    body.append(foot('取舍说明：+%.1f pp 主要来自「同域名限流」（命中 %d 条），'
                     '并非垃圾内容识别；它同时损失了 blog.csdn.net 上 18 条可能相关的文章。'
                     '规则需按实际效果持续维护。<br>'
                     '本次对照全程复用 Phase 1 缓存，'
                     '<b>额外 API 调用 0 次</b>，数据见 evidence/phase2_ab.json。'
                     % (d["top_trusted_share_pp"], p2["filter_hits"].get("domain_cap", 0))))
    return page('Phase 2 · 噪声过滤前后对照与误伤审计',
                'v1 纯归一化排序 vs v2 加噪声过滤 · 全部数字可复算',
                ''.join(body))


def capture(name, html_text, out_png):
    TMP.mkdir(parents=True, exist_ok=True)
    hp = TMP / (name + ".html")
    hp.write_text(html_text, encoding="utf-8")
    raw = TMP / (name + ".raw.png")
    url = "file:///" + str(hp).replace("\\", "/")
    cmd = [
        str(CHROME), "--headless=new", "--disable-gpu", "--hide-scrollbars",
        "--no-sandbox", "--no-first-run", "--disable-extensions",
        "--user-data-dir=" + str(TMP / ("profile-" + name)),
        "--screenshot=" + str(raw),
        "--window-size=%d,%d" % (WIDTH, SHOT_HEIGHT), url,
    ]
    proc = subprocess.run(cmd, capture_output=True, timeout=90)
    if not raw.is_file():
        raise RuntimeError("截图失败 %s: %s"
                           % (name, proc.stderr.decode(errors="replace")[-300:]))
    img = Image.open(raw).convert("RGB")
    bg = Image.new("RGB", img.size, BG)
    bbox = ImageChops.difference(img, bg).getbbox()
    bottom = min(img.height, (bbox[3] if bbox else img.height) + 36)
    if bbox and bbox[3] > SHOT_HEIGHT - 20:
        print("  WARN %s 内容可能超出截图高度" % name)
    final_h = max(bottom, 240)
    img.crop((0, 0, img.width, final_h)).save(out_png)
    return img.width, final_h


def build_final_md():
    source = (ARTICLES / "csdn_draft.md").read_text(encoding="utf-8")

    def repl(match):
        n = int(match.group(1))
        cap = CAPTIONS[n]
        return "![%s](images/%s)\n\n> %s" % (cap, FILES[n], cap)

    out, count = re.subn(r"^> 【配图 (\d)】.*$", repl, source, flags=re.M)
    if count != 5:
        raise RuntimeError("配图标记替换数量异常：%d（应为 5）" % count)
    (ARTICLES / "csdn_final.md").write_text(out, encoding="utf-8")
    return out


def build_preview(md_text):
    body_html = markdown.markdown(
        md_text, extensions=["tables", "fenced_code", "sane_lists"])

    def inline(match):
        path = IMAGES / Path(match.group(1)).name
        if path.is_file():
            data = base64.b64encode(path.read_bytes()).decode("ascii")
            return 'src="data:image/png;base64,%s"' % data
        return match.group(0)

    body_html = re.sub(r'src="images/([^"]+)"', inline, body_html)
    doc = ('<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8">'
           '<meta name="viewport" content="width=device-width,initial-scale=1">'
           '<title>CSDN 征文 · 发布预览</title><style>' + PREVIEW_CSS
           + '</style></head><body>' + body_html + '</body></html>')
    (ARTICLES / "preview.html").write_text(doc, encoding="utf-8")


def main():
    if not CHROME.is_file():
        print("未找到 Chrome，请修改 make_figures.py 里的 CHROME 路径。")
        return 2
    IMAGES.mkdir(parents=True, exist_ok=True)
    phase0 = json.loads((EVIDENCE / "phase0_run.json").read_text(encoding="utf-8"))
    radar = json.loads((EVIDENCE / "phase1_radar.json").read_text(encoding="utf-8"))
    ab = json.loads((EVIDENCE / "phase1_ab.json").read_text(encoding="utf-8"))
    p2 = json.loads((EVIDENCE / "phase2_ab.json").read_text(encoding="utf-8"))

    specs = [
        (1, fig1(phase0)), (2, fig2(radar)), (3, fig3(radar)),
        (4, fig4(ab)), (5, fig5(p2)),
    ]
    print("生成配图中（Chrome 无头截图 + 自动裁白边）")
    for n, text in specs:
        width, height = capture("fig%d" % n, text, IMAGES / FILES[n])
        size_kb = (IMAGES / FILES[n]).stat().st_size / 1024
        print("  图 %d  %-20s  %dx%d  %.0f KB" % (n, FILES[n], width, height, size_kb))

    md = build_final_md()
    build_preview(md)
    print("\n已生成：")
    print("  articles/images/*.png     5 张配图")
    print("  articles/csdn_final.md    图片已排好版的最终稿")
    print("  articles/preview.html     自包含预览（图片内嵌，可全选复制到编辑器）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
