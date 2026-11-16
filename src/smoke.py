"""Phase 0 冒烟：真实跑通一次「搜索 → 结果」，并留存可核验的运行证据。

用法（在项目根目录执行）：
  python src/smoke.py --self-test       # 离线自检：不联网、不消耗额度
  python src/smoke.py                   # 2 次真实调用 + 生成证据文件
  python src/smoke.py --once            # 只跑 1 次调用
  python src/smoke.py --query "Unity 2022 LTS WebGL 兼容性"
  python src/smoke.py --params '{"Cnt":10,"Freshness":"d30"}'

产出（evidence/，均可直接用于征文配图与复现核对）：
  phase0_raw.json      完整原始响应，逐条可核对
  phase0_run.json      脱敏后的运行指标与解析结果
  phase0_report.html   可截图的证据页，离线打开即可
"""

from __future__ import annotations

import argparse
import html
import json
import os
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import wsa_client as wsa  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
EVIDENCE = ROOT / "evidence"
ENV_PATH = ROOT / ".env"
OFFICIAL_QUERY = "三星堆的由来"
SCENE_QUERY = "Unity WebGL 构建 性能优化"

CONSOLE_STEPS = """\
Phase 0 控制台清单（需要你本人登录操作，我无法代做）：
  0. 腾讯云账号完成实名认证，且账户余额 >= 0 元
  1. 打开 https://console.cloud.tencent.com/wsapi/activity  进入「活动专区」
  2. 点【立即开通】-> 完成服务配置（个人账号只能选极速版 / 标准版，建议标准版）
  3. 开通成功后点【进入控制台】，等待 3-5 分钟分配资源
  4. 再次进入【活动专区】-> 点【参与活动】-> 填邀请码 4US3FK88 提交核销
     （额度 2000 -> 6000 次/自然月，只可核销 1 次，多个邀请码不叠加）
  5. 打开 https://console.cloud.tencent.com/wsapi/index?tab=apikey
     概览 > 服务 API KEY 方式 >【创建 API KEY】，明文只显示一次，立即复制
  6. 把 .env.example 复制为 .env，填入 TENCENTCLOUD_WSA_APIKEY
  7. 回来执行：python src/smoke.py
"""


def esc(value):
    return html.escape(str(value if value not in (None, "") else "—"), quote=True)


def console_precheck(auth):
    if auth == "apikey" and not os.getenv("TENCENTCLOUD_WSA_APIKEY"):
        print("未检测到 TENCENTCLOUD_WSA_APIKEY。\n")
        print(CONSOLE_STEPS)
        return False
    if auth == "signature" and not (
        os.getenv("TENCENTCLOUD_SECRET_ID") and os.getenv("TENCENTCLOUD_SECRET_KEY")
    ):
        print("signature 模式缺少 SecretId / SecretKey。\n")
        print(CONSOLE_STEPS)
        return False
    return True


def print_summary(index, total, res):
    print("\n[%d/%d] Query = %s" % (index, total, res["query"]))
    print("  endpoint   %s" % res["endpoint"])
    print("  auth       %s (%s)" % (res["auth"], res["credential"]))
    print("  HTTP %s   %.1f ms   RequestId=%s" % (
        res["http_status"], res["latency_ms"], res["request_id"] or "n/a"))
    print("  Version    %s   (账号实际档位，决定 Mode / Cnt / Industry 是否可用)" % (res["version"] or "n/a"))
    print("  Pages      %d raw / %d parsed / %d bad" % (
        res["raw_count"], res["parsed_count"], res["bad_pages"]))
    cov = res["fields"]
    total_items = max(cov["_total"], 1)
    present = ["%s %d/%d" % (k, cov[k], cov["_total"])
               for k in ("title", "url", "date", "passage", "content", "score")
               if cov[k]]
    print("  fields     " + ", ".join(present))
    for i, page in enumerate(res["pages"][:3], 1):
        title = str(page.get("title") or page.get("url") or "")
        print("    %d. [%s] %s  %s  score=%s" % (
            i, esc(page.get("site") or "?"), title[:46],
            esc(page.get("date") or "?"), esc(page.get("score") or "n/a")))
    if cov["_total"] == 0:
        print("  ! 返回 0 条：检查检索词、账号档位与服务是否已生效")


