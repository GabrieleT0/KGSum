import asyncio
import logging
import sys
import os
import ssl
import xml.etree.ElementTree as eT
from typing import Any
from urllib.parse import urldefrag, urljoin, urlparse

import aiohttp
import pandas as pd
from rdflib import BNode, Graph, Literal, URIRef
from rdflib.namespace import DCTERMS, OWL, RDF, RDFS

from config import Config
from src.lov_data_preparation import find_tags_from_list, find_comments_from_lists
from src.void_linksets import aggregate_same_as_links

MAX_OFFSET = 1000
ENDPOINT_TIMEOUT = 600
SAME_AS_PAGE_SIZE = int(os.getenv("SAME_AS_PAGE_SIZE", "500"))
MAX_SAME_AS_LINKS = int(os.getenv("MAX_SAME_AS_LINKS", "10000"))

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("dataset_preparation_remote")

SPARQL_RESULTS_ACCEPT = (
    "application/sparql-results+xml, application/xml;q=0.9, text/xml;q=0.8, */*;q=0.1"
)
VOID_RDF_ACCEPT = (
    "text/turtle, application/rdf+xml;q=0.9, application/ld+json;q=0.8, "
    "application/n-triples;q=0.7, text/n3;q=0.6, text/html;q=0.5, */*;q=0.1"
)
VOID_DATASET = URIRef("http://rdfs.org/ns/void#Dataset")
VOID_DATASET_DESCRIPTION = URIRef("http://rdfs.org/ns/void#DatasetDescription")
VOID_LINKSET = URIRef("http://rdfs.org/ns/void#Linkset")
VOID_SPARQL_ENDPOINT = URIRef("http://rdfs.org/ns/void#sparqlEndpoint")
VOID_DATA_DUMP = URIRef("http://rdfs.org/ns/void#dataDump")
VOID_VOCABULARY = URIRef("http://rdfs.org/ns/void#vocabulary")
VOID_TRIPLES = URIRef("http://rdfs.org/ns/void#triples")
VOID_ENTITIES = URIRef("http://rdfs.org/ns/void#entities")
VOID_CLASS_PARTITION = URIRef("http://rdfs.org/ns/void#classPartition")
VOID_PROPERTY_PARTITION = URIRef("http://rdfs.org/ns/void#propertyPartition")
VOID_CLASS = URIRef("http://rdfs.org/ns/void#class")
VOID_PROPERTY = URIRef("http://rdfs.org/ns/void#property")
VOID_TARGET = URIRef("http://rdfs.org/ns/void#target")
VOID_OBJECTS_TARGET = URIRef("http://rdfs.org/ns/void#objectsTarget")
VOID_LINK_PREDICATE = URIRef("http://rdfs.org/ns/void#linkPredicate")
VOID_IN_DATASET = URIRef("http://rdfs.org/ns/void#inDataset")
VOID_ROOT_RESOURCE = URIRef("http://rdfs.org/ns/void#rootResource")
VOID_URI_LOOKUP_ENDPOINT = URIRef("http://rdfs.org/ns/void#uriLookupEndpoint")
FOAF_HOMEPAGE = URIRef("http://xmlns.com/foaf/0.1/homepage")
FOAF_TOPIC = URIRef("http://xmlns.com/foaf/0.1/topic")
FOAF_PRIMARY_TOPIC = URIRef("http://xmlns.com/foaf/0.1/primaryTopic")
SD_DATASET = URIRef("http://www.w3.org/ns/sparql-service-description#Dataset")
SD_GRAPH = URIRef("http://www.w3.org/ns/sparql-service-description#Graph")
SD_URL = URIRef("http://www.w3.org/ns/sparql-service-description#url")
SD_DEFAULT_DATASET_DESCRIPTION = URIRef("http://www.w3.org/ns/sparql-service-description#defaultDatasetDescription")
SD_DEFAULT_GRAPH = URIRef("http://www.w3.org/ns/sparql-service-description#defaultGraph")
SD_NAMED_GRAPH = URIRef("http://www.w3.org/ns/sparql-service-description#namedGraph")
SD_GRAPH_PROP = URIRef("http://www.w3.org/ns/sparql-service-description#graph")
DCAT_DATASET = URIRef("http://www.w3.org/ns/dcat#Dataset")
DCAT_LANDING_PAGE = URIRef("http://www.w3.org/ns/dcat#landingPage")
DCAT_ACCESS_URL = URIRef("http://www.w3.org/ns/dcat#accessURL")
DCAT_DOWNLOAD_URL = URIRef("http://www.w3.org/ns/dcat#downloadURL")
DCAT_DISTRIBUTION = URIRef("http://www.w3.org/ns/dcat#distribution")
DCAT_ENDPOINT_URL = URIRef("http://www.w3.org/ns/dcat#endpointURL")
SCHEMA_DATASET = URIRef("http://schema.org/Dataset")
SCHEMA_HTTPS_DATASET = URIRef("https://schema.org/Dataset")
SCHEMA_CONTENT_URL = URIRef("http://schema.org/contentUrl")
SCHEMA_HTTPS_CONTENT_URL = URIRef("https://schema.org/contentUrl")
SCHEMA_DISTRIBUTION = URIRef("http://schema.org/distribution")
SCHEMA_HTTPS_DISTRIBUTION = URIRef("https://schema.org/distribution")
DCTYPE_DATASET = URIRef("http://purl.org/dc/dcmitype/Dataset")
QB_DATASET = URIRef("http://purl.org/linked-data/cube#DataSet")
ADMS_ASSET = URIRef("http://www.w3.org/ns/adms#Asset")

try:
    import certifi

    SSL_CONTEXT = ssl.create_default_context(cafile=certifi.where())
except Exception:
    SSL_CONTEXT = None


def _one_line_snippet(text: str, limit: int = 240) -> str:
    snippet = " ".join((text or "").split())
    if len(snippet) > limit:
        return snippet[: limit - 3] + "..."
    return snippet


def _is_remote_http_url(url: str) -> bool:
    parsed = urlparse(str(url))
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return False
    host = (parsed.hostname or "").lower()
    return host not in {"localhost", "127.0.0.1", "::1", "0.0.0.0"}


def _guess_rdf_format(url: str, content_type: str = "") -> str | None:
    content_type = content_type.lower()
    url_path = urlparse(url).path.lower()
    if "turtle" in content_type or url_path.endswith(".ttl"):
        return "turtle"
    if "rdf+xml" in content_type or "application/xml" in content_type or url_path.endswith((".rdf", ".xml")):
        return "xml"
    if "n-triples" in content_type or url_path.endswith(".nt"):
        return "nt"
    if "ld+json" in content_type or url_path.endswith(".jsonld"):
        return "json-ld"
    if "n3" in content_type or url_path.endswith(".n3"):
        return "n3"
    if "html" in content_type or url_path.endswith((".html", ".htm")):
        return "rdfa"
    return None


def _well_known_void_url(endpoint: str) -> str:
    parsed = urlparse(endpoint)
    origin = f"{parsed.scheme}://{parsed.netloc}/"
    return urljoin(origin, ".well-known/void")


def _origin_url(url: str) -> str:
    parsed = urlparse(url)
    return f"{parsed.scheme}://{parsed.netloc}/"


def _dataset_site_urls(endpoint: str) -> list[str]:
    parsed = urlparse(endpoint)
    sites = [endpoint]
    path = parsed.path.rstrip("/")
    if path.lower().endswith("/sparql"):
        dataset_path = path[:-len("/sparql")] or "/"
        sites.append(parsed._replace(path=dataset_path, params="", query="", fragment="").geturl())
    sites.append(_origin_url(endpoint))

    seen: set[str] = set()
    return [site for site in sites if not (site in seen or seen.add(site))]


def _published_void_candidates(endpoint: str) -> list[str]:
    candidates: list[str] = []
    for site in _dataset_site_urls(endpoint):
        site_base = site if site.endswith("/") else site + "/"
        candidates.extend([
            urljoin(site_base, "void.ttl"),
            site,
        ])

    seen: set[str] = set()
    return [candidate for candidate in candidates if not (candidate in seen or seen.add(candidate))]


def _document_url_from_uri(uri: str) -> str:
    return urldefrag(str(uri))[0]


def _uri_host_matches(uri: Any, endpoint: str) -> bool:
    uri_host = urlparse(str(uri)).hostname
    endpoint_host = urlparse(endpoint).hostname
    return bool(uri_host and endpoint_host and uri_host.lower() == endpoint_host.lower())


def _endpoint_uri_variants(endpoint: str) -> set[URIRef]:
    variants = {endpoint}
    if endpoint.startswith("http://"):
        variants.add("https://" + endpoint[7:])
    elif endpoint.startswith("https://"):
        variants.add("http://" + endpoint[8:])
    return {URIRef(variant) for variant in variants}


