"""元宝搜索 (Tencent Yuanbao Search / wsa) 零依赖客户端。

只使用 Python 标准库，支持两种官方鉴权方式：
  apikey    : POST https://api.wsa.cloud.tencent.com/SearchPro
              Authorization: Bearer <TENCENTCLOUD_WSA_APIKEY>
              官方文档 https://cloud.tencent.com/document/product/1806/130615
  signature : POST https://wsa.tencentcloudapi.com/  (TC3-HMAC-SHA256)
              官方文档 https://cloud.tencent.com/document/product/1806/121802

注意：响应里的 Pages 是「JSON 字符串数组」而非对象数组，本模块统一二次解析。
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

APIKEY_URL = "https://api.wsa.cloud.tencent.com/SearchPro"
SIGN_URL = "https://wsa.tencentcloudapi.com/"
ACTION = "SearchPro"
VERSION = "2025-05-08"
SERVICE = "wsa"
TIMEOUT = 30

TRACKED_FIELDS = (
    "title", "url", "date", "passage", "content", "site",
    "score", "favicon", "pics", "authority_level", "deeplinks",
)

ERROR_HINTS = {
    "UnauthorizedOperation": "鉴权失败：检查 API KEY / SecretKey 是否正确，子账号需主账号授权",
    "ResourceNotFound": "服务未开通或尚未生效：开通后需等待 3-5 分钟再试",
    "ResourceUnavailable": "服务不可用：检查腾讯云账户是否欠费",
    "RequestLimitExceeded": "超过频率限制：降低并发或稍后重试",
    "InvalidParameter": "参数不合法：极速版不支持 Mode / Cnt / Industry",
    "AuthFailure.SignatureFailure": "签名错误：检查本机时间与标准时间误差是否小于 5 分钟",
    "AuthFailure.SignatureExpire": "签名过期：校准本机时间",
    "InternalError": "服务端内部错误：可退避重试",
}


class WSAError(Exception):
    def __init__(self, message, code=None, request_id=None):
        super().__init__(message)
        self.code = code
        self.request_id = request_id


def load_dotenv(path=".env"):
    """极简 .env 读取；已存在的环境变量优先，不覆盖。"""
    if not os.path.isfile(path):
        return {}
    values = {}
    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            values[key] = value
            os.environ.setdefault(key, value)
    return values


def mask(secret):
    """脱敏：只留首尾各 4 位，供日志与报告展示。"""
    if not secret:
        return "<empty>"
    if len(secret) <= 8:
        return secret[:2] + "***"
    return secret[:4] + "***" + secret[-4:]


def parse_pages(raw_pages):
    """把 Pages（JSON 字符串数组）解析为 dict 列表，并容错脏数据。

    Returns: (pages, bad_count)
    """
    pages, bad = [], 0
    for item in raw_pages or []:
        if isinstance(item, dict):
            pages.append(item)
            continue
        try:
            obj = json.loads(item)
            if isinstance(obj, dict):
                pages.append(obj)
            else:
                bad += 1
        except (json.JSONDecodeError, TypeError, ValueError):
            bad += 1
    return pages, bad


def field_coverage(pages):
    """统计每个字段的返回条数，用于判断账号实际档位。"""
    total = len(pages)
    out = {}
    for key in TRACKED_FIELDS:
        out[key] = sum(
            1 for p in pages
            if p.get(key) not in (None, "", [], {})
        )
    out["_total"] = total
    return out


def _post(url, payload, headers):
    req = urllib.request.Request(
        url, data=payload.encode("utf-8"), headers=headers, method="POST"
    )
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            status = resp.status
    except urllib.error.HTTPError as err:
        body = err.read().decode("utf-8", errors="replace")
        status = err.code
    except urllib.error.URLError as err:
        raise WSAError("网络请求失败：%s" % err.reason) from err
    latency_ms = round((time.perf_counter() - started) * 1000, 1)
    try:
        data = json.loads(body)
    except json.JSONDecodeError:
        raise WSAError("响应不是合法 JSON (HTTP %s)：%s" % (status, body[:300]))
    response = data.get("Response", data)
    if isinstance(response, dict) and "Error" in response:
        err = response["Error"]
        code = err.get("Code", "Unknown")
        hint = ERROR_HINTS.get(code, err.get("Message", "未知错误"))
        raise WSAError(
            "[%s] %s" % (code, hint),
            code=code,
            request_id=response.get("RequestId"),
        )
    return data, status, latency_ms


def _tc3_authorization(secret_id, secret_key, payload, timestamp=None):
    """腾讯云 API 3.0 TC3-HMAC-SHA256 签名（标准库手写）。"""
    ts = int(timestamp if timestamp is not None else time.time())
    date = datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%d")
    host = "wsa.tencentcloudapi.com"
    content_type = "application/json; charset=utf-8"
    canonical_headers = "content-type:%s\nhost:%s\n" % (content_type, host)
    signed_headers = "content-type;host"
    hashed_payload = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    canonical_request = "\n".join([
        "POST", "/", "", canonical_headers, signed_headers, hashed_payload,
    ])
    scope = "%s/%s/tc3_request" % (date, SERVICE)
    string_to_sign = "\n".join([
        "TC3-HMAC-SHA256", str(ts), scope,
        hashlib.sha256(canonical_request.encode("utf-8")).hexdigest(),
    ])

    def _hmac(key, msg):
        return hmac.new(key, msg.encode("utf-8"), hashlib.sha256).digest()

    k_date = _hmac(("TC3" + secret_key).encode("utf-8"), date)
    k_service = _hmac(k_date, SERVICE)
    k_signing = _hmac(k_service, "tc3_request")
    signature = hmac.new(
        k_signing, string_to_sign.encode("utf-8"), hashlib.sha256
    ).hexdigest()
    authorization = (
        "TC3-HMAC-SHA256 Credential=%s/%s, SignedHeaders=%s, Signature=%s"
        % (secret_id, scope, signed_headers, signature)
    )
    return {
        "Authorization": authorization,
        "Content-Type": content_type,
        "Host": host,
        "X-TC-Action": ACTION,
        "X-TC-Timestamp": str(ts),
        "X-TC-Version": VERSION,
    }


def search(query, params=None, auth=None, api_key=None,
           secret_id=None, secret_key=None):
    """发起一次 SearchPro 调用。

    Args:
        query: 必填检索词。
        params: 可选参数 dict，如 {"Cnt": 10, "Freshness": "d7"}。
        auth: "apikey" | "signature"，默认取环境变量 WSA_AUTH。
    Returns:
        (result, raw_response)。result 含脱敏元信息、解析后结果与字段覆盖率。
    """
    auth = auth or os.getenv("WSA_AUTH", "apikey")
    body = {"Query": query}
    if params:
        body.update(params)
    payload = json.dumps(body, ensure_ascii=False, separators=(",", ":"))

    if auth == "apikey":
        key = api_key or os.getenv("TENCENTCLOUD_WSA_APIKEY")
        if not key:
            raise WSAError(
                "缺少 TENCENTCLOUD_WSA_APIKEY：请在控制台创建服务 API KEY 并写入 .env"
            )
        url = APIKEY_URL
        headers = {
            "Authorization": "Bearer " + key,
            "Content-Type": "application/json; charset=utf-8",
        }
        credential_label = mask(key)
    elif auth == "signature":
        sid = secret_id or os.getenv("TENCENTCLOUD_SECRET_ID")
        skey = secret_key or os.getenv("TENCENTCLOUD_SECRET_KEY")
        if not sid or not skey:
            raise WSAError(
                "缺少 TENCENTCLOUD_SECRET_ID / TENCENTCLOUD_SECRET_KEY"
            )
        url = SIGN_URL
        headers = _tc3_authorization(sid, skey, payload)
        credential_label = mask(sid)
    else:
        raise WSAError("未知鉴权方式 %r，应为 apikey 或 signature" % auth)

    raw, status, latency_ms = _post(url, payload, headers)
    response = raw.get("Response", raw)
    raw_pages = response.get("Pages") or []
    pages, bad = parse_pages(raw_pages)

    result = {
        "ok": True,
        "query": query,
        "params": {k: v for k, v in body.items() if k != "Query"},
        "auth": auth,
        "credential": credential_label,
        "endpoint": url,
        "http_status": status,
        "latency_ms": latency_ms,
        "request_id": response.get("RequestId"),
        "version": response.get("Version"),
        "msg": response.get("Msg"),
        "raw_count": len(raw_pages),
        "parsed_count": len(pages),
        "bad_pages": bad,
        "fields": field_coverage(pages),
        "pages": pages,
    }
    return result, raw


def self_test():
    """离线自检：不联网、不消耗额度，验证解析与签名逻辑。"""
    sample = [
        '{"title":"t","url":"https://example.com","date":"2026-11-12","score":0.9}',
        "not-json",
        '{"broken":',
    ]
    pages, bad = parse_pages(sample)
    assert len(pages) == 1 and bad == 2, "parse_pages 容错逻辑异常"
    assert pages[0]["score"] == 0.9, "二次解析结果异常"
    coverage = field_coverage(pages)
    assert coverage["score"] == 1 and coverage["content"] == 0, "字段统计异常"

    headers = _tc3_authorization(
        "TESTID", "TESTKEY", '{"Query":"x"}', timestamp=1762930000
    )
    assert headers["Authorization"].startswith(
        "TC3-HMAC-SHA256 Credential=TESTID/"
    ), "TC3 凭证串格式异常"
    assert len(headers["Authorization"].split("Signature=")[-1]) == 64, "签名长度异常"
    assert headers["X-TC-Action"] == ACTION and headers["X-TC-Version"] == VERSION
    return [
        "parse_pages: JSON 字符串数组二次解析 + 脏数据容错",
        "field_coverage: 档位字段覆盖率统计",
        "TC3-HMAC-SHA256: 规范化请求 / 派生密钥 / 64 位签名",
    ]