CSS = """
:root{color-scheme:dark}
*{box-sizing:border-box}
body{margin:0;padding:32px 28px 56px;background:#0b1016;color:#e6edf3;
 font:14px/1.65 -apple-system,BlinkMacSystemFont,"Segoe UI","Microsoft YaHei",sans-serif}
.wrap{max-width:1080px;margin:0 auto}
h1{font-size:22px;font-weight:500;margin:0 0 6px}
h2{font-size:16px;font-weight:500;margin:30px 0 12px;color:#22d3ee}
.sub{color:#8b98a5;font-size:13px;margin:0 0 22px}
.meta{display:flex;flex-wrap:wrap;gap:10px;margin-bottom:8px}
.chip{background:#131c26;border:1px solid #24313e;border-radius:8px;padding:7px 12px;font-size:12px;color:#aebbc8}
.chip b{color:#e6edf3;font-weight:500}
.card{background:#111a23;border:1px solid #24313e;border-radius:12px;padding:20px;margin:16px 0}
pre{background:#0a1219;border:1px solid #1e2b37;border-radius:8px;padding:12px 14px;
 overflow:auto;font:12px/1.6 Consolas,"Courier New",monospace;color:#9fd8e8;margin:0}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:12px;margin:16px 0}
.metric{background:#0c151e;border-radius:8px;padding:10px 12px}
.metric .k{font-size:11px;color:#7d8b99;letter-spacing:.04em}
.metric .v{font-size:17px;color:#e6edf3;margin-top:2px;word-break:break-all}
table{width:100%;border-collapse:collapse;font-size:12.5px}
th{text-align:left;color:#8b98a5;font-weight:500;border-bottom:1px solid #24313e;padding:9px 8px}
td{border-bottom:1px solid #1a2530;padding:9px 8px;vertical-align:top;color:#c9d4de}
td a{color:#22d3ee;text-decoration:none}
td a:hover{text-decoration:underline}
.sum{color:#7f8d9b;font-size:11.5px}
.bar{height:5px;background:#1b2733;border-radius:3px;overflow:hidden;margin-top:5px}
.bar i{display:block;height:100%;background:#22d3ee}
.foot{margin-top:34px;padding-top:16px;border-top:1px solid #24313e;color:#7d8b99;font-size:12px}
code{background:#0a1219;padding:1px 5px;border-radius:4px;color:#9fd8e8;font-size:12px}
"""


