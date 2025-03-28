import functools
import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any, Callable, Concatenate, Iterable, ParamSpec, Self, TypeVar

import flask
import pyairtable
import requests
import werkzeug

from airtable_proxy.record_cache import RecordCache


class AppContext:
    def __init__(self) -> None:
        self._apis: dict[str, pyairtable.Api] = {}
        self._caches: dict[str, RecordCache] = {}

    @property
    def api_key(self) -> str:
        """
        Extracts the API key from the Authorization header of the current request.
        """
        auth_header = flask.request.headers.get("Authorization", "")
        if match := re.match(r"^Bearer ([a-zA-Z0-9._-]+)$", auth_header):
            return match.group(1)
        raise flask.abort(403)

    @property
    def api(self) -> pyairtable.Api:
        """
        Generates a unique instance of ``pyairtable.Api`` for the request's API key.
        """
        try:
            return self._apis[self.api_key]
        except KeyError:
            api = self._apis[self.api_key] = pyairtable.Api(self.api_key)
            return api

    @property
    def cache_location(self) -> Path:
        """
        Generates a unique location for the disk cache for the request's API key.
        """
        base = Path(os.environ["AIRTABLE_CACHE_DIR"])
        return base / hashlib.sha256(self.api_key.encode()).hexdigest()

    @property
    def cache(self) -> RecordCache:
        """
        Opens the appropriate ``RecordCache`` for the request's API key.
        """
        if self.api_key not in self._caches:
            self._caches[self.api_key] = RecordCache(self.cache_location, self.api)
        return self._caches[self.api_key]


P = ParamSpec("P")
T = TypeVar("T")


def uses_context(callable: Callable[Concatenate[AppContext, P], T]) -> Callable[P, T]:
    key = "AIRTABLE_PROXY_CONTEXT"

    @functools.wraps(callable)
    def _wrapper(*args: P.args, **kwargs: P.kwargs) -> T:
        try:
            ctx = flask.current_app.config[key]
        except Exception:
            ctx = flask.current_app.config[key] = AppContext()
        return callable(ctx, *args, **kwargs)

    return _wrapper


class AirtableIdConverter(werkzeug.routing.BaseConverter):
    regex = r"[a-z]{3}[a-zA-Z0-9]{14}"

    @classmethod
    def for_prefix(cls, prefix: str) -> type[Self]:
        regex = prefix + r"[a-zA-Z0-9]{14}"
        return type(prefix.capitalize() + "Converter", (cls,), {"regex": regex})


app = flask.Flask("airtable_proxy")
app.url_map.converters["app"] = AirtableIdConverter.for_prefix("app")
app.url_map.converters["tbl"] = AirtableIdConverter.for_prefix("tbl")
app.url_map.converters["rec"] = AirtableIdConverter.for_prefix("rec")


# If any of these are in the request, we'll proxy it directly to Airtable.
UNSUPPORTED_PARAMS = (
    "cellFormat",
    "filterByFormula",
    "maxRecords",
    "offset",
    "recordMetadata",
    "sort",
    "view",
)


@app.route("/v0/meta/bases/<app:base_id>/tables")
@uses_context
def get_base_schema(ctx: AppContext, base_id: str) -> Any:
    return get_cache_or_perform_request(ctx, f"meta/bases/{base_id}/tables")


@app.route("/v0/<app:base_id>/<tbl:table_id>")
@uses_context
def get_records(ctx: AppContext, base_id: str, table_id: str) -> Any:
    if any(param in flask.request.args for param in UNSUPPORTED_PARAMS):
        return requests_to_flask(
            passthrough_get(ctx.api.build_url(f"{base_id}/{table_id}"))
        )

    use_field_ids = bool(flask.request.args.get("returnFieldsByFieldId"))
    records = ctx.cache.get_records(base_id, table_id, use_field_ids=use_field_ids)
    return json_response({"records": records})


@app.route("/v0/<app:base_id>/<tbl:table_id>/<rec:record_id>")
@uses_context
def get_record(ctx: AppContext, base_id: str, table_id: str, record_id: str) -> Any:
    if any(param in flask.request.args for param in UNSUPPORTED_PARAMS):
        return requests_to_flask(
            passthrough_get(ctx.api.build_url(f"{base_id}/{table_id}/{record_id}"))
        )

    use_field_ids = bool(flask.request.args.get("returnFieldsByFieldId"))
    record = ctx.cache.get_record(
        base_id, table_id, record_id, use_field_ids=use_field_ids
    )
    return json_response(record)


def get_cache_or_perform_request(ctx: AppContext, path: str) -> flask.Response:
    """
    Return the cached response for the given path, or perform the request and cache it.
    """
    cache_key = "@" + path
    try:
        data = ctx.cache.persisted[cache_key]
        return json_response(data)
    except KeyError:
        pass
    url = ctx.api.build_url(path)
    response = passthrough_get(url)
    response.raise_for_status()
    ctx.cache.persisted.set(cache_key, response.json())
    return requests_to_flask(response)


def passthrough_request(
    method: str,
    url: str,
    *,
    pass_headers: Iterable[str] = {"authorization", "user-agent"},
) -> requests.Response:
    """
    Perform a GET request, passing along the headers from the original request.
    """
    pass_headers = [header.lower() for header in pass_headers]
    headers = {
        k: v for (k, v) in flask.request.headers.items() if k.lower() in pass_headers
    }
    return requests.request(
        method,
        url,
        params=dict(flask.request.args.lists()),
        headers=headers,
    )


passthrough_get = functools.partial(passthrough_request, "GET")
passthrough_post = functools.partial(passthrough_request, "POST")


def requests_to_flask(value: requests.Response) -> flask.Response:
    response = flask.Response(
        value.content,
        status=value.status_code,
        mimetype=value.headers.get("Content-Type", "application/json"),
    )
    response.headers.update(value.headers.items())
    return response


def json_response(data: Any, status: int = 200) -> flask.Response:
    return flask.Response(json.dumps(data), status=status, mimetype="application/json")
