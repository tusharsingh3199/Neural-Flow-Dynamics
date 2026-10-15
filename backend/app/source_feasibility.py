import argparse
import csv
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from functools import partial
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, cast

REGISTRY_PATH = Path(__file__).resolve().parents[2] / "source_registry.json"
S3_NAMESPACE = "http://s3.amazonaws.com/doc/2006-03-01/"


class AnchorParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.anchors: list[dict[str, str]] = []
        self._href: str | None = None
        self._text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "a":
            self._href = dict(attrs).get("href")
            self._text = []

    def handle_data(self, data: str) -> None:
        if self._href is not None:
            self._text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._href is not None:
            self.anchors.append({"href": self._href, "text": " ".join(self._text).strip()})
            self._href = None
            self._text = []


def load_registry() -> dict[str, Any]:
    return cast(dict[str, Any], json.loads(REGISTRY_PATH.read_text(encoding="utf-8")))


def request_bytes(
    url: str,
    *,
    method: str = "GET",
    headers: dict[str, str] | None = None,
    timeout: int = 25,
    limit: int = 1_000_000,
) -> tuple[int, dict[str, str], bytes]:
    request = urllib.request.Request(url, headers=headers or {}, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read(limit)
            return response.status, dict(response.headers.items()), body
    except urllib.error.HTTPError as error:
        error.close()
        raise


def find_source(registry: dict[str, Any], source_id: str) -> dict[str, Any]:
    return next(source for source in registry["sources"] if source["id"] == source_id)


def check_arco(source: dict[str, Any]) -> dict[str, Any]:
    probe = source["probe"]
    status, _, body = request_bytes(probe["metadata_url"])
    metadata = json.loads(body)
    available_variables: list[str] = []
    unavailable_variables: list[str] = []
    store_path = source["url"].removeprefix("gs://gcp-public-data-arco-era5/").rstrip("/")
    for name in probe["variable_names"]:
        attrs_url = (
            "https://storage.googleapis.com/gcp-public-data-arco-era5/"
            f"{store_path}/{urllib.parse.quote(name)}/.zattrs"
        )
        try:
            _, _, attrs_body = request_bytes(attrs_url)
            attributes = json.loads(attrs_body)
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, json.JSONDecodeError):
            unavailable_variables.append(name)
            continue
        if attributes.get("units"):
            available_variables.append(name)
        else:
            unavailable_variables.append(name)
    return {
        "source_id": source["id"],
        "status": "reachable" if not unavailable_variables else "partial",
        "http_status": status,
        "last_updated": metadata.get("last_updated"),
        "valid_time_start": metadata.get("valid_time_start"),
        "valid_time_stop": metadata.get("valid_time_stop"),
        "valid_time_stop_era5t": metadata.get("valid_time_stop_era5t"),
        "variables_with_units": available_variables,
        "variables_unavailable_or_without_units": unavailable_variables,
    }


def parse_s3_listing(content: bytes, expected_bucket: str) -> dict[str, Any]:
    root = ET.fromstring(content)
    name = root.findtext(f"{{{S3_NAMESPACE}}}Name")
    key_count = int(root.findtext(f"{{{S3_NAMESPACE}}}KeyCount", default="0"))
    keys = [
        element.text or ""
        for element in root.findall(f"{{{S3_NAMESPACE}}}Contents/{{{S3_NAMESPACE}}}Key")
    ]
    if name != expected_bucket:
        raise ValueError(f"S3 returned bucket {name!r}, expected {expected_bucket!r}")
    return {"bucket": name, "key_count": key_count, "keys": keys}


def extract_sachet_feed_links(content: bytes) -> list[dict[str, str]]:
    parser = AnchorParser()
    parser.feed(content.decode("utf-8", errors="replace"))
    feed_links: list[dict[str, str]] = []
    for anchor in parser.anchors:
        path = urllib.parse.urlsplit(anchor["href"]).path.lower()
        if path.endswith((".rss", ".xml")) or "/rss/" in path or path.startswith("/rss"):
            feed_links.append(anchor)
    return feed_links


def check_gfs_bucket(source: dict[str, Any]) -> dict[str, Any]:
    bucket = source["probe"]["bucket"]
    base_url = f"https://{bucket}.s3.amazonaws.com/"
    listing_url = base_url + "?list-type=2&max-keys=1"
    status, _, body = request_bytes(listing_url)
    listing = parse_s3_listing(body, bucket)
    recent: list[dict[str, str]] = []
    today = datetime.now(UTC).date()
    for offset in range(2):
        date = (today - timedelta(days=offset)).strftime("%Y%m%d")
        query = urllib.parse.urlencode(
            {"list-type": "2", "prefix": f"gfs.{date}/", "max-keys": "1"}
        )
        _, _, day_body = request_bytes(base_url + "?" + query)
        day_listing = parse_s3_listing(day_body, bucket)
        recent.extend({"date_utc": date, "key": key} for key in day_listing["keys"])
    if listing["key_count"] == 0:
        result_status = "empty"
    elif recent:
        result_status = "recent_data"
    else:
        result_status = "reachable_no_recent_run_found"
    return {
        "source_id": source["id"],
        "status": result_status,
        "http_status": status,
        "root_key_count": listing["key_count"],
        "recent_keys": recent,
    }


