"""Phase 1 检索式配置：面向 Unity / WebGL + Android 跑酷游戏毕设的技术雷达。

4 个业务维度 × 2 路检索 = 8 路。每路写清 why，避免"随手拼关键词"。
改选题只改本文件，不需要动流水线代码。
"""

# 标准版支持 Cnt；若账号是极速版，run_phase1 会按档位自动裁掉不支持的参数
BASE_PARAMS = {"Cnt": 10}

DIMENSIONS = [
    {
        "key": "engine",
        "name": "引擎版本与兼容性",
        "why": "毕设锁定 Unity LTS，版本升级或平台支持变化会直接推翻既有构建配置",
        "queries": [
            {"q": "Unity 2022 LTS WebGL 平台 支持 变更", "params": {"Freshness": "m3"}},
            {"q": "Unity 版本 弃用 API 迁移 兼容性 说明", "params": {"Freshness": "y1"}},
        ],
    },
    {
        "key": "performance",
        "name": "双平台帧率与性能",
        "why": "验收硬指标是 WebGL + Android 双平台 >=30 FPS，需要可核查的优化依据",
        "queries": [
            {"q": "Unity WebGL 帧率 内存 优化 30 FPS", "params": {"Freshness": "y1"}},
            {"q": "Unity Android 性能优化 帧率 稳定 实践", "params": {}},
        ],
    },
    {
        "key": "gameplay",
        "name": "玩法与迷你游戏实现",
        "why": "跑酷主体 + 切水果 / 音游 / 石头剪刀布三种道具触发玩法，需查判定与输入方案",
        "queries": [
            {"q": "Unity 跑酷游戏 无尽生成 碰撞判定 实现", "params": {}},
            {"q": "Unity 音游 节奏判定 输入延迟 校准", "params": {}},
        ],
    },
    {
        "key": "data",
        "name": "评分统计与排行榜",
        "why": "要交付评分统计与 Top 100 排行榜，需确认数据结构与排序方案",
        "queries": [
            {"q": "游戏 排行榜 Top 100 数据结构 设计 Redis", "params": {}},
            {"q": "休闲游戏 评分 统计 指标 设计 学术", "params": {"Industry": "acad"}},
        ],
    },
]

# A/B 实测：固定同一条查询，每组只改一个参数
AB_QUERY = "Unity WebGL 帧率 内存 优化"
AB_VARIANTS = [
    {"label": "基线（仅 Query）", "params": {}},
    {"label": "Freshness=d30", "params": {"Freshness": "d30"}},
    {"label": "Freshness=m3", "params": {"Freshness": "m3"}},
    {"label": "Industry=acad", "params": {"Industry": "acad"}},
    {"label": "Industry=gov", "params": {"Industry": "gov"}},
    {"label": "Cnt=50", "params": {"Cnt": 50}},
    {"label": "Site=docs.unity3d.com", "params": {"Site": "docs.unity3d.com"}},
    {"label": "Mode=0 公开网页", "params": {"Mode": 0}},
    {"label": "Mode=1 权威垂直", "params": {"Mode": 1}},
    {"label": "Mode=2 混合", "params": {"Mode": 2}},
]

# 权威域名白名单：用于「权威源占比」这一可核验指标，规则透明、可在文中公开
TRUSTED_SUFFIXES = (
    "unity.com", "unity3d.com", "github.com", "microsoft.com",
    "android.com", "developer.android.com", "gov.cn", "edu.cn",
    "acm.org", "ieee.org", "arxiv.org", "cnki.net",
    "springer.com", "sciencedirect.com", "people.com.cn",
    "xinhuanet.com", "news.cn", "cac.gov.cn",
)

# 简报每个维度展示的条数
TOP_PER_DIMENSION = 4
