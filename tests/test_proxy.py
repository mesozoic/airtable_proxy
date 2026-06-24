"""Tests for the proxy module helpers."""

import gzip
import json

import httpx

from airtable_proxy import proxy


def test_parse_2xx_body_returns_none_for_non_2xx():
    response = httpx.Response(status_code=422, content=b'{"error": "bad"}')
    assert proxy.parse_2xx_body(response) is None


def test_parse_2xx_body_returns_none_for_non_json():
    response = httpx.Response(status_code=200, content=b"not json")
    assert proxy.parse_2xx_body(response) is None


def test_parse_2xx_body_returns_none_for_json_list():
    response = httpx.Response(
        status_code=200,
        content=json.dumps([{"id": "rec1"}]).encode(),
        headers={"Content-Type": "application/json"},
    )
    assert proxy.parse_2xx_body(response) is None


def test_parse_2xx_body_returns_dict_for_valid_response():
    body = {"records": [{"id": "rec1"}]}
    response = httpx.Response(
        status_code=200,
        content=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
    )
    assert proxy.parse_2xx_body(response) == body


def test_response_from_httpx_strips_hop_by_hop_encoding_headers():
    """
    httpx auto-decodes gzipped bodies. If the proxy forwards the
    Content-Encoding / Transfer-Encoding headers, downstream clients
    will try to decode an already-decoded body and fail. They must be
    stripped.
    """
    upstream = httpx.Response(
        status_code=200,
        headers={
            "Content-Type": "application/json",
            "Content-Encoding": "gzip",
            "Transfer-Encoding": "chunked",
            "X-Custom": "preserved",
        },
        content=gzip.compress(b'{"ok": true}'),
    )

    result = proxy.response_from_httpx(upstream)

    assert "content-encoding" not in {k.lower() for k in result.headers}
    assert "transfer-encoding" not in {k.lower() for k in result.headers}
    assert result.headers["X-Custom"] == "preserved"
    assert result.status_code == 200
    assert result.media_type == "application/json"