def build_report(runs):
    parts = [
        "<!DOCTYPE html><html lang=\"zh-CN\"><head><meta charset=\"utf-8\">",
        "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">",
        "<title>Phase 0 · 元宝搜索首次真实调用证据</title><style>", CSS,
        "</style></head><body><div class=\"wrap\">",
        "<h1>Phase 0 · 元宝搜索首次真实调用证据</h1>",
        "<p class=\"sub\">本页由 <code>src/smoke.py</code> 依据真实接口响应自动生成，"
        "结果条目未经手工增删；密钥已脱敏，原始响应见 <code>evidence/phase0_raw.json</code>。</p>",
    ]
    total_ms = round(sum(r["latency_ms"] for r in runs), 1)
    chips = [
        ("生成时间", datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
        ("鉴权方式", runs[0]["auth"] + " · " + runs[0]["credential"]),
        ("调用次数", str(len(runs))),
        ("总耗时", "%.1f ms" % total_ms),
        ("接口", "SearchPro / 2025-05-08"),
    ]
    parts.append("<div class=\"meta\">")
    for key, value in chips:
        parts.append("<span class=\"chip\">%s <b>%s</b></span>" % (esc(key), esc(value)))
    parts.append("</div>")

    for idx, res in enumerate(runs, 1):
        parts.append("<h2>调用 %d · %s</h2>" % (idx, esc(res["query"])))
        parts.append("<div class=\"card\">")
        request_body = {"Query": res["query"]}
        request_body.update(res["params"])
        parts.append("<pre>POST %s\nAuthorization: Bearer %s\nContent-Type: application/json; charset=utf-8\n\n%s</pre>"
                     % (esc(res["endpoint"]), esc(res["credential"]),
                        esc(json.dumps(request_body, ensure_ascii=False, indent=2))))
        metrics = [
            ("HTTP", str(res["http_status"])),
            ("耗时", "%.1f ms" % res["latency_ms"]),
            ("RequestId", res["request_id"] or "n/a"),
            ("账号版本", res["version"] or "n/a（API KEY 方式不返回）"),
            ("原始条数", str(res["raw_count"])),
            ("解析成功", str(res["parsed_count"])),
            ("脏数据", str(res["bad_pages"])),
        ]
        parts.append("<div class=\"grid\">")
        for key, value in metrics:
            parts.append("<div class=\"metric\"><div class=\"k\">%s</div><div class=\"v\">%s</div></div>"
                         % (esc(key), esc(value)))
        parts.append("</div>")

        cov = res["fields"]
        denom = max(cov["_total"], 1)
        parts.append("<p class=\"sub\" style=\"margin:8px 0 4px\">字段覆盖率（用于判断账号实际档位）</p>")
        for key in ("title", "url", "date", "passage", "content", "score",
                    "site", "favicon", "pics", "authority_level"):
            pct = round(cov[key] / denom * 100)
            parts.append(
                "<div style=\"font-size:12px;color:#aebbc8;margin-top:6px\">%s "
                "<span style=\"float:right\">%d/%d</span>"
                "<div class=\"bar\"><i style=\"width:%d%%\"></i></div></div>"
                % (esc(key), cov[key], cov["_total"], pct)
            )

        parts.append("<h2 style=\"margin-top:24px\">返回结果（含来源与时间）</h2>")
        parts.append("<table><thead><tr><th style=\"width:34px\">#</th><th>标题</th>"
                     "<th style=\"width:120px\">站点</th><th style=\"width:150px\">发布时间</th>"
                     "<th style=\"width:80px\">score</th></tr></thead><tbody>")
        for i, page in enumerate(res["pages"], 1):
            title = str(page.get("title") or page.get("url") or "—")
            url = str(page.get("url") or "")
            link = ("<a href=\"%s\" target=\"_blank\" rel=\"noopener\">%s</a>"
                    % (esc(url), esc(title))) if url.startswith("http") else esc(title)
            summary = str(page.get("passage") or page.get("content") or "")[:110]
            parts.append(
                "<tr><td>%d</td><td>%s<div class=\"sum\">%s</div></td>"
                "<td>%s</td><td>%s</td><td>%s</td></tr>"
                % (i, link, esc(summary), esc(page.get("site") or "—"),
                   esc(page.get("date") or "—"), esc(page.get("score") or "—"))
            )
        if not res["pages"]:
            parts.append("<tr><td colspan=\"5\">本次调用未返回结果条目</td></tr>")
        parts.append("</tbody></table></div>")

    parts.append(
        "<div class=\"foot\">证据说明：请求参数与响应摘要均由脚本从本次真实调用中读取；"
        "<code>phase0_raw.json</code> 保存未经修改的完整响应，"
        "<code>phase0_run.json</code> 保存解析后的指标。"
        "文中如需引用数据，请以这两个文件为准。</div>"
    )
    parts.append("</div></body></html>")
    return "".join(parts)


def main():
    parser = argparse.ArgumentParser(description="Phase 0 元宝搜索首次调用冒烟")
    parser.add_argument("--self-test", action="store_true", help="离线自检，不联网")
    parser.add_argument("--once", action="store_true", help="只发起 1 次调用")
    parser.add_argument("--query", default=SCENE_QUERY, help="第二条检索词")
    parser.add_argument("--auth", choices=["apikey", "signature"], default=None)
    parser.add_argument("--params", default=None, help="额外入参，JSON 字符串")
    args = parser.parse_args()

    if args.self_test:
        print("离线自检（不联网、不消耗额度）")
        for line in wsa.self_test():
            print("  PASS  " + line)
        print("全部通过。")
        return 0

    wsa.load_dotenv(str(ENV_PATH))
    auth = args.auth or os.getenv("WSA_AUTH", "apikey")
    if not console_precheck(auth):
        return 2

    params = None
    if args.params:
        try:
            params = json.loads(args.params)
        except json.JSONDecodeError as err:
            print("--params 不是合法 JSON：%s" % err)
            return 2

    queries = [OFFICIAL_QUERY] if args.once else [OFFICIAL_QUERY, args.query]
    print("Phase 0 冒烟：%s 模式，共 %d 次调用（每次消耗 1 次额度）" % (auth, len(queries)))

    runs, raws = [], []
    for i, query in enumerate(queries, 1):
        try:
            res, raw = wsa.search(query, params=params, auth=auth)
        except wsa.WSAError as err:
            print("\n调用失败：%s" % err)
            print("  code=%s  requestId=%s" % (err.code or "n/a", err.request_id or "n/a"))
            print("\n" + CONSOLE_STEPS)
            return 1
        runs.append(res)
        raws.append({
            "query": query,
            "request": {
                "endpoint": res["endpoint"],
                "auth_mode": res["auth"],
                "credential": res["credential"],
                "body": {"Query": query, **res["params"]},
            },
            "response": raw,
        })
        print_summary(i, len(queries), res)

    EVIDENCE.mkdir(parents=True, exist_ok=True)
    (EVIDENCE / "phase0_raw.json").write_text(
        json.dumps(raws, ensure_ascii=False, indent=2), encoding="utf-8")
    (EVIDENCE / "phase0_run.json").write_text(
        json.dumps(runs, ensure_ascii=False, indent=2), encoding="utf-8")
    (EVIDENCE / "phase0_report.html").write_text(
        build_report(runs), encoding="utf-8")

    print("\n证据已写入 evidence/：")
    print("  phase0_raw.json     完整原始响应")
    print("  phase0_run.json     脱敏运行指标")
    print("  phase0_report.html  打开后截图，作为征文「实际运行结果」配图")
    print("\n下一步：确认核销后的额度为 6000 次/月，然后进入 Phase 1 多路检索与 A/B 实测。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
