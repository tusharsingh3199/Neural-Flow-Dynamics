import os
from unittest.mock import patch

import pytest

from app.source_feasibility import (
    S3_NAMESPACE,
    check_tinyfish,
    extract_sachet_feed_links,
    find_source,
    load_registry,
    parse_s3_listing,
)


def test_parse_s3_listing_extracts_bucket_and_key() -> None:
    payload = (
        f'<ListBucketResult xmlns="{S3_NAMESPACE}">'
        "<Name>test-bucket</Name><KeyCount>1</KeyCount>"
        "<Contents><Key>gfs.20261015/00/file.grb2</Key></Contents>"
        "</ListBucketResult>"
    ).encode()

    result = parse_s3_listing(payload, "test-bucket")

    assert result["key_count"] == 1
    assert result["keys"] == ["gfs.20261015/00/file.grb2"]


def test_parse_s3_listing_rejects_unexpected_bucket() -> None:
    payload = (
        f'<ListBucketResult xmlns="{S3_NAMESPACE}">'
        "<Name>wrong-bucket</Name><KeyCount>0</KeyCount>"
        "</ListBucketResult>"
    ).encode()

    with pytest.raises(ValueError, match="expected"):
        parse_s3_listing(payload, "expected-bucket")


def test_sachet_feedback_link_is_not_misidentified_as_rss() -> None:
    html = b'<a href="/CapFeed">RSS FEED</a><a href="/Feedback">Feedback</a>'

    assert extract_sachet_feed_links(html) == []


def test_sachet_detects_explicit_feed_urls() -> None:
    html = b'<a href="/feeds/india.xml">India RSS</a>'

    assert extract_sachet_feed_links(html) == [{"href": "/feeds/india.xml", "text": "India RSS"}]


def test_missing_tinyfish_key_is_reported_without_network_call() -> None:
    registry = load_registry()
    source = find_source(registry, "tinyfish_fetch")
    with patch.dict(os.environ, {"TINYFISH_API_KEY": ""}):
        result = check_tinyfish(source, probe_api=True)

    assert result == {"source_id": "tinyfish_fetch", "status": "skipped_no_api_key"}