def check_ibtracs(source: dict[str, Any]) -> dict[str, Any]:
    probe = source["probe"]
    status, headers, _ = request_bytes(probe["url"], method="HEAD")
    _, _, sample = request_bytes(
        probe["url"],
        headers={"Range": "bytes=0-8191"},
        limit=8192,
    )
    rows = csv.reader(sample.decode("utf-8-sig").splitlines())
    header = next(rows, [])
    missing = [column for column in probe["required_columns"] if column not in header]
    return {
        "source_id": source["id"],
        "status": "reachable" if not missing else "partial",
        "http_status": status,
        "content_length_bytes": headers.get("Content-Length"),
        "header_column_count": len(header),
        "required_columns_found": [
            column for column in probe["required_columns"] if column in header
        ],
        "required_columns_missing": missing,
    }


def check_sachet(source: dict[str, Any]) -> dict[str, Any]:
    probe = source["probe"]
    status, headers, body = request_bytes(probe["url"])
    feed_links = extract_sachet_feed_links(body)
    return {
        "source_id": source["id"],
        "status": "feed_link_found" if feed_links else "landing_page_only",
        "http_status": status,
        "content_type": headers.get("Content-Type"),
        "candidate_feed_links": feed_links,
    }


def check_documentation_page(source: dict[str, Any]) -> dict[str, Any]:
    url = source["probe"]["url"]
    status, headers, _ = request_bytes(url, limit=4096)
    return {
        "source_id": source["id"],
        "status": "reachable",
        "http_status": status,
        "content_type": headers.get("Content-Type"),
    }


def guarded_check(source_id: str, check: Callable[[], dict[str, Any]]) -> dict[str, Any]:
    try:
        return check()
    except urllib.error.HTTPError as error:
        error.close()
        return {"source_id": source_id, "status": "http_error", "http_status": error.code}
    except (urllib.error.URLError, TimeoutError, OSError):
        return {"source_id": source_id, "status": "network_error"}
    except (json.JSONDecodeError, ET.ParseError, UnicodeDecodeError, ValueError):
        return {"source_id": source_id, "status": "invalid_response"}


def check_tinyfish(source: dict[str, Any], *, probe_api: bool) -> dict[str, Any]:
    key = os.environ.get(source["probe"]["key_environment_variable"], "").strip()
    if not key:
        return {"source_id": source["id"], "status": "skipped_no_api_key"}
    if not probe_api:
        return {"source_id": source["id"], "status": "key_present_api_not_called"}
    request = urllib.request.Request(
        source["probe"]["endpoint"],
        data=json.dumps(
            {"urls": ["https://www.ncei.noaa.gov/products/international-best-track-archive"]}
        ).encode("utf-8"),
        headers={"X-API-Key": key, "Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=150) as response:
        result = cast(dict[str, Any], json.loads(response.read(1_000_000)))
    return {
        "source_id": source["id"],
        "status": "fetch_succeeded" if result.get("results") else "fetch_returned_no_results",
        "result_count": len(result.get("results", [])),
        "error_count": len(result.get("errors", [])),
    }


def run_checks(registry: dict[str, Any], *, probe_tinyfish: bool = False) -> list[dict[str, Any]]:
    sources = {source["id"]: source for source in registry["sources"]}
    checks: list[dict[str, Any]] = []
    for source_id in (
        "arco_era5",
        "noaa_gfs_bdp_pds",
        "noaa_gfs_pds_legacy",
        "ibtracs_north_indian_v04r01",
        "sachet_cap_rss",
        "openstreetmap_data",
        "worldpop_population",
    ):
        source = sources[source_id]
        kind = source["probe"]["kind"]
        if kind == "arco_metadata":
            checks.append(guarded_check(source_id, partial(check_arco, source)))
        elif kind == "s3_bucket":
            checks.append(guarded_check(source_id, partial(check_gfs_bucket, source)))
        elif kind == "csv_header":
            checks.append(guarded_check(source_id, partial(check_ibtracs, source)))
        elif kind == "html_feed_discovery":
            checks.append(guarded_check(source_id, partial(check_sachet, source)))
        elif kind == "documentation_page":
            checks.append(guarded_check(source_id, partial(check_documentation_page, source)))
    tinyfish = sources["tinyfish_fetch"]
    checks.append(
        guarded_check(
            tinyfish["id"],
            partial(check_tinyfish, tinyfish, probe_api=probe_tinyfish),
        )
    )
    return checks


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Check configured environmental source availability."
    )
    parser.add_argument(
        "--probe-tinyfish",
        action="store_true",
        help="Make one TinyFish Fetch API request if TINYFISH_API_KEY is set.",
    )
    args = parser.parse_args()
    report = {
        "checked_at": datetime.now(UTC).isoformat(),
        "results": run_checks(load_registry(), probe_tinyfish=args.probe_tinyfish),
    }
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
