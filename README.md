# Yuanbao Tech Radar / 元宝搜索技术雷达

[中文](#中文) | [English](#english)

![Python](https://img.shields.io/badge/Python-3.9%2B-blue)
![Core dependencies](https://img.shields.io/badge/core%20deps-standard%20library-brightgreen)
![License](https://img.shields.io/badge/license-not%20specified-lightgrey)

## 中文

面向毕业设计资料调研的元宝搜索实践工具：把 Unity / WebGL + Android 跑酷游戏毕设中「查资料」这件事，做成一条可复现、可核验的流水线。

本项目是「元宝搜索开发者征文大赛」参赛作品。所有指标均来自对腾讯云元宝搜索 `SearchPro` 接口的真实调用；`evidence/` 保留原始响应，可逐条复算。配套征文：[《给毕设做一台技术雷达：8 路检索、10 组参数实测与一次噪声过滤复盘》](https://blog.csdn.net/2501_91391585/article/details/170859367)。

### 功能

- **零依赖客户端**：仅用 Python 标准库调用 `SearchPro`，支持服务 API KEY（`Bearer`）与腾讯云标准签名（手写 TC3-HMAC-SHA256）两种鉴权方式。
- **结构化结果处理**：`Pages` 是 JSON 字符串数组，逐条二次解析并对脏数据容错；`date` 兼容多种格式与缺失值；URL 归一化去重；传 `Industry` 导致 `score` 量纲漂移时，在同一次响应内做 min-max 归一化。
- **8 路检索式**：按毕设的四个真实信息需求（引擎版本、双平台性能、玩法实现、评分与排行榜）拆成 8 路，每路写明检索理由，参数逐维度分档。
- **10 组参数 A/B 实测**：固定同一查询，逐组只改一个参数（`Freshness` / `Industry` / `Cnt` / `Site` / `Mode`），记录条数、日期覆盖、权威源占比、score 均值与耗时。
- **噪声过滤对照**：5 条可解释规则（免费托管域名、垃圾特征词、摘要过短、查询词零命中、同域名限流），对学术域名设例外；保留被过滤条目与「差点误伤」清单，全部留痕可复核。
- **可核验产出**：带来源与发布时间的 Markdown 简报，以及可直接截图的 HTML 证据页。
- **离线自检与重渲染**：`--self-test` 不联网即可验证解析与签名逻辑；`--render-only` 从缓存重新生成报告，不消耗额度。

### 截图与证据

| 内容 | 文件 |
|---|---|
| 首次真实调用（`HTTP 200`、档位、耗时、RequestId） | [`01-first-call.png`](articles/images/01-first-call.png) |
| 8 路检索式与返回情况 | [`02-queries.png`](articles/images/02-queries.png) |
| 带来源与日期的资料简报 | [`03-brief.png`](articles/images/03-brief.png) |
| 10 组参数 A/B 实测 | [`04-ab.png`](articles/images/04-ab.png) |
| 噪声过滤前后对照与误伤审计 | [`05-filter.png`](articles/images/05-filter.png) |

完整的交互式证据页：[Phase 0](evidence/phase0_report.html) · [Phase 1](evidence/phase1_report.html) · [Phase 2](evidence/phase2_report.html)。

### 环境要求

- Python 3.9+（核心脚本**不需要任何第三方包**，只用标准库）
- 一个已完成实名认证的腾讯云账号，并开通[元宝搜索](https://console.cloud.tencent.com/wsapi/index)服务（个人账号可选极速版或标准版；`Mode` / `Cnt` / `Industry` 需标准版）
- 一把服务 API KEY，或（可选）SecretId / SecretKey
- 可选：活动期内凭渠道邀请码在[活动专区](https://console.cloud.tencent.com/wsapi/activity)核销免费额度；非必需，不影响代码运行
- **仅出图脚本** `src/make_figures.py` 额外需要 `pip install pillow markdown` 与本机 Chrome

### 安装与配置

```bash
git clone <仓库地址>
cd yuanbao-tech-radar
cp .env.example .env
```

编辑 `.env`，二选一：

```bash
# 方式一：服务 API KEY（推荐）
WSA_AUTH=apikey
TENCENTCLOUD_WSA_APIKEY=你的服务密钥

# 方式二：腾讯云标准签名
WSA_AUTH=signature
TENCENTCLOUD_SECRET_ID=你的 SecretId
TENCENTCLOUD_SECRET_KEY=你的 SecretKey
```

`.env` 已在 `.gitignore` 中排除。密钥创建时只显示一次明文，请妥善保存；若曾泄露，请到控制台吊销重建。

### 使用

在项目根目录执行：

```bash
python src/smoke.py --self-test       # 离线自检，不联网、不消耗额度
python src/smoke.py                   # Phase 0：2 次真实调用，生成首次运行证据
python src/run_phase1.py --dry-run    # 只列出 18 次调用计划，不联网
python src/run_phase1.py --all        # Phase 1：8 路检索 + 10 组 A/B（18 次额度）
python src/run_phase2.py              # Phase 2：噪声过滤对照（0 次额度，复用缓存）
python src/run_phase1.py --render-only  # 从缓存重渲染报告，0 次额度
```

其他可用参数：`python src/smoke.py --once`（只跑 1 次）、`--query "..."`（自定义检索词）、`--params '{"Cnt":10,"Freshness":"d30"}'`（附加接口参数）、`--auth signature`（切换鉴权方式）。检索式与业务维度集中在 `src/radar_config.py`，改选题不需要动流水线代码。

### 项目结构

```text
yuanbao-tech-radar/
├── src/
│   ├── wsa_client.py      # 零依赖 SearchPro 客户端：两种鉴权、Pages 解析、错误码提示
│   ├── smoke.py           # Phase 0 冒烟与证据生成
│   ├── radar_config.py    # 8 路检索式、A/B 变体、权威域名白名单
│   ├── radar_metrics.py   # 日期容错、URL 归一化、指标统计、组内归一化排序
│   ├── run_phase1.py      # 8 路检索 + 10 组 A/B + 简报生成
│   ├── noise_filter.py    # 5 条噪声过滤规则与误伤审计
│   ├── run_phase2.py      # 过滤前后对照与证据页
│   └── make_figures.py    # 开发辅助：生成 5 张配图与发布预览（需 pillow/markdown/Chrome）
├── evidence/              # 真实调用的原始响应、量化指标与 HTML 证据页
├── reports/               # 带来源与时间的 Markdown 简报
├── articles/              # 征文原稿、最终稿、配图与自包含发布预览
├── .env.example           # 配置模板（无真实密钥）
└── requirements.txt       # 说明核心脚本无第三方依赖
```

### 工作方式

1. **调用层** `wsa_client.py` 统一处理两种鉴权，把响应里的 `Pages` 字符串数组解析成对象，并把错误码翻译成中文提示。
2. **指标层** `radar_metrics.py` 从原始响应复算条数、日期覆盖率、权威源占比、score 均值与耗时；排序在**同一次响应内**做 min-max 归一化，避免 `Industry` 组因量纲不同整体霸榜。
3. **实验层** Phase 1 用固定查询逐组改单参数验证参数是否生效；Phase 2 完全复用 Phase 1 缓存做过滤前后对照，**不新增任何 API 调用**。
4. **证据层** 每一次调用都保留完整原始响应与 RequestId，所有报告由脚本生成，不做手工增删。

### 构建、运行与部署

本项目是本地 CLI 工具，没有传统意义上的构建步骤或云端部署。按「使用」一节运行脚本即可；报告与简报写入本地 `evidence/` 与 `reports/`。若需重新生成征文配图：

```bash
pip install pillow markdown
python src/make_figures.py
```

该脚本调用本机 Chrome 无头模式截图，不是核心流水线的一部分。

### 许可证

**当前未指定开源许可证**，仓库中的代码、证据与文章默认保留所有权利，请勿直接用于商业用途。建议采用 MIT License（宽松、适合参赛作品分享与复现），但需作者明确确认后才会添加 `LICENSE` 文件。

### 贡献

欢迎提交 Issue 指出事实错误、规则误伤案例或复现问题。涉及检索式与噪声规则的改动，请附上可核验的指标对照。

### 路线图

- 将 8 路检索挂到定时任务，只推送与前一日 diff 出的新条目
- 把 `passage` 交给大模型做「这条是否需要调整构建配置」的研判，而不只是堆链接
- `Site` 改为给每个维度配一条锚定官方站的补充查询
- 噪声规则从人工维护改成按「同域名连续 N 次被过滤」自动沉淀

### 致谢

- [腾讯云元宝搜索](https://cloud.tencent.com/product/wsa)提供检索能力
- [元宝搜索开发者征文大赛](https://builderx.csdn.net/activity-site/yuanbao/index)提供活动与额度支持
- 官方[接口文档](https://cloud.tencent.com/document/api/1806/121811)与[接入指引](https://cloud.tencent.com/document/product/1806/130615)

---

## English

A practical Yuanbao Search pipeline that turns "looking things up" for a Unity / WebGL + Android graduation project into a reproducible, verifiable workflow.

This repository is a submission for the **Yuanbao Search Developer Writing Contest**. Every metric comes from real calls to the Tencent Cloud `SearchPro` API; raw responses are kept in `evidence/` so each number can be recomputed. Companion article (Chinese): [Building a tech radar for my graduation project](https://blog.csdn.net/2501_91391585/article/details/170859367).

### Features

- **Zero-dependency client**: Python standard library only. Supports service API KEY (`Bearer`) and Tencent Cloud standard signing (hand-written TC3-HMAC-SHA256).
- **Structured result handling**: `Pages` is an array of JSON strings, parsed item by item with tolerance for malformed data. `date` parsing accepts multiple formats and missing values. URLs are normalized before deduplication. When `Industry` pushes `score` outside the documented 0–1 range, min-max normalization is applied within the same response.
- **Eight queries**: four real information needs (engine versions, dual-platform performance, gameplay implementation, scoring and leaderboards), each with a stated reason and per-dimension parameter settings.
- **Ten parameter A/B groups**: one query, one changed parameter per group (`Freshness` / `Industry` / `Cnt` / `Site` / `Mode`), recording result counts, date coverage, trusted-source share, average score and latency.
- **Noise-filter ablation**: five explainable rules (free hosting, junk keywords, short summaries, zero query-term hits, per-domain cap), with an academic-domain exception. Filtered items and near-miss cases are all recorded for human review.
- **Verifiable output**: a Markdown brief with sources and timestamps, plus HTML evidence pages ready for screenshots.
- **Offline self-test and re-render**: `--self-test` checks parsing and signing without network; `--render-only` regenerates reports from cache with zero API cost.

### Screenshots and evidence

| Item | File |
|---|---|
| First real call (`HTTP 200`, tier, latency, RequestId) | [`01-first-call.png`](articles/images/01-first-call.png) |
| Eight queries and their results | [`02-queries.png`](articles/images/02-queries.png) |
| Brief with sources and dates | [`03-brief.png`](articles/images/03-brief.png) |
| Ten-group parameter A/B test | [`04-ab.png`](articles/images/04-ab.png) |
| Noise-filter comparison and false-positive audit | [`05-filter.png`](articles/images/05-filter.png) |

Full HTML evidence pages: [Phase 0](evidence/phase0_report.html) · [Phase 1](evidence/phase1_report.html) · [Phase 2](evidence/phase2_report.html).

### Requirements

- Python 3.9+ — core scripts need **no third-party packages**, only the standard library
- A verified Tencent Cloud account with [Yuanbao Search](https://console.cloud.tencent.com/wsapi/index) enabled (personal accounts: Lite or Standard; `Mode` / `Cnt` / `Industry` require Standard)
- A service API KEY, or optionally SecretId / SecretKey
- Optional: an activity invitation code redeemed at the [activity page](https://console.cloud.tencent.com/wsapi/activity) for free quota; not required to run the code
- **Figure script only** `src/make_figures.py` additionally needs `pip install pillow markdown` and a local Chrome installation

### Installation and configuration

```bash
git clone <repository-url>
cd yuanbao-tech-radar
cp .env.example .env
```

Edit `.env` and choose one option:

```bash
# Option 1: service API KEY (recommended)
WSA_AUTH=apikey
TENCENTCLOUD_WSA_APIKEY=your-api-key

# Option 2: Tencent Cloud standard signing
WSA_AUTH=signature
TENCENTCLOUD_SECRET_ID=your-secret-id
TENCENTCLOUD_SECRET_KEY=your-secret-key
```

`.env` is excluded by `.gitignore`. The secret is shown in plain text only once at creation; store it safely and rotate it if exposed.

### Usage

Run from the project root:

```bash
python src/smoke.py --self-test       # offline checks, no network or quota
python src/smoke.py                   # Phase 0: 2 real calls with evidence
python src/run_phase1.py --dry-run    # list the 18 planned calls, no network
python src/run_phase1.py --all        # Phase 1: 8 queries + 10 A/B groups (18 calls)
python src/run_phase2.py              # Phase 2: filter ablation (0 calls, cached data)
python src/run_phase1.py --render-only  # re-render reports from cache, 0 calls
```

Other flags: `python src/smoke.py --once` (one call), `--query "..."`, `--params '{"Cnt":10,"Freshness":"d30"}'`, and `--auth signature`. Queries and dimensions live in `src/radar_config.py`, so changing the topic does not require touching the pipeline.

### Project structure

```text
yuanbao-tech-radar/
├── src/
│   ├── wsa_client.py      # zero-dependency SearchPro client: auth, Pages parsing, errors
│   ├── smoke.py           # Phase 0 smoke test and evidence generation
│   ├── radar_config.py    # 8 queries, A/B variants, trusted-domain whitelist
│   ├── radar_metrics.py   # date tolerance, URL normalization, metrics, normalized ranking
│   ├── run_phase1.py      # queries + A/B test + brief generation
│   ├── noise_filter.py    # five filtering rules and false-positive audit
│   ├── run_phase2.py      # before/after comparison and evidence page
│   └── make_figures.py    # dev helper: figures and publish preview (pillow/markdown/Chrome)
├── evidence/              # raw responses, metrics and HTML evidence pages
├── reports/               # Markdown briefs with sources and timestamps
├── articles/              # article draft, final version, figures and self-contained preview
├── .env.example           # configuration template without real secrets
└── requirements.txt       # documents that core scripts have no third-party dependencies
```

### How it works

1. **Client** `wsa_client.py` handles both auth modes, parses the JSON-string `Pages` array, and translates error codes.
2. **Metrics** `radar_metrics.py` recomputes counts, date coverage, trusted-source share, average score and latency from raw responses. Ranking is min-max normalized **within each response** so `Industry` groups cannot dominate purely due to scale.
3. **Experiments** Phase 1 changes one parameter at a time with a fixed query. Phase 2 reuses Phase 1's cache entirely — **no additional API calls**.
4. **Evidence** every call keeps its full raw response and RequestId; all reports are script-generated without manual edits.

### Build, run and deploy

This is a local CLI tool. There is no conventional build step or cloud deployment — just run the scripts listed above. Reports are written to local `evidence/` and `reports/`. To regenerate the article figures:

```bash
pip install pillow markdown
python src/make_figures.py
```

That helper uses headless Chrome and is not part of the core pipeline.

### License

**No open-source license is currently specified.** Code, evidence and articles are all rights reserved by default; please do not reuse them commercially. MIT License is suggested (permissive and suitable for a contest submission), but a `LICENSE` file will only be added after explicit author confirmation.

### Contributing

Issues about factual errors, false-positive filter cases or reproduction problems are welcome. Changes to queries or filtering rules should include verifiable metric comparisons.

### Roadmap

- Schedule the eight queries as a daily job and push only entries diffed against the previous day
- Feed `passage` to an LLM for "does this require a build-configuration change?" judgments instead of piling up links
- Turn `Site` into one official-site anchor query per dimension
- Evolve noise rules from a hand-maintained list into automatic accumulation based on repeated per-domain filtering

### Acknowledgements

- [Tencent Yuanbao Search](https://cloud.tencent.com/product/wsa) for the search capability
- [Yuanbao Search Developer Writing Contest](https://builderx.csdn.net/activity-site/yuanbao/index) for the event and free quota
- Official [API reference](https://cloud.tencent.com/document/api/1806/121811) and [integration guide](https://cloud.tencent.com/document/product/1806/130615)
