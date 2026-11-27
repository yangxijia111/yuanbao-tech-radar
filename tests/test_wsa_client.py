"""SearchPro 客户端的离线回归测试。"""

import io
import json
import sys
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import wsa_client as wsa


class FakeResponse:
    def __init__(self, body, status=200):
        self.body = body
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False

    def read(self):
        return self.body


class PostResponseTests(unittest.TestCase):
    def call_post(self, body, status=200):
        encoded = body if isinstance(body, bytes) else json.dumps(body).encode("utf-8")
        with patch(
            "wsa_client.urllib.request.urlopen",
            return_value=FakeResponse(encoded, status),
        ):
            return wsa._post(wsa.APIKEY_URL, "{}", {})

    def test_valid_search_response_is_preserved(self):
        body = {"Response": {
            "Pages": ['{"title":"示例","url":"https://example.com"}'],
            "RequestId": "request-1",
        }}
        with patch(
            "wsa_client.urllib.request.urlopen",
            return_value=FakeResponse(json.dumps(body).encode("utf-8")),
        ):
            result, raw = wsa.search("测试查询", api_key="test-key")

        self.assertTrue(result["ok"])
        self.assertEqual(result["http_status"], 200)
        self.assertEqual(result["request_id"], "request-1")
        self.assertEqual(result["pages"][0]["title"], "示例")
        self.assertEqual(raw, body)

    def test_null_pages_remains_an_empty_result(self):
        body = {"Response": {"Pages": None}}
        with patch(
            "wsa_client.urllib.request.urlopen",
            return_value=FakeResponse(json.dumps(body).encode("utf-8")),
        ):
            result, _ = wsa.search("测试查询", api_key="test-key")

        self.assertEqual(result["raw_count"], 0)
        self.assertEqual(result["pages"], [])

    def test_http_error_without_api_error_is_not_success(self):
        error = urllib.error.HTTPError(
            wsa.APIKEY_URL, 500, "Internal Server Error", {}, io.BytesIO(b"{}")
        )
        with patch("wsa_client.urllib.request.urlopen", side_effect=error):
            with self.assertRaises(wsa.WSAError) as raised:
                wsa.search("测试查询", api_key="test-key")

        self.assertEqual(raised.exception.code, "500")
        self.assertIn("500", str(raised.exception))

    def test_http_error_preserves_api_error_details(self):
        body = json.dumps({"Response": {
            "Error": {
                "Code": "RequestLimitExceeded",
                "Message": "too many requests",
            },
            "RequestId": "request-429",
        }}).encode("utf-8")
        error = urllib.error.HTTPError(
            wsa.APIKEY_URL, 429, "Too Many Requests", {}, io.BytesIO(body)
        )
        with patch("wsa_client.urllib.request.urlopen", side_effect=error):
            with self.assertRaises(wsa.WSAError) as raised:
                wsa.search("测试查询", api_key="test-key")

        self.assertEqual(raised.exception.code, "RequestLimitExceeded")
        self.assertEqual(raised.exception.request_id, "request-429")

    def test_non_json_response_reports_http_status(self):
        with self.assertRaises(wsa.WSAError) as raised:
            self.call_post(b"not-json", status=502)

        self.assertIn("HTTP 502", str(raised.exception))

    def test_non_success_status_without_http_error_is_rejected(self):
        with self.assertRaises(wsa.WSAError) as raised:
            self.call_post({"Response": {"Pages": []}}, status=503)

        self.assertEqual(raised.exception.code, "503")

    def test_invalid_response_shapes_raise_wsa_error(self):
        cases = (
            ([], "顶层"),
            ({"Response": []}, "Response"),
            ({"Response": {"Pages": "not-an-array"}}, "Pages"),
            ({"Response": {"Error": "not-an-object"}}, "Error"),
        )
        for body, expected in cases:
            with self.subTest(body=body):
                with self.assertRaises(wsa.WSAError) as raised:
                    self.call_post(body)
                self.assertIn(expected, str(raised.exception))

    def test_url_error_is_wrapped(self):
        with patch(
            "wsa_client.urllib.request.urlopen",
            side_effect=urllib.error.URLError("connection refused"),
        ):
            with self.assertRaises(wsa.WSAError) as raised:
                wsa.search("测试查询", api_key="test-key")

        self.assertIn("网络请求失败", str(raised.exception))


if __name__ == "__main__":
    unittest.main()