def _dataset_site_uri_variants(endpoint: str) -> set[URIRef]:
    variants: set[str] = set()
    for site in _dataset_site_urls(endpoint):
        variants.add(site)
        variants.add(site.rstrip("/") + "/")
    return {URIRef(variant) for variant in variants if variant}


def _object_matches_endpoint(value: Any, endpoint: str) -> bool:
    value_text = str(value).strip()
    if not value_text:
        return False
    endpoint_values = {str(uri) for uri in _endpoint_uri_variants(endpoint)}
    dataset_site_values = {str(uri) for uri in _dataset_site_uri_variants(endpoint)}
    return (
        value_text in endpoint_values
        or value_text in dataset_site_values
        or _uri_host_matches(value_text, endpoint)
    )


def _dataset_match_score(
        graph: Graph,
        dataset: Any,
        endpoint: str,
        preferred_dataset_nodes: set[Any] | None = None
) -> int:
    score = 0
    preferred_dataset_nodes = preferred_dataset_nodes or set()
    if dataset in preferred_dataset_nodes:
        score += 12
    endpoint_refs = _endpoint_uri_variants(endpoint)
    dataset_site_refs = _dataset_site_uri_variants(endpoint)

    if dataset in endpoint_refs or dataset in dataset_site_refs:
        score += 8
    if isinstance(dataset, URIRef) and _uri_host_matches(dataset, endpoint):
        score += 2

    for endpoint_ref in endpoint_refs:
        if (dataset, VOID_SPARQL_ENDPOINT, endpoint_ref) in graph:
            score += 10
        if (dataset, SD_URL, endpoint_ref) in graph:
            score += 10

    for dataset_site_ref in dataset_site_refs:
        if (dataset, FOAF_HOMEPAGE, dataset_site_ref) in graph:
            score += 6
        if (dataset, VOID_ROOT_RESOURCE, dataset_site_ref) in graph:
            score += 6

    same_host_predicates = (
        VOID_SPARQL_ENDPOINT,
        VOID_DATA_DUMP,
        VOID_ROOT_RESOURCE,
        VOID_URI_LOOKUP_ENDPOINT,
        FOAF_HOMEPAGE,
        SD_URL,
        DCAT_LANDING_PAGE,
        DCAT_ACCESS_URL,
        DCAT_DOWNLOAD_URL,
        DCAT_ENDPOINT_URL,
    )
    if any(
            _object_matches_endpoint(value, endpoint)
            for predicate in same_host_predicates
            for value in graph.objects(dataset, predicate)
    ):
        score += 3

    return score


def _select_relevant_void_datasets(
        graph: Graph,
        endpoint: str,
        preferred_dataset_nodes: set[Any] | None = None
) -> set[Any]:
    endpoint_refs = _endpoint_uri_variants(endpoint)
    preferred_dataset_nodes = preferred_dataset_nodes or set()

    dataset_nodes = {
        node
        for node in preferred_dataset_nodes
        if (node, None, None) in graph or (None, None, node) in graph
    }

    for endpoint_ref in endpoint_refs:
        dataset_nodes.update(graph.subjects(VOID_SPARQL_ENDPOINT, endpoint_ref))
        dataset_nodes.update(graph.subjects(SD_URL, endpoint_ref))
    dataset_nodes.update(graph.objects(None, VOID_IN_DATASET))

    for description in graph.subjects(RDF.type, VOID_DATASET_DESCRIPTION):
        dataset_nodes.update(graph.objects(description, FOAF_PRIMARY_TOPIC))
        dataset_nodes.update(graph.objects(description, FOAF_TOPIC))

    candidates = set(graph.subjects(RDF.type, VOID_DATASET))
    candidates.update(graph.subjects(RDF.type, SD_DATASET))
    candidates.update(graph.subjects(RDF.type, SD_GRAPH))
    candidates.update(graph.subjects(RDF.type, DCAT_DATASET))
    candidates.update(graph.subjects(RDF.type, SCHEMA_DATASET))
    candidates.update(graph.subjects(RDF.type, SCHEMA_HTTPS_DATASET))
    candidates.update(graph.subjects(RDF.type, DCTYPE_DATASET))
    candidates.update(graph.subjects(RDF.type, QB_DATASET))
    candidates.update(graph.subjects(RDF.type, ADMS_ASSET))
    candidates.update(graph.objects(None, SD_DEFAULT_DATASET_DESCRIPTION))
    candidates.update(graph.objects(None, SD_DEFAULT_GRAPH))
    candidates.update(graph.objects(None, SD_GRAPH_PROP))

    all_candidates = dataset_nodes.union(candidates)
    if all_candidates:
        if len(all_candidates) == 1:
            dataset_nodes = all_candidates
        else:
            scored = {
                dataset: _dataset_match_score(graph, dataset, endpoint, preferred_dataset_nodes)
                for dataset in all_candidates
            }
            dataset_nodes = {dataset for dataset, score in scored.items() if score > 0}

    if not dataset_nodes and not candidates:
        for predicate in (
            DCTERMS.title,
            DCTERMS.description,
            DCTERMS.creator,
            DCTERMS.license,
            DCTERMS.subject,
            VOID_SPARQL_ENDPOINT,
            VOID_DATA_DUMP,
            VOID_VOCABULARY,
            VOID_TRIPLES,
            VOID_ENTITIES,
            VOID_CLASS_PARTITION,
            VOID_PROPERTY_PARTITION,
            FOAF_HOMEPAGE,
            SD_URL,
            SD_DEFAULT_DATASET_DESCRIPTION,
            SD_DEFAULT_GRAPH,
            SD_GRAPH_PROP,
            DCAT_LANDING_PAGE,
            DCAT_ACCESS_URL,
            DCAT_DOWNLOAD_URL,
            DCAT_ENDPOINT_URL,
        ):
            dataset_nodes.update(graph.subjects(predicate, None))

    return dataset_nodes


def _serialize_term(value: Any) -> dict[str, str]:
    if isinstance(value, URIRef):
        return {"type": "uri", "value": str(value)}
    if isinstance(value, Literal):
        item = {"type": "literal", "value": str(value)}
        if value.language:
            item["lang"] = value.language
        if value.datatype:
            item["datatype"] = str(value.datatype)
        return item
    return {"type": "blank", "value": str(value)}


def _extract_all_void_dataset_triples(graph: Graph, dataset_nodes: set[Any]) -> list[dict[str, Any]]:
    triples: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    visited_nodes: set[str] = set()

    def _visit(subject: Any, root_dataset: Any) -> None:
        subject_key = str(subject)
        if subject_key in visited_nodes:
            return
        visited_nodes.add(subject_key)

        for predicate, obj in graph.predicate_objects(subject):
            key = (str(subject), str(predicate), str(obj))
            if key not in seen:
                seen.add(key)
                triples.append({
                    "dataset": _serialize_term(root_dataset),
                    "subject": _serialize_term(subject),
                    "predicate": str(predicate),
                    "object": _serialize_term(obj),
                })
            if isinstance(obj, BNode):
                _visit(obj, root_dataset)

    for dataset in dataset_nodes:
        _visit(dataset, dataset)
    return triples


def _metadata_has_values(metadata: dict[str, Any]) -> bool:
    return any(metadata.get(key) for key in metadata)


def _merge_void_metadata(primary: dict[str, Any] | None, fallback: dict[str, Any] | None) -> dict[str, Any]:
    primary = primary or {}
    fallback = fallback or {}
    if not primary:
        return fallback
    if not fallback:
        return primary

    merged = dict(primary)
    for key in (
        "title", "dsc", "creator", "contributor", "publisher", "source", "identifier",
        "date", "created", "issued", "modified",
        "license", "sbj", "download", "voc", "sparql"
    ):
        merged[key] = _merge_lists(primary.get(key), fallback.get(key))
    merged["statistics"] = _merge_statistics(primary.get("statistics"), fallback.get("statistics"))
    merged["class_partitions"] = _merge_partitions(
        primary.get("class_partitions"), fallback.get("class_partitions"), "class", "entities"
    )
    merged["property_partitions"] = _merge_partitions(
        primary.get("property_partitions"), fallback.get("property_partitions"), "property", "triples"
    )
    merged["same_as_links"] = aggregate_same_as_links(
        (primary.get("same_as_links") or []) + (fallback.get("same_as_links") or [])
    )
    merged["void_metadata"] = _dedupe_void_metadata(
        (primary.get("void_metadata") or []) + (fallback.get("void_metadata") or [])
    )
    return merged


