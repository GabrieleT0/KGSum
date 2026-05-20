from __future__ import annotations

from collections import Counter
from typing import Any
from urllib.parse import urlparse


def kg_from_uri(uri: str) -> str:
    """Return a dataset-level URI for a linked resource URI."""
    if not isinstance(uri, str):
        return ""

    parsed = urlparse(uri.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return ""

    return f"{parsed.scheme}://{parsed.netloc}"


def aggregate_same_as_links(links: Any) -> list[dict[str, Any]]:
    """Group owl:sameAs object URIs by linked KG and count all links."""
    if links is None:
        return []

    if isinstance(links, dict):
        links = [links]
    elif not isinstance(links, list):
        links = [links]

    counts: Counter[str] = Counter()
    for item in links:
        if isinstance(item, dict):
            dataset = item.get("dataset") or item.get("kg") or item.get("target")
            count = item.get("count") or item.get("triples") or 0
            dataset_uri = kg_from_uri(str(dataset)) if dataset else ""
            if dataset_uri:
                try:
                    counts[dataset_uri] += int(count)
                except (TypeError, ValueError):
                    counts[dataset_uri] += 1
            continue

        dataset_uri = kg_from_uri(str(item))
        if dataset_uri:
            counts[dataset_uri] += 1

    return [
        {"dataset": dataset, "count": count}
        for dataset, count in sorted(counts.items(), key=lambda pair: (-pair[1], pair[0]))
    ]
