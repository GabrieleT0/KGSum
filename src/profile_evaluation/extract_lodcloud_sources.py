
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import aiohttp
import requests


BASE_DIR = Path(__file__).resolve().parent
DEFAULT_CATALOG_URL = "https://lod-cloud.net/versions/latest/lod-data.json"
SPARQL_TEST_QUERY = "SELECT * WHERE { ?s ?p ?o } LIMIT 1"
USER_AGENT = "KGSum-LODCloud-source-extractor/1.0"

RDF_EXTENSIONS = (
    ".rdf",
    ".ttl",
    ".nt",
    ".nq",
    ".trig",
    ".trix",
    ".jsonld",
    ".json",
    ".owl",
    ".xml",
    ".rdf.gz",
    ".ttl.gz",
    ".nt.gz",
    ".nq.gz",
    ".trig.gz",
    ".jsonld.gz",
    ".rdf.zip",
    ".ttl.zip",
    ".nt.zip",
    ".nq.zip",
    ".trig.zip",
)

RDF_MEDIA_HINTS = (
    "rdf",
    "turtle",
    "n-triples",
    "n-quads",
    "trig",
    "trix",
    "ld+json",
    "owl",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-url", default=DEFAULT_CATALOG_URL, help="LOD Cloud JSON URL to analyze.")
    parser.add_argument("--output", default=str(BASE_DIR / "lodcloud_sources.json"), help="Output JSON file path.")
    parser.add_argument("--timeout", type=float, default=12.0, help="Per-request timeout in seconds.")
    parser.add_argument("--concurrency", type=int, default=25, help="Maximum concurrent dataset checks.")
    parser.add_argument(
        "--include-non-rdf-looking-dumps",
        action="store_true",
        help="Also test full_download URLs that do not look RDF-like by extension/media type.",
    )
    parser.add_argument("--indent", type=int, default=2, help="JSON indentation for the output file.")
    parser.add_argument(
        "--profiles-output-dir",
        default=str(BASE_DIR / "lodcloud_profiles"),
        help="Directory where LOD Cloud RDF profile TTL files are written.",
    )
    return parser.parse_args()


def iter_url_values(entries: Any, preferred_keys: Iterable[str]) -> list[str]:
    urls: list[str] = []
    if not isinstance(entries, list):
        return urls

    for entry in entries:
        if not isinstance(entry, dict):
            continue
        for key in preferred_keys:
            value = entry.get(key)
            if isinstance(value, str) and value.strip():
                urls.append(value.strip())

    return list(dict.fromkeys(urls))


def looks_like_rdf_dump(entry: dict[str, Any], url: str) -> bool:
    url_without_query = url.split("?", 1)[0].lower()
    media_type = str(entry.get("media_type") or "").lower()
    title = str(entry.get("title") or "").lower()
    description = str(entry.get("description") or "").lower()
    haystack = " ".join((media_type, title, description))

    return url_without_query.endswith(RDF_EXTENSIONS) or any(hint in haystack for hint in RDF_MEDIA_HINTS)


def dump_candidates(dataset: dict[str, Any], include_non_rdf_looking: bool) -> list[str]:
    candidates: list[str] = []
    full_download = dataset.get("full_download")
    if not isinstance(full_download, list):
        return candidates

    for entry in full_download:
        if not isinstance(entry, dict):
            continue

        urls = [
            value.strip()
            for key in ("download_url", "access_url")
            if isinstance((value := entry.get(key)), str) and value.strip()
        ]
        for url in urls:
            if include_non_rdf_looking or looks_like_rdf_dump(entry, url):
                candidates.append(url)

    return list(dict.fromkeys(candidates))


async def fetch_catalog(session: aiohttp.ClientSession, url: str) -> dict[str, Any]:
    async with session.get(url) as response:
        response.raise_for_status()
        payload = await response.json(content_type=None)
        if not isinstance(payload, dict):
            raise ValueError("LOD Cloud catalog is not a JSON object.")
        return payload


async def sparql_endpoint_works(session: aiohttp.ClientSession, endpoint: str) -> bool:
    headers = {"Accept": "application/sparql-results+json, application/json;q=0.9, */*;q=0.1"}
    params = {"query": SPARQL_TEST_QUERY, "format": "json"}

    try:
        async with session.get(endpoint, params=params, headers=headers, allow_redirects=True) as response:
            if response.status >= 400:
                return False
            text = await response.text()
    except (aiohttp.ClientError, asyncio.TimeoutError, UnicodeDecodeError):
        return False

    if not text.strip():
        return False

    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return "sparql" in text.lower() or "results" in text.lower()

    return isinstance(payload, dict) and ("results" in payload or "boolean" in payload)


async def url_downloadable(session: aiohttp.ClientSession, url: str) -> bool:
    headers = {"Accept": "*/*", "Range": "bytes=0-0"}

    try:
        async with session.head(url, headers=headers, allow_redirects=True) as response:
            if 200 <= response.status < 400:
                return True
            if response.status not in {405, 403, 406}:
                return False
    except (aiohttp.ClientError, asyncio.TimeoutError):
        pass

    try:
        async with session.get(url, headers=headers, allow_redirects=True) as response:
            return 200 <= response.status < 400
    except (aiohttp.ClientError, asyncio.TimeoutError):
        return False


async def first_working_sparql(session: aiohttp.ClientSession, dataset: dict[str, Any]) -> str | None:
    endpoints = iter_url_values(dataset.get("sparql"), ("access_url", "download_url"))
    for endpoint in endpoints:
        if await sparql_endpoint_works(session, endpoint):
            return endpoint
    return None


async def first_downloadable_dump(
    session: aiohttp.ClientSession,
    dataset: dict[str, Any],
    include_non_rdf_looking: bool,
) -> str | None:
    for url in dump_candidates(dataset, include_non_rdf_looking):
        if await url_downloadable(session, url):
            return url
    return None


async def analyze_dataset(
    session: aiohttp.ClientSession,
    dataset_id: str,
    dataset: dict[str, Any],
    include_non_rdf_looking: bool,
) -> dict[str, str] | None:
    title = str(dataset.get("title") or dataset.get("identifier") or dataset_id)
    result = {"id": str(dataset.get("identifier") or dataset.get("_id") or dataset_id), "title": title}

    endpoint = await first_working_sparql(session, dataset)
    if endpoint:
        result["sparql_endpoint"] = endpoint
        return result

    dump_url = await first_downloadable_dump(session, dataset, include_non_rdf_looking)
    if dump_url:
        result["rdf_dump"] = dump_url
        return result

    return None


async def analyze_catalog(args: argparse.Namespace) -> list[dict[str, str]]:
    timeout = aiohttp.ClientTimeout(total=args.timeout)
    connector = aiohttp.TCPConnector(limit=max(args.concurrency, 1), ssl=False)
    headers = {"User-Agent": USER_AGENT}

    async with aiohttp.ClientSession(timeout=timeout, connector=connector, headers=headers) as session:
        catalog = await fetch_catalog(session, args.input_url)
        semaphore = asyncio.Semaphore(max(args.concurrency, 1))

        async def guarded(dataset_id: str, dataset: Any) -> dict[str, str] | None:
            if not isinstance(dataset, dict):
                return None
            async with semaphore:
                return await analyze_dataset(session, dataset_id, dataset, args.include_non_rdf_looking_dumps)

        tasks = [guarded(dataset_id, dataset) for dataset_id, dataset in catalog.items()]
        results = await asyncio.gather(*tasks)

    return sorted((result for result in results if result), key=lambda item: item["id"].lower())


def retrieve_lodcloud_profiles(sources_path: Path, profiles_output_dir: Path) -> None:
    with sources_path.open('r', encoding='utf-8') as f:
        sources = json.load(f)

    profiles_output_dir.mkdir(parents=True, exist_ok=True)

    for source in sources:
        source_id = source['id']
        response = requests.get(f"https://lod-cloud.net/rdf/{source_id}?format=ttl")
        if response.status_code == 200:
            (profiles_output_dir / f'{source_id}.ttl').write_text(response.text, encoding='utf-8')
        else:
            print(f"Failed to retrieve RDF for {source_id}: {response.status_code}")


def main() -> int:
    args = parse_args()
    try:
        results = asyncio.run(analyze_catalog(args))
    except KeyboardInterrupt:
        return 130
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(results, indent=args.indent, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Wrote {len(results)} dataset sources to {output_path}")
    profiles_output_dir = Path(args.profiles_output_dir)
    if not profiles_output_dir.is_absolute():
        profiles_output_dir = output_path.parent / profiles_output_dir
    retrieve_lodcloud_profiles(output_path, profiles_output_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