def _dedupe_void_metadata(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for item in items:
        if not isinstance(item, dict):
            continue
        dataset = item.get("dataset", {}).get("value") if isinstance(item.get("dataset"), dict) else ""
        subject = item.get("subject", {}).get("value") if isinstance(item.get("subject"), dict) else ""
        predicate = str(item.get("predicate") or "")
        obj = item.get("object", {}).get("value") if isinstance(item.get("object"), dict) else ""
        key = (str(dataset), str(subject), predicate, str(obj))
        if key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result


async def _fetch_rdf_graph(session: aiohttp.ClientSession, url: str, timeout: int) -> Graph | None:
    headers = {
        "Accept": VOID_RDF_ACCEPT,
        "User-Agent": "KGSum/1.0 (+https://github.com/isislab-unisa/KGSum)"
    }
    kwargs: dict[str, Any] = {
        "headers": headers,
        "timeout": aiohttp.ClientTimeout(total=timeout),
        "allow_redirects": True,
    }
    if url.startswith("https://"):
        kwargs["ssl"] = SSL_CONTEXT

    try:
        async with session.get(url, **kwargs) as response:
            if response.status >= 400:
                logger.debug(f"[VOID-DISCOVERY] {url} returned HTTP {response.status}")
                return None
            body = await response.text()
            if not body.strip():
                return None
            final_url = str(response.url)
            content_type = response.headers.get("Content-Type", "")
    except Exception as e:
        logger.debug(f"[VOID-DISCOVERY] Error fetching {url}: {e}")
        return None

    guessed_format = _guess_rdf_format(final_url, content_type)
    formats = [guessed_format] if guessed_format else []
    formats.extend(fmt for fmt in ["turtle", "xml", "nt", "json-ld", "n3", "rdfa"] if fmt not in formats)

    for rdf_format in formats:
        try:
            graph = Graph()
            graph.parse(data=body, publicID=final_url, format=rdf_format)
            if len(graph) > 0:
                logger.info(f"[VOID-DISCOVERY] Parsed VoID candidate {final_url} as {rdf_format}")
                return graph
        except Exception:
            continue

    logger.debug(f"[VOID-DISCOVERY] Could not parse RDF from {final_url}; type={content_type}")
    return None


def _node_values(graph: Graph, node: Any, predicates: tuple[URIRef, ...]) -> list[str]:
    values: list[str] = []
    for predicate in predicates:
        for value in graph.objects(node, predicate):
            text = str(value).strip()
            if text:
                values.append(text)
    return _dedupe(values)


DUMP_VALUE_PREDICATES = (
    VOID_DATA_DUMP,
    DCAT_DOWNLOAD_URL,
    DCAT_ACCESS_URL,
    SCHEMA_CONTENT_URL,
    SCHEMA_HTTPS_CONTENT_URL,
)
DUMP_CONTAINER_PREDICATES = (
    DCAT_DISTRIBUTION,
    SCHEMA_DISTRIBUTION,
    SCHEMA_HTTPS_DISTRIBUTION,
)


def _predicate_local_name(predicate: Any) -> str:
    text = str(predicate)
    if "#" in text:
        return text.rsplit("#", 1)[-1]
    return text.rstrip("/").rsplit("/", 1)[-1]


def _looks_like_dump_predicate(predicate: Any) -> bool:
    local_name = _predicate_local_name(predicate).lower()
    return (
        "dump" in local_name
        or "download" in local_name
        or local_name in {"accessurl", "contenturl", "distribution"}
    )


def _extract_download_values(graph: Graph, dataset: Any) -> list[str]:
    downloads: list[str] = []
    visited: set[str] = set()

    def _visit(node: Any) -> None:
        node_key = str(node)
        if node_key in visited:
            return
        visited.add(node_key)

        for predicate, obj in graph.predicate_objects(node):
            predicate_is_dump = predicate in DUMP_VALUE_PREDICATES or _looks_like_dump_predicate(predicate)
            if predicate_is_dump and isinstance(obj, URIRef):
                downloads.append(str(obj))
            if predicate in DUMP_CONTAINER_PREDICATES or _predicate_local_name(predicate).lower() == "distribution":
                _visit(obj)

    _visit(dataset)
    return _dedupe(downloads)


def _literal_or_uri_value(value: Any) -> str:
    if isinstance(value, Literal):
        return str(value).strip()
    return str(value).strip()


def _positive_int(value: Any) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return 0
    return number if number > 0 else 0


def _dedupe(values: Any) -> list[str]:
    if values is None:
        return []
    if not isinstance(values, list):
        values = [values]
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        if isinstance(value, list):
            for nested in _dedupe(value):
                if nested not in seen:
                    seen.add(nested)
                    result.append(nested)
            continue
        text = str(value).strip()
        if text and text not in seen:
            seen.add(text)
            result.append(text)
    return result


def _merge_lists(*values: Any) -> list[str]:
    merged: list[str] = []
    for value in values:
        merged.extend(_dedupe(value))
    return _dedupe(merged)


def _merge_statistics(primary: dict[str, Any] | None, fallback: dict[str, Any] | None) -> dict[str, int]:
    primary = primary or {}
    fallback = fallback or {}
    merged: dict[str, int] = {}
    for key in ("triples", "entities"):
        value = _positive_int(primary.get(key))
        if not value:
            value = _positive_int(fallback.get(key))
        if value:
            merged[key] = value
    return merged


def _merge_partitions(primary: Any, fallback: Any, uri_key: str, count_key: str) -> list[dict[str, Any]]:
    merged: dict[str, int] = {}

    def _visit(items: Any, replace_existing: bool) -> None:
        if isinstance(items, dict):
            items = [items]
        if not isinstance(items, list):
            return
        for item in items:
            if not isinstance(item, dict):
                continue
            uri = str(item.get(uri_key) or "").strip()
            if not uri:
                continue
            count = _positive_int(item.get(count_key))
            if uri not in merged or replace_existing or not merged[uri]:
                merged[uri] = count

    _visit(primary, True)
    _visit(fallback, False)
    return [
        {uri_key: uri, count_key: count}
        for uri, count in sorted(merged.items(), key=lambda pair: (-pair[1], pair[0]))
    ]


def _extract_void_metadata_from_graph(
        graph: Graph,
        endpoint: str,
        preferred_dataset_nodes: set[Any] | None = None
) -> dict[str, Any]:
    dataset_nodes = _select_relevant_void_datasets(graph, endpoint, preferred_dataset_nodes)

    metadata: dict[str, Any] = {
        "title": [],
        "dsc": [],
        "creator": [],
        "contributor": [],
        "publisher": [],
        "source": [],
        "identifier": [],
        "date": [],
        "created": [],
        "issued": [],
        "modified": [],
        "license": [],
        "sbj": [],
        "download": [],
        "voc": [],
        "sparql": [],
        "statistics": {},
        "class_partitions": [],
        "property_partitions": [],
        "same_as_links": [],
        "void_metadata": [],
    }

    for dataset in dataset_nodes:
        metadata["title"].extend(_node_values(graph, dataset, (DCTERMS.title, RDFS.label)))
        metadata["dsc"].extend(_node_values(graph, dataset, (DCTERMS.description,)))
        metadata["creator"].extend(_node_values(graph, dataset, (DCTERMS.creator,)))
        metadata["contributor"].extend(_node_values(graph, dataset, (DCTERMS.contributor,)))
        metadata["publisher"].extend(_node_values(graph, dataset, (DCTERMS.publisher,)))
        metadata["source"].extend(_node_values(graph, dataset, (DCTERMS.source,)))
        metadata["identifier"].extend(_node_values(graph, dataset, (DCTERMS.identifier,)))
        metadata["date"].extend(_node_values(graph, dataset, (DCTERMS.date,)))
        metadata["created"].extend(_node_values(graph, dataset, (DCTERMS.created,)))
        metadata["issued"].extend(_node_values(graph, dataset, (DCTERMS.issued,)))
        metadata["modified"].extend(_node_values(graph, dataset, (DCTERMS.modified,)))
        metadata["license"].extend(_node_values(graph, dataset, (DCTERMS.license,)))
        metadata["sbj"].extend(_node_values(graph, dataset, (DCTERMS.subject,)))
        metadata["download"].extend(_extract_download_values(graph, dataset))
        metadata["voc"].extend(_node_values(graph, dataset, (VOID_VOCABULARY,)))
        metadata["sparql"].extend(_node_values(graph, dataset, (VOID_SPARQL_ENDPOINT,)))

        triples = next(graph.objects(dataset, VOID_TRIPLES), None)
        entities = next(graph.objects(dataset, VOID_ENTITIES), None)
        if triples is not None:
            metadata["statistics"]["triples"] = _positive_int(triples)
        if entities is not None:
            metadata["statistics"]["entities"] = _positive_int(entities)

        for partition in graph.objects(dataset, VOID_CLASS_PARTITION):
            class_uri = next(graph.objects(partition, VOID_CLASS), None)
            if class_uri:
                metadata["class_partitions"].append({
                    "class": _literal_or_uri_value(class_uri),
                    "entities": _positive_int(next(graph.objects(partition, VOID_ENTITIES), 0)),
                })

        for partition in graph.objects(dataset, VOID_PROPERTY_PARTITION):
            property_uri = next(graph.objects(partition, VOID_PROPERTY), None)
            if property_uri:
                metadata["property_partitions"].append({
                    "property": _literal_or_uri_value(property_uri),
                    "triples": _positive_int(next(graph.objects(partition, VOID_TRIPLES), 0)),
                })

    for linkset in graph.subjects(RDF.type, VOID_LINKSET):
        predicates = list(graph.objects(linkset, VOID_LINK_PREDICATE))
        if predicates and OWL.sameAs not in predicates:
            continue
        targets = list(graph.objects(linkset, VOID_TARGET))
        targets.extend(graph.objects(linkset, VOID_OBJECTS_TARGET))
        count = _positive_int(next(graph.objects(linkset, VOID_TRIPLES), 0))
        for target in targets:
            target_text = str(target)
            if target_text and target_text != endpoint and target not in dataset_nodes:
                metadata["same_as_links"].append({"dataset": target_text, "count": count or 1})

    for key in (
        "title", "dsc", "creator", "contributor", "publisher", "source", "identifier",
        "date", "created", "issued", "modified",
        "license", "sbj", "download", "voc", "sparql"
    ):
        metadata[key] = _dedupe(metadata[key])
    metadata["same_as_links"] = aggregate_same_as_links(metadata["same_as_links"])
    metadata["statistics"] = {key: value for key, value in metadata["statistics"].items() if value}
    metadata["void_metadata"] = _extract_all_void_dataset_triples(graph, dataset_nodes)
    return metadata


async def async_discover_standard_void_metadata(endpoint: str, timeout: int = 60) -> dict[str, Any]:
    if not _is_remote_http_url(endpoint):
        return {}

    logger.info(f"[VOID-DISCOVERY] Trying standard VoID discovery for remote host: {endpoint}")
    async with aiohttp.ClientSession() as session:
        dataset_doc_graph = await _fetch_rdf_graph(session, endpoint, timeout)
        if dataset_doc_graph:
            dataset_uris = {
                dataset
                for dataset in dataset_doc_graph.objects(None, VOID_IN_DATASET)
                if isinstance(dataset, URIRef)
            }
            for dataset_uri in dataset_uris:
                void_document_url = _document_url_from_uri(str(dataset_uri))
                if not void_document_url:
                    continue
                graph = await _fetch_rdf_graph(session, void_document_url, timeout)
                if not graph:
                    graph = dataset_doc_graph
                metadata = _extract_void_metadata_from_graph(graph, endpoint, {dataset_uri})
                if _metadata_has_values(metadata):
                    logger.info(
                        "[VOID-DISCOVERY] Found VoID metadata via void:inDataset "
                        f"backlink: {dataset_uri}"
                    )
                    return metadata

        for site in _dataset_site_urls(endpoint):
            well_known_url = _well_known_void_url(site)
            graph = await _fetch_rdf_graph(session, well_known_url, timeout)
            if graph:
                metadata = _extract_void_metadata_from_graph(graph, endpoint)
                if _metadata_has_values(metadata):
                    logger.info(f"[VOID-DISCOVERY] Found VoID metadata at {well_known_url}")
                    return metadata

        for candidate in _published_void_candidates(endpoint):
            graph = await _fetch_rdf_graph(session, candidate, timeout)
            if not graph:
                continue
            metadata = _extract_void_metadata_from_graph(graph, endpoint)
            if _metadata_has_values(metadata):
                logger.info(f"[VOID-DISCOVERY] Found published VoID metadata at {candidate}")
                return metadata

    logger.info(f"[VOID-DISCOVERY] No VoID descriptor found for {endpoint}")
    return {}


async def _fetch_query(
        session: aiohttp.ClientSession,
        endpoint: str,
        query: str,
        timeout: int,
        max_retries: int = 3
) -> str:
    headers = {
        "Accept": SPARQL_RESULTS_ACCEPT,
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36"
    }
    timeout_cfg = aiohttp.ClientTimeout(total=timeout)

    if endpoint.startswith("http://"):
        https_endpoint = "https://" + endpoint[7:]
        http_endpoint = endpoint
    elif endpoint.startswith("https://"):
        https_endpoint = endpoint
        http_endpoint = "http://" + endpoint[8:]
    else:
        https_endpoint = "https://" + endpoint
        http_endpoint = "http://" + endpoint

    async def _attempt(target_url: str, method: str, use_ssl: Any) -> tuple[int, str, str, str, Exception | None]:
        kwargs = {
            "headers": headers,
            "timeout": timeout_cfg,
            "allow_redirects": True,
        }

        if target_url.startswith("https://"):
            kwargs["ssl"] = use_ssl

        if method == "POST":
            kwargs["data"] = {"query": query, "format": "application/sparql-results+xml"}
        else:
            kwargs["params"] = {"query": query, "format": "application/sparql-results+xml"}

        try:
            req = session.post(target_url, **kwargs) if method == "POST" else session.get(target_url, **kwargs)
            async with req as response:
                body = await response.text()
                return response.status, response.reason, response.headers.get("Content-Type", ""), body, None
        except Exception as e:
            return 0, "", "", "", e

    strategies = [
        (https_endpoint, "POST", SSL_CONTEXT),
        (https_endpoint, "GET", SSL_CONTEXT),
        (https_endpoint, "POST", False),
        (https_endpoint, "GET", False),
        (http_endpoint, "POST", False),
        (http_endpoint, "GET", False)
    ]

    last_error = "Unknown error"

    for attempt in range(max_retries):
        for target_url, method, use_ssl in strategies:
            status, reason, content_type, body, exc = await _attempt(target_url, method, use_ssl)

            if exc:
                last_error = f"Exception at {target_url} ({method}): {type(exc).__name__} - {str(exc)}"
                continue

            if status in (429, 500, 502, 503, 504):
                last_error = f"HTTP {status} {reason} at {target_url}"
                await asyncio.sleep(2 ** attempt)
                break

            if status >= 400:
                clean_body = _one_line_snippet(body, limit=80)
                last_error = f"HTTP {status} {reason} at {target_url} ({method}); body={clean_body}"
                continue

            is_xml = "xml" in content_type.lower() or body.lstrip().startswith("<")
            if status == 200 and is_xml:
                return body
            else:
                clean_body = _one_line_snippet(body, limit=80)
                last_error = f"Non-XML response at {target_url} ({method}); type={content_type}; body={clean_body}"
                continue

    raise RuntimeError(f"Failed after {max_retries} retries. Last issue: {last_error}")


async def async_discover_void_metadata_by_dataset_query(
        endpoint: str,
        timeout: int = 120,
        include_alternative_dataset_vocabularies: bool = False
) -> dict[str, Any]:
    metadata = await _discover_dataset_metadata_by_type_query(
        endpoint,
        timeout,
        "void:Dataset",
        "void:Dataset"
    )
    if metadata or not include_alternative_dataset_vocabularies:
        return metadata

    return await _discover_dataset_metadata_by_type_query(
        endpoint,
        timeout,
        "DCAT/schema/dctype/qb dataset",
        "?datasetType",
        values="""
            VALUES ?datasetType {
                dcat:Dataset
                schema:Dataset
                schemahttps:Dataset
                dctype:Dataset
                qb:DataSet
                adms:Asset
            }
        """
    )


async def _discover_dataset_metadata_by_type_query(
        endpoint: str,
        timeout: int,
        label: str,
        dataset_type_pattern: str,
        values: str = ""
) -> dict[str, Any]:
    logger.info(f"[DATASET-QUERY] Searching {label} metadata through endpoint query: {endpoint}")
    query = f"""
        PREFIX void: <http://rdfs.org/ns/void#>
        PREFIX dcat: <http://www.w3.org/ns/dcat#>
        PREFIX schema: <http://schema.org/>
        PREFIX schemahttps: <https://schema.org/>
        PREFIX dctype: <http://purl.org/dc/dcmitype/>
        PREFIX qb: <http://purl.org/linked-data/cube#>
        PREFIX adms: <http://www.w3.org/ns/adms#>
        SELECT *
        WHERE {{
            {values}
            ?s a {dataset_type_pattern} .
            ?s ?p ?o .
        }}
    """
    graph = Graph()
    async with aiohttp.ClientSession() as session:
        try:
            result_text = await _fetch_query(session, endpoint, query, timeout)
            root = eT.fromstring(result_text)
            ns = {"sparql": "http://www.w3.org/2005/sparql-results#"}
            for result in root.findall(".//sparql:result", ns):
                subject = _sparql_xml_binding_to_rdflib(result.find('./sparql:binding[@name="s"]/*', ns))
                predicate = _sparql_xml_binding_to_rdflib(result.find('./sparql:binding[@name="p"]/*', ns))
                obj = _sparql_xml_binding_to_rdflib(result.find('./sparql:binding[@name="o"]/*', ns))
                if subject is not None and isinstance(predicate, URIRef) and obj is not None:
                    graph.add((subject, predicate, obj))
        except Exception as e:
            logger.warning(f"[DATASET-QUERY] Query execution error for {label}: {e}. Endpoint: {endpoint}")
            return {}

    if len(graph) == 0:
        return {}

    metadata = _extract_void_metadata_from_graph(graph, endpoint)
    if _metadata_has_values(metadata):
        logger.info(f"[DATASET-QUERY] Found {label} metadata through endpoint query: {endpoint}")
        return metadata
    return {}


def _sparql_xml_binding_to_rdflib(node: eT.Element | None) -> Any:
    if node is None:
        return None
    tag = node.tag.rsplit("}", 1)[-1]
    text = node.text or ""
    if tag == "uri":
        return URIRef(text)
    if tag == "literal":
        lang = node.attrib.get("{http://www.w3.org/XML/1998/namespace}lang")
        datatype = node.attrib.get("datatype")
        return Literal(text, lang=lang, datatype=URIRef(datatype) if datatype else None)
    if tag == "bnode":
        return BNode(text)
    return Literal(text)


async def async_select_remote_vocabularies(endpoint: str, timeout: int = 300) -> list[str]:
    logger.info(f"[VOC] Starting vocabulary query for endpoint: {endpoint}")
    vocabularies: set[str] = set()
    query = """
        SELECT DISTINCT ?predicate
        WHERE {
            ?subject ?predicate ?object.
        }
        LIMIT 1000
    """
    async with aiohttp.ClientSession() as session:
        try:
            result_text = await _fetch_query(session, endpoint, query, timeout)
            root = eT.fromstring(result_text)
            ns = {"sparql": "http://www.w3.org/2005/sparql-results#"}
            bindings = root.findall('.//sparql:binding[@name="predicate"]/sparql:uri', ns)

            if not bindings:
                logger.debug(f"[VOC] No predicate bindings found at endpoint {endpoint}.")
            for binding in bindings:
                predicate_uri = binding.text or ""
                if "#" in predicate_uri:
                    vocabulary_uri = predicate_uri.split("#")[0]
                elif "/" in predicate_uri:
                    parts = predicate_uri.rstrip("/").split("/")
                    vocabulary_uri = "/".join(parts[:-1]) if len(parts) > 1 else predicate_uri
                else:
                    vocabulary_uri = predicate_uri

                if not vocabulary_uri:
                    continue

                vocabularies.add(vocabulary_uri)

        except Exception as e:
            logger.warning(f"[VOC] Query execution error: {e}. Endpoint: {endpoint}")
            return []

    logger.info(f"[VOC] Finished vocabulary query for endpoint: {endpoint} (found {len(vocabularies)} vocabularies)")
    return list(vocabularies)


async def async_select_remote_class_partitions(endpoint: str, timeout: int = 300) -> list[dict[str, Any]]:
    logger.info(f"[CLS] Starting class query for endpoint: {endpoint}")
    partitions: list[dict[str, Any]] = []
    query = """
        SELECT ?class (COUNT(?instance) AS ?instanceCount)
        WHERE {
            ?instance a ?class .
        }
        GROUP BY ?class
        ORDER BY DESC(?instanceCount)
        LIMIT 1000
    """
    async with aiohttp.ClientSession() as session:
        try:
            result_text = await _fetch_query(session, endpoint, query, timeout)
            root = eT.fromstring(result_text)
            ns = {"sparql": "http://www.w3.org/2005/sparql-results#"}
            results = root.findall(".//sparql:result", ns)
            if not results:
                logger.debug(f"[CURI] No class bindings found at endpoint {endpoint}.")
            for result in results:
                class_node = result.find('./sparql:binding[@name="class"]/sparql:uri', ns)
                count_node = result.find('./sparql:binding[@name="instanceCount"]/*', ns)
                class_uri = class_node.text if class_node is not None else ""
                if not class_uri:
                    continue
                try:
                    count = int((count_node.text if count_node is not None else "0") or "0")
                except ValueError:
                    count = 0
                partitions.append({"class": class_uri, "entities": count})
        except Exception as e:
            logger.warning(f"[CURI] Query execution error: {e}. Endpoint: {endpoint}")
            return []
    logger.info(f"[CURI] Finished class query for endpoint: {endpoint} (found {len(partitions)} classes)")
    return partitions


async def async_select_remote_class(endpoint: str, timeout: int = 300) -> list[str]:
    return [partition["class"] for partition in await async_select_remote_class_partitions(endpoint, timeout)]


async def async_select_remote_same_as_objects(endpoint: str, timeout: int = 300) -> list[str]:
    logger.info(f"[CON] Starting paginated owl:sameAs query for endpoint: {endpoint}")
    connections: list[str] = []
    async with aiohttp.ClientSession() as session:
        offset = 0
        while True:
            limit = SAME_AS_PAGE_SIZE
            if MAX_SAME_AS_LINKS > 0:
                remaining = MAX_SAME_AS_LINKS - len(connections)
                if remaining <= 0:
                    logger.info(f"[CON] Reached MAX_SAME_AS_LINKS={MAX_SAME_AS_LINKS} for endpoint: {endpoint}")
                    break
                limit = min(limit, remaining)

            query = f"""
                PREFIX owl: <http://www.w3.org/2002/07/owl#>
                SELECT ?o
                WHERE {{
                    ?s owl:sameAs ?o .
                    FILTER(isIRI(?o))
                }}
                LIMIT {limit}
                OFFSET {offset}
            """
            try:
                result_text = await _fetch_query(session, endpoint, query, timeout)
                root = eT.fromstring(result_text)
                ns = {"sparql": "http://www.w3.org/2005/sparql-results#"}
                bindings = root.findall('.//sparql:binding[@name="o"]/sparql:uri', ns)
                if not bindings:
                    break
                for binding in bindings:
                    obj_uri = binding.text or ""
                    if obj_uri:
                        connections.append(obj_uri)
                if len(bindings) < limit:
                    break
                offset += limit
            except Exception as e:
                logger.warning(f"[CON] Paginated query error at offset {offset}: {e}. Endpoint: {endpoint}")
                break

    logger.info(f"[CON] Finished paginated owl:sameAs query for endpoint: {endpoint} (found {len(connections)} links)")
    return connections


async def async_select_remote_connection(endpoint: str, timeout: int = 300) -> list[str]:
    return sorted(set(await async_select_remote_same_as_objects(endpoint, timeout)))[:1000]


async def async_select_remote_same_as_links(endpoint: str, timeout: int = 300) -> list[dict[str, Any]]:
    connections = await async_select_remote_same_as_objects(endpoint, timeout)
    same_as_links = aggregate_same_as_links(connections)
    logger.info(f"[LINKSET] Finished owl:sameAs linkset aggregation for endpoint: {endpoint} (found {len(same_as_links)} linked KGs)")
    return same_as_links


async def async_select_remote_label(endpoint: str, timeout: int = 300, en: bool = True) -> list[str]:
    logger.info(f"[LAB] Starting label query for endpoint: {endpoint} (en={en})")
    labels: list[str] = []
    ns = {"sparql": "http://www.w3.org/2005/sparql-results#"}
    query = """
        PREFIX skosxl: <http://www.w3.org/2008/05/skos-xl#>
        PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
        PREFIX skos: <http://www.w3.org/2004/02/skos/core#>
        PREFIX foaf: <http://xmlns.com/foaf/0.1/>
        PREFIX awol: <http://bblfish.net/work/atom-owl/2006-06-06/#>
        PREFIX wdrs: <http://www.w3.org/2007/05/powder-s#>
        PREFIX schema: <http://schema.org/>
        SELECT DISTINCT ?o
        WHERE {
            ?s a ?label .
            { ?s rdfs:label ?o } UNION
            { ?s foaf:name ?o } UNION
            { ?s skos:prefLabel ?o } UNION
            { ?s rdfs:comment ?o } UNION
            { ?s awol:label ?o } UNION
            { ?s skos:note ?o } UNION
            { ?s wdrs:text ?o } UNION
            { ?s skosxl:prefLabel ?o } UNION
            { ?s skosxl:literalForm ?o } UNION
            { ?s schema:name ?o }
    """
    if en:
        query += 'FILTER(langMatches(lang(?o), "en")) '
    query += "} LIMIT 1000"

    async with aiohttp.ClientSession() as session:
        try:
            result_text = await _fetch_query(session, endpoint, query, timeout)
            root = eT.fromstring(result_text)
            bindings = root.findall('.//sparql:binding[@name="o"]/sparql:literal', ns)
            if not bindings:
                logger.debug(f"[LAB] No label bindings (primary) at endpoint {endpoint}. Trying fallback.")
                query_fallback = """
                    PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
                    SELECT DISTINCT ?o
                    WHERE {
                        ?s rdfs:label ?o
                """
                if en:
                    query_fallback += 'FILTER(langMatches(lang(?o), "en")) '
                query_fallback += "} LIMIT 1000"
                result_text = await _fetch_query(session, endpoint, query_fallback, timeout)
                root = eT.fromstring(result_text)
                bindings = root.findall('.//sparql:binding[@name="o"]/sparql:literal', ns)
            for binding in bindings or []:
                lit = binding.text or ""
                if lit:
                    labels.append(lit)
        except Exception as e:
            logger.warning(f"[LAB] Query execution error: {e}. Endpoint: {endpoint}")
            return []
    logger.info(f"[LAB] Finished label query for endpoint: {endpoint} (found {len(labels)} labels)")
    return labels


async def async_select_remote_title(endpoint: str, timeout: int = 300) -> str:
    logger.info(f"[TITLE] Starting title query for endpoint: {endpoint}")
    title = ""
    query = """
        PREFIX dcterms: <http://purl.org/dc/terms/>
        SELECT ?classUri
        WHERE {
            ?type dcterms:title ?classUri .
        }
        LIMIT 1
    """
    async with aiohttp.ClientSession() as session:
        try:
            result_text = await _fetch_query(session, endpoint, query, timeout)
            root = eT.fromstring(result_text)
            ns = {"sparql": "http://www.w3.org/2005/sparql-results#"}
            bindings = root.findall('.//sparql:binding[@name="classUri"]/sparql:uri', ns)
            if not bindings:
                logger.debug(f"[TITLE] No title found at endpoint {endpoint}.")
            else:
                title = bindings[0].text or ""
        except Exception as e:
            logger.warning(f"[TITLE] Query execution error: {e}. Endpoint: {endpoint}")
            return ""
    logger.info(f"[TITLE] Finished title query for endpoint: {endpoint}")
    return title


async def async_select_remote_tlds(endpoint: str, limit: int = 1000, timeout: int = 300) -> list[str]:
    logger.info(f"[TLDS] Starting TLD query for endpoint: {endpoint}")
    tlds: set[str] = set()
    query = f"""
        SELECT DISTINCT ?o
        WHERE {{
            ?s ?p ?o .
            FILTER(isIRI(?o))
        }}
        LIMIT {limit}
    """
    try:
        async with aiohttp.ClientSession() as session:
            result_text = await _fetch_query(session, endpoint, query, timeout)
            root = eT.fromstring(result_text)
            ns = {"sparql": "http://www.w3.org/2005/sparql-results#"}
            bindings = root.findall('.//sparql:binding[@name="o"]/sparql:uri', ns)
            if not bindings:
                logger.debug(f"[TLDS] No TLD bindings found at endpoint {endpoint}.")
            for binding in bindings:
                url = binding.text
                if url and url.lower().startswith(("http://", "https://")):
                    url_parts = url.split('/')
                    if len(url_parts) >= 3:
                        host = url_parts[2]
                        host_parts = host.split('.')
                        if len(host_parts) >= 2:
                            tld = host_parts[-1]
                            if 1 < len(tld) <= 10:
                                tlds.add(tld)
                        else:
                            logger.debug(f"[TLDS] Cannot parse TLD from host: {host}")
                    else:
                        logger.debug(f"[TLDS] Cannot parse host from URL: {url}")
    except Exception as e:
        logger.warning(f"[TLDS] Query execution error: {e}. Endpoint: {endpoint}")
        return []
    logger.info(f"[TLDS] Finished TLD query for endpoint: {endpoint} (found {len(tlds)} TLDs)")
    return list(tlds)


async def async_select_remote_property_partitions(endpoint: str, timeout: int = 300) -> list[dict[str, Any]]:
    logger.info(f"[PROP] Starting property query for endpoint: {endpoint}")
    partitions: list[dict[str, Any]] = []
    query = f"""
        PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
        SELECT ?property (COUNT(?s) AS ?usageCount)
        WHERE {{
            ?s ?property ?o .
            FILTER (?property != rdf:type)
        }}
        GROUP BY ?property
        ORDER BY DESC(?usageCount)
        LIMIT 1000
    """
    async with aiohttp.ClientSession() as session:
        try:
            result_text = await _fetch_query(session, endpoint, query, timeout)
            root = eT.fromstring(result_text)
            ns = {"sparql": "http://www.w3.org/2005/sparql-results#"}
            results = root.findall(".//sparql:result", ns)
            if not results:
                logger.debug(f"[PURI] No property bindings found at endpoint {endpoint}.")
            for result in results:
                prop_node = result.find('./sparql:binding[@name="property"]/sparql:uri', ns)
                count_node = result.find('./sparql:binding[@name="usageCount"]/*', ns)
                prop_uri = prop_node.text if prop_node is not None else ""
                if not prop_uri:
                    continue
                try:
                    count = int((count_node.text if count_node is not None else "0") or "0")
                except ValueError:
                    count = 0
                partitions.append({"property": prop_uri, "triples": count})
        except Exception as e:
            logger.warning(f"[PURI] Query execution error: {e}. Endpoint: {endpoint}")
            return []
    logger.info(f"[PURI] Finished property query for endpoint: {endpoint} (found {len(partitions)} properties)")
    return partitions


async def async_select_remote_property(endpoint: str, timeout: int = 300) -> list[str]:
    return [partition["property"] for partition in await async_select_remote_property_partitions(endpoint, timeout)]


async def async_select_remote_statistics(endpoint: str, timeout: int = 120) -> dict[str, int]:
    logger.info(f"[STATS] Starting statistics query for endpoint: {endpoint}")
    query = """
        SELECT (COUNT(*) AS ?triples) (COUNT(DISTINCT ?s) AS ?entities)
        WHERE {
            ?s ?p ?o .
        }
    """
    async with aiohttp.ClientSession() as session:
        try:
            result_text = await _fetch_query(session, endpoint, query, timeout)
            root = eT.fromstring(result_text)
            ns = {"sparql": "http://www.w3.org/2005/sparql-results#"}
            triples_node = root.find('.//sparql:binding[@name="triples"]/*', ns)
            entities_node = root.find('.//sparql:binding[@name="entities"]/*', ns)
            triples = int((triples_node.text if triples_node is not None else "0") or "0")
            entities = int((entities_node.text if entities_node is not None else "0") or "0")
            return {"triples": triples, "entities": entities}
        except Exception as e:
            logger.warning(f"[STATS] Query execution error: {e}. Endpoint: {endpoint}")
            return {}


async def async_has_void_file(endpoint: str, timeout: int = 300) -> str | bool:
    logger.info(f"[VOID] Checking for VOID file at endpoint: {endpoint}")
    query = f"""
        PREFIX void: <http://rdfs.org/ns/void#>
        SELECT DISTINCT ?s
        WHERE {{
            ?s a void:Dataset ;
               void:sparqlEndpoint <{endpoint}> .
        }}
        LIMIT 1
    """
    async with aiohttp.ClientSession() as session:
        try:
            result_text = await _fetch_query(session, endpoint, query, timeout)
            root = eT.fromstring(result_text)
            ns = {"sparql": "http://www.w3.org/2005/sparql-results#"}
            bindings = root.findall('.//sparql:binding[@name="s"]/sparql:uri', ns)
            for binding in bindings:
                uri = binding.text or ""
                if uri:
                    logger.info(f"[VOID] VOID file found: {uri}")
                    return uri
            return False
        except Exception as e:
            logger.warning(f"[VOID] Error checking for VOID file: {e}. Endpoint: {endpoint}")
            return False


async def async_select_void_description(endpoint: str, timeout: int = 300, void_file: bool = False) -> list[str]:
    logger.info(f"[VDESC] Starting VOID description query for endpoint: {endpoint}")
    descriptions: set[str] = set()
    query = """
        PREFIX dcterms: <http://purl.org/dc/terms/>
        SELECT ?desc
        WHERE {
            ?s dcterms:description ?desc .
        }
        LIMIT 1
    """
    async with aiohttp.ClientSession() as session:
        try:
            result_text = await _fetch_query(session, endpoint, query, timeout)
            root = eT.fromstring(result_text)
            ns = {"sparql": "http://www.w3.org/2005/sparql-results#"}
            bindings = root.findall('.//sparql:binding[@name="desc"]/*', ns)
            for binding in bindings:
                desc_text = binding.text or ""
                if desc_text:
                    descriptions.add(desc_text)
            if not descriptions and not void_file:
                void_uri = await async_has_void_file(endpoint, timeout)
                if void_uri:
                    return await async_select_void_description(str(void_uri), timeout, True)
        except Exception as e:
            logger.warning(f"[DSC] Query execution error: {e}. Endpoint: {endpoint}")
            return []
    logger.info(f"[DSC] Finished VOID description query for endpoint: {endpoint}")
    return list(descriptions)


async def async_select_void_license(endpoint: str, timeout: int = 300, void_file: bool = False) -> list[str]:
    logger.info(f"[VLIC] Starting VOID license query for endpoint: {endpoint}")
    licenses: set[str] = set()
    query = """
        PREFIX dcterms: <http://purl.org/dc/terms/>
        SELECT ?desc
        WHERE {
            ?s dcterms:license ?desc .
        }
        LIMIT 1
    """
    async with aiohttp.ClientSession() as session:
        try:
            result_text = await _fetch_query(session, endpoint, query, timeout)
            root = eT.fromstring(result_text)
            ns = {"sparql": "http://www.w3.org/2005/sparql-results#"}
            bindings = root.findall('.//sparql:binding[@name="desc"]/*', ns)
            for binding in bindings:
                lic_text = binding.text or ""
                if lic_text:
                    licenses.add(lic_text)
            if not licenses and not void_file:
                void_uri = await async_has_void_file(endpoint, timeout)
                if void_uri:
                    return await async_select_void_license(str(void_uri), timeout, True)
        except Exception as e:
            logger.warning(f"[VLIC] Query execution error: {e}. Endpoint: {endpoint}")
            return []
    logger.info(f"[VLIC] Finished VOID license query for endpoint: {endpoint}")
    return list(licenses)


async def async_select_void_creator(endpoint: str, timeout: int = 300, void_file: bool = False) -> list[str]:
    logger.info(f"[VCRE] Starting VOID creator query for endpoint: {endpoint}")
    creators: set[str] = set()
    query = """
        PREFIX dcterms: <http://purl.org/dc/terms/>
        SELECT ?desc
        WHERE {
            ?s dcterms:creator ?desc .
        }
        LIMIT 1
    """
    async with aiohttp.ClientSession() as session:
        try:
            result_text = await _fetch_query(session, endpoint, query, timeout)
            root = eT.fromstring(result_text)
            ns = {"sparql": "http://www.w3.org/2005/sparql-results#"}
            bindings = root.findall('.//sparql:binding[@name="desc"]/*', ns)
            for binding in bindings:
                cre_text = binding.text or ""
                if cre_text:
                    creators.add(cre_text)
            if not creators and not void_file:
                void_uri = await async_has_void_file(endpoint, timeout)
                if void_uri:
                    return await async_select_void_creator(str(void_uri), timeout, True)
        except Exception as e:
            logger.warning(f"[VCRE] Query execution error: {e}. Endpoint: {endpoint}")
            return []
    logger.info(f"[VCRE] Finished VOID creator query for endpoint: {endpoint}")
    return list(creators)


async def async_select_void_download(endpoint: str, timeout: int = 300, void_file: bool = False) -> list[str]:
    logger.info(f"[DOWNLOAD] Starting VOID download query for endpoint: {endpoint}")
    downloadURL: set[str] = set()
    query = """
        PREFIX void: <http://rdfs.org/ns/void#>
        SELECT ?desc
        WHERE {
            ?s void:dataDump ?desc .
        }
        LIMIT 100
    """
    async with aiohttp.ClientSession() as session:
        try:
            result_text = await _fetch_query(session, endpoint, query, timeout)
            root = eT.fromstring(result_text)
            ns = {"sparql": "http://www.w3.org/2005/sparql-results#"}
            bindings = root.findall('.//sparql:binding[@name="desc"]/*', ns)
            for binding in bindings:
                cre_text = binding.text or ""
                if cre_text:
                    downloadURL.add(cre_text)
            if not downloadURL and not void_file:
                void_uri = await async_has_void_file(endpoint, timeout)
                if void_uri:
                    return await async_select_void_download(str(void_uri), timeout, True)
        except Exception as e:
            logger.warning(f"[DOWNLOAD] Query execution error: {e}. Endpoint: {endpoint}")
            return []
    logger.info(f"[DOWNLOAD] Finished VOID download query for endpoint: {endpoint}")
    return list(downloadURL)


async def async_select_void_subject_remote(endpoint: str, timeout: int = 300, void_file: bool = False) -> list[str]:
    logger.info(f"[SVJ] Starting VOID subject query for endpoint: {endpoint}")
    dataset_uris: set[str] = set()
    query = """
        PREFIX void: <http://rdfs.org/ns/void#>
        PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
        SELECT DISTINCT ?s
        WHERE {
            ?s rdf:type void:Dataset .
        }
        LIMIT 100
    """
    async with aiohttp.ClientSession() as session:
        try:
            result_text = await _fetch_query(session, endpoint, query, timeout)
            root = eT.fromstring(result_text)
            ns = {"sparql": "http://www.w3.org/2005/sparql-results#"}
            bindings = root.findall('.//sparql:binding[@name="s"]/sparql:uri', ns)
            for binding in bindings:
                uri = binding.text or ""
                if uri:
                    dataset_uris.add(uri)
            if not dataset_uris and not void_file:
                void_uri = await async_has_void_file(endpoint, timeout)
                if void_uri:
                    return await async_select_void_subject_remote(str(void_uri), timeout, True)
        except Exception as e:
            logger.warning(f"[SBJ] Query execution error: {e}. Endpoint: {endpoint}")
            return []

    class_names: set[str] = set()
    async with aiohttp.ClientSession() as session:
        for ds_uri in dataset_uris:
            query2 = f"""
                PREFIX dcterms: <http://purl.org/dc/terms/>
                SELECT DISTINCT ?classUri
                WHERE {{
                    <{ds_uri}> dcterms:subject ?classUri .
                }}
                LIMIT 100
            """
            try:
                result_text = await _fetch_query(session, endpoint, query2, timeout)
                root = eT.fromstring(result_text)
                ns = {"sparql": "http://www.w3.org/2005/sparql-results#"}
                bindings2 = root.findall('.//sparql:binding[@name="classUri"]/sparql:uri', ns)
                for binding in bindings2:
                    cn = binding.text or ""
                    if cn:
                        class_names.add(cn)
            except Exception as e:
                logger.warning(f"[SBJ] Error processing VOID subjects for {ds_uri}: {e}")

    logger.info(f"[SBJ] Finished VOID subject query for endpoint: {endpoint}")
    return list(class_names)


async def process_endpoint(row: pd.Series) -> list[Any]:
    endpoint = str(row["sparql_url"])
    row_id = str(row["id"])
    logger.info(f"[PROC] Processing endpoint {row_id}")
    same_as_objects_task = asyncio.create_task(async_select_remote_same_as_objects(endpoint))
    tasks = {
        "title": async_select_remote_title(endpoint),
        "voc": async_select_remote_vocabularies(endpoint),
        "class_partitions": async_select_remote_class_partitions(endpoint),
        "property_partitions": async_select_remote_property_partitions(endpoint),
        "statistics": async_select_remote_statistics(endpoint),
        "lab": async_select_remote_label(endpoint),
        "tlds": async_select_remote_tlds(endpoint),
        "creator": async_select_void_creator(endpoint),
        "license": async_select_void_license(endpoint),
    }
    results = await asyncio.gather(*tasks.values(), return_exceptions=True)
    result_dict = dict(zip(tasks.keys(), results))
    same_as_result = await asyncio.gather(same_as_objects_task, return_exceptions=True)
    same_as_objects = same_as_result[0] if same_as_result and not isinstance(same_as_result[0], Exception) else []
    class_partitions = result_dict.get("class_partitions") or []
    if isinstance(class_partitions, Exception):
        class_partitions = []
    property_partitions = result_dict.get("property_partitions") or []
    if isinstance(property_partitions, Exception):
        property_partitions = []
    statistics = result_dict.get("statistics") or {}
    if isinstance(statistics, Exception):
        statistics = {}
    classes = [partition["class"] for partition in class_partitions if isinstance(partition, dict) and partition.get("class")]
    properties = [
        partition["property"]
        for partition in property_partitions
        if isinstance(partition, dict) and partition.get("property")
    ]
    connections = sorted(set(same_as_objects))[:1000]
    same_as_links = aggregate_same_as_links(same_as_objects)
    logger.info(f"[PROC] Finished processing endpoint {row_id}")
    return [
        row_id,
        result_dict.get("title") or "",
        result_dict.get("voc") or [],
        classes,
        properties,
        class_partitions,
        property_partitions,
        statistics,
        result_dict.get("lab") or [],
        result_dict.get("tlds") or [],
        endpoint,
        result_dict.get("creator") or [],
        result_dict.get("license") or [],
        connections,
        same_as_links,
        str(row["category"]),
    ]


async def process_endpoint_void(row: pd.Series) -> list[Any]:
    endpoint = str(row["sparql_url"])
    row_id = str(row["id"])
    logger.info(f"[VOID-PROC] Processing VOID endpoint {row_id}")
    tasks = {
        "sbj": async_select_void_subject_remote(endpoint),
        "dsc": async_select_void_description(endpoint),
        "download": async_select_void_download(endpoint),
    }
    results = await asyncio.gather(*tasks.values(), return_exceptions=True)
    result_dict = dict(zip(tasks.keys(), results))
    logger.info(f"[VOID-PROC] Finished processing VOID endpoint {row_id}")
    return [
        row_id,
        result_dict.get("sbj") or [],
        result_dict.get("dsc") or [],
        result_dict.get("download") or [],
        str(row["category"]),
    ]


async def process_endpoint_full_inplace(endpoint: str, ingest_lov: bool = False) -> dict[str, Any]:
    row = pd.Series({"id": "", "sparql_url": endpoint, "category": ""})
    discovered_void = await async_discover_standard_void_metadata(endpoint)
    query_discovered_void = await async_discover_void_metadata_by_dataset_query(
        endpoint,
        include_alternative_dataset_vocabularies=not bool(discovered_void)
    )
    discovered_void = _merge_void_metadata(discovered_void, query_discovered_void)

    discovered_titles = _dedupe(discovered_void.get("title"))
    if discovered_titles:
        title = discovered_titles[0]
    else:
        void_uri = await async_has_void_file(endpoint)
        if void_uri:
            title = await async_select_remote_title(str(void_uri))
        else:
            title = await async_select_remote_title(endpoint)
    if not title:
        title = endpoint

    data_list = await process_endpoint(row)
    void_list = await process_endpoint_void(row)

    if discovered_void:
        logger.info(f"[VOID-DISCOVERY] Enriching endpoint profile with discovered VoID metadata: {endpoint}")
    else:
        logger.info(f"[VOID-DISCOVERY] Proceeding with regular endpoint profiling only: {endpoint}")

    voc = _merge_lists(discovered_void.get("voc"), data_list[2])
    class_partitions = _merge_partitions(discovered_void.get("class_partitions"), data_list[5], "class", "entities")
    property_partitions = _merge_partitions(
        discovered_void.get("property_partitions"),
        data_list[6],
        "property",
        "triples"
    )
    statistics = _merge_statistics(discovered_void.get("statistics"), data_list[7])
    classes = [partition["class"] for partition in class_partitions if partition.get("class")]
    properties = [partition["property"] for partition in property_partitions if partition.get("property")]
    creator = _merge_lists(discovered_void.get("creator"), data_list[11])
    contributor = _merge_lists(discovered_void.get("contributor"))
    publisher = _merge_lists(discovered_void.get("publisher"))
    source = _merge_lists(discovered_void.get("source"))
    identifier = _merge_lists(discovered_void.get("identifier"))
    date = _merge_lists(discovered_void.get("date"))
    created = _merge_lists(discovered_void.get("created"))
    issued = _merge_lists(discovered_void.get("issued"))
    modified = _merge_lists(discovered_void.get("modified"))
    license_values = _merge_lists(discovered_void.get("license"), data_list[12])
    sbj = _merge_lists(discovered_void.get("sbj"), void_list[1])
    dsc = _merge_lists(discovered_void.get("dsc"), void_list[2])
    download = _merge_lists(discovered_void.get("download"), void_list[3])
    same_as_links = discovered_void.get("same_as_links") or data_list[14]
    connections = data_list[13]

    if discovered_void.get("same_as_links") and data_list[14]:
        same_as_links = aggregate_same_as_links(discovered_void.get("same_as_links", []) + data_list[14])
        connections = _merge_lists(
            [link.get("dataset") for link in discovered_void.get("same_as_links", []) if isinstance(link, dict)],
            data_list[13]
        )

    voc_tags = []
    comments = []
    if ingest_lov or Config.QUERY_LOV:
        voc_tags = find_tags_from_list(voc)
        comments = find_comments_from_lists(curi_list=classes, puri_list=properties)

    return {
        "id": endpoint,
        "title": title,
        "sbj": sbj,
        "dsc": dsc,
        "download": download,
        "voc": voc,
        "curi": classes,
        "puri": properties,
        "class_partitions": class_partitions,
        "property_partitions": property_partitions,
        "statistics": statistics,
        "lab": data_list[8],
        "tlds": data_list[9],
        "sparql": endpoint,
        "creator": creator,
        "contributor": contributor,
        "publisher": publisher,
        "source": source,
        "identifier": identifier,
        "date": date,
        "created": created,
        "issued": issued,
        "modified": modified,
        "license": license_values,
        "con": connections,
        "same_as_links": same_as_links,
        "void_metadata": discovered_void.get("void_metadata", []),
        "tags": voc_tags,
        "comments": comments
    }


async def main_normal() -> None:
    logger.info("[MAIN] Starting asynchronous remote dataset processing (normal mode).")
    try:
        lod_frame = pd.read_csv("../data/raw/sparql_full_download.csv")
        lod_frame = lod_frame[~lod_frame["category"].fillna("").str.strip().isin(["user_generated"])]
    except Exception as e:
        logger.error(f"Error reading CSV file: {e}")
        sys.exit(1)
    lod_frame = lod_frame.drop_duplicates(subset=["sparql_url"])
    lod_frame = lod_frame[lod_frame["sparql_url"].notna() & (lod_frame["sparql_url"] != "")]
    tasks = [
        asyncio.wait_for(process_endpoint(row), timeout=ENDPOINT_TIMEOUT)
        for _, row in lod_frame.iterrows()
    ]
    total = len(tasks)
    logger.info(f"[MAIN] Total endpoints to process: {total}")
    results: list[list[Any]] = []
    processed = 0
    for coro in asyncio.as_completed(tasks):
        try:
            res = await coro
            if res is not None:
                results.append(res)
        except asyncio.TimeoutError:
            logger.warning("[MAIN] Timeout processing an endpoint.")
        except Exception as e:
            logger.warning(f"[MAIN] Error processing an endpoint: {e}")
        processed += 1
        logger.info(f"[MAIN] Processed {processed}/{total} endpoints")
    df = pd.DataFrame(
        results,
        columns=[
            "id",
            "title",
            "voc",
            "curi",
            "puri",
            "class_partitions",
            "property_partitions",
            "statistics",
            "lab",
            "tlds",
            "sparql",
            "creator",
            "license",
            "con",
            "same_as_links",
            "category",
        ],
    )
    output_path = "../data/raw/remote/remote_feature_set_sparqlwrapper.json"
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    df.to_json(output_path, orient="records")
    logger.info(f"[MAIN] Finished processing. Output saved to {output_path}")


async def main_void() -> None:
    logger.info("[VOID-MAIN] Starting asynchronous VOID dataset processing.")
    try:
        lod_frame = pd.read_csv("../data/raw/sparql_full_download.csv")
        lod_frame = lod_frame[~lod_frame["category"].fillna("").str.strip().isin(["user_generated"])]
    except Exception as e:
        logger.error(f"Error reading CSV file: {e}")
        sys.exit(1)
    lod_frame = lod_frame.drop_duplicates(subset=["sparql_url"])
    lod_frame = lod_frame[lod_frame["sparql_url"].notna() & (lod_frame["sparql_url"] != "")]
    tasks = [
        asyncio.wait_for(process_endpoint_void(row), timeout=ENDPOINT_TIMEOUT)
        for _, row in lod_frame.iterrows()
    ]
    total = len(tasks)
    logger.info(f"[VOID-MAIN] Total VOID endpoints to process: {total}")
    results: list[list[Any]] = []
    processed = 0
    for coro in asyncio.as_completed(tasks):
        try:
            res = await coro
            if res is not None:
                results.append(res)
        except asyncio.TimeoutError:
            logger.warning("[VOID-MAIN] Timeout processing a VOID endpoint.")
        except Exception as e:
            logger.warning(f"[VOID-MAIN] Error processing a VOID endpoint: {e}")
        processed += 1
        logger.info(f"[VOID-MAIN] Processed {processed}/{total} VOID endpoints")
    df = pd.DataFrame(results, columns=["id", "sbj", "dsc", "download", "category"])
    output_path = "../data/raw/remote/remote_void_feature_set_sparqlwrapper.json"
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    df.to_json(output_path, orient="records")
    logger.info(f"[VOID-MAIN] Finished VOID processing. Output saved to {output_path}")


if __name__ == "__main__":
    asyncio.run(main_normal())
    asyncio.run(main_void())
