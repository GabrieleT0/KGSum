import logging
import os
from multiprocessing import get_context
from os import listdir
from typing import Any

import pandas as pd
import rdflib
from rdflib import Graph
from rdflib.plugins.sparql import prepareQuery

from config import Config
from src.lov_data_preparation import find_tags_from_list, find_comments_from_lists
from src.util import match_file_lod, CATEGORIES
from src.void_linksets import aggregate_same_as_links
from src.dataset_preparation_remote import (
    _dedupe,
    _extract_all_void_dataset_triples,
    _extract_download_values,
    _merge_lists,
    _merge_partitions,
    _merge_statistics,
    _select_relevant_void_datasets,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("dataset_preparation")

FORMATS = {'ttl', 'xml', 'nt', 'trig', 'n3', 'nquads'}


def log_query(query):
    logger.info(f"SPARQL Query: {query}")


def select_local_vocabularies(parsed_graph):
    Q_LOCAL_VOCABULARIES = prepareQuery("""
        SELECT DISTINCT ?predicate
        WHERE {
            ?subject ?predicate ?object .
            FILTER(STRSTARTS(STR(?predicate), "http://"))
            FILTER(!STRSTARTS(STR(STRBEFORE(STR(?predicate), "#")), "http://www.w3.org/"))
        }
        LIMIT 1000
    """)
    log_query(Q_LOCAL_VOCABULARIES)
    try:
        qres = parsed_graph.query(Q_LOCAL_VOCABULARIES)
    except Exception as e:
        logger.warning(f"SPARQL error in select_local_vocabularies: {e}")
        return set()

    vocabularies = set()
    for row in qres:
        predicate_uri = str(row.predicate)
        if not predicate_uri:
            continue

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

    return vocabularies


def select_local_class_partitions(parsed_graph) -> list[dict[str, Any]]:
    Q_LOCAL_CLASS = prepareQuery("""
        SELECT ?classUri (COUNT(?instance) AS ?instanceCount)
        WHERE {
            ?instance a ?classUri .
        }
        GROUP BY ?classUri
        ORDER BY DESC(?instanceCount)
        LIMIT 1000
    """)
    log_query(Q_LOCAL_CLASS)
    try:
        qres = parsed_graph.query(Q_LOCAL_CLASS)
    except Exception as e:
        logger.warning(f"SPARQL error in select_local_class: {e}")
        return []

    partitions = []
    for row in qres:
        row_dict = row.asdict()
        class_uri = str(row_dict.get("classUri", ""))
        if not class_uri:
            continue
        try:
            count = int(row_dict.get("instanceCount", 0))
        except (TypeError, ValueError):
            count = 0
        partitions.append({"class": class_uri, "entities": count})
    return partitions


def select_local_class(parsed_graph) -> list[str]:
    return [partition["class"] for partition in select_local_class_partitions(parsed_graph)]


def select_local_label(parsed_graph):
    ns = {
        "schema": 'http://schema.org',
        "skos": 'http://www.w3.org/2004/02/skos/core#',
        "rdfs": 'http://www.w3.org/2000/01/rdf-schema#',
        "foaf": 'http://xmlns.com/foaf/0.1/',
        "awol": 'http://bblfish.net/work/atom-owl/2006-06-06/#',
        "wdrs": 'http://www.w3.org/2007/05/powder-s#',
        "skosxl": 'http://www.w3.org/2008/05/skos-xl#'
    }

    Q_LOCAL_LABEL_EN = prepareQuery("""
        SELECT DISTINCT ?o
        WHERE {
            ?s a ?label .
            { ?s rdfs:label ?o }
            UNION
            { ?s foaf:name ?o }
            UNION
            { ?s skos:prefLabel ?o }
            UNION
            { ?s rdfs:comment ?o }
            UNION
            { ?s awol:label ?o }
            UNION
            { ?s skos:note ?o }
            UNION
            { ?s wdrs:text ?o }
            UNION
            { ?s skosxl:prefLabel ?o }
            UNION
            { ?s skosxl:literalForm ?o }
            UNION
            { ?s schema:name ?o }
            FILTER(langMatches(lang(?o), "en"))
        }
        LIMIT 1000
    """, initNs=ns)
    log_query(Q_LOCAL_LABEL_EN)

    try:
        qres = parsed_graph.query(Q_LOCAL_LABEL_EN)
    except Exception as e:
        logger.warning(f"SPARQL error in select_local_label (EN): {e}")
        qres = []

    if not qres or len(qres) < 2:
        Q_LOCAL_LABEL = prepareQuery("""
            SELECT DISTINCT ?o
            WHERE {
                ?s a ?label .
                { ?s rdfs:label ?o }
                UNION
                { ?s foaf:name ?o }
                UNION
                { ?s skos:prefLabel ?o }
                UNION
                { ?s rdfs:comment ?o }
                UNION
                { ?s awol:label ?o }
                UNION
                { ?s skos:note ?o }
                UNION
                { ?s wdrs:text ?o }
                UNION
                { ?s skosxl:prefLabel ?o }
                UNION
                { ?s skosxl:literalForm ?o }
                UNION
                { ?s schema:name ?o }
            }
            LIMIT 1000
        """, initNs=ns)
        log_query(Q_LOCAL_LABEL)
        try:
            qres = parsed_graph.query(Q_LOCAL_LABEL)
        except Exception as e:
            logger.warning(f"SPARQL error in select_local_label (fallback): {e}")
            return set()

    return {str(row.o) for row in qres}


def select_local_tld(parsed_graph):
    Q_LOCAL_TLD = prepareQuery("""
        SELECT DISTINCT ?o
        WHERE {
            ?s ?p ?o .
            FILTER(isIRI(?o))
        }
        LIMIT 1000
    """)
    log_query(Q_LOCAL_TLD)
    try:
        qres = parsed_graph.query(Q_LOCAL_TLD)
    except Exception as e:
        logger.warning(f"SPARQL error in select_local_tld: {e}")
        return set()

    tlds = set()
    for row in qres:
        url = str(row.o)
        if url.startswith(("http://", "https://")):
            try:
                host = url.split("/")[2]
                tld = host.split(".")[-1]
                if 1 < len(tld) <= 10:
                    tlds.add(tld)
            except Exception as exc:
                logger.warning(f"Unable to parse TLD from {url}: {exc}")
    return tlds


def select_local_property_partitions(parsed_graph) -> list[dict[str, Any]]:
    Q_LOCAL_PROPERTY = prepareQuery("""
        SELECT ?property (COUNT(?s) AS ?usageCount)
        WHERE {
            ?s ?property ?o .
            FILTER (?property != rdf:type)
        }
        GROUP BY ?property
        ORDER BY DESC(?usageCount)
        LIMIT 1000
    """, initNs={"rdf": rdflib.RDF})
    log_query(Q_LOCAL_PROPERTY)
    try:
        qres = parsed_graph.query(Q_LOCAL_PROPERTY)
    except Exception as e:
        logger.warning(f"SPARQL error in select_local_property: {e}")
        return []

    partitions = []
    for row in qres:
        row_dict = row.asdict()
        property_uri = str(row_dict.get("property", ""))
        if not property_uri:
            continue
        try:
            count = int(row_dict.get("usageCount", 0))
        except (TypeError, ValueError):
            count = 0
        partitions.append({"property": property_uri, "triples": count})
    return partitions


def select_local_property(parsed_graph):
    return [partition["property"] for partition in select_local_property_partitions(parsed_graph)]


def select_local_statistics(parsed_graph) -> dict[str, int]:
    try:
        triples = len(parsed_graph)
        entities = len({s for s, _, _ in parsed_graph.triples((None, rdflib.RDF.type, None))})
        return {"triples": triples, "entities": entities}
    except Exception as e:
        logger.warning(f"Error in select_local_statistics: {e}")
        return {}


def select_local_void_dataset_metadata(parsed_graph, endpoint: str | None = None) -> dict[str, Any]:
    Q_LOCAL_VOID_DATASET = prepareQuery("""
        SELECT *
        WHERE {
            ?s a ?datasetType .
            VALUES ?datasetType {
                void:Dataset
                dcat:Dataset
                schema:Dataset
                schemahttps:Dataset
                dctype:Dataset
                qb:DataSet
                adms:Asset
            }
            ?s ?p ?o .
        }
    """, initNs={
        "void": 'http://rdfs.org/ns/void#',
        "dcat": 'http://www.w3.org/ns/dcat#',
        "schema": 'http://schema.org/',
        "schemahttps": 'https://schema.org/',
        "dctype": 'http://purl.org/dc/dcmitype/',
        "qb": 'http://purl.org/linked-data/cube#',
        "adms": 'http://www.w3.org/ns/adms#',
    })
    log_query(Q_LOCAL_VOID_DATASET)

    try:
        rows = list(parsed_graph.query(Q_LOCAL_VOID_DATASET))
    except Exception as e:
        logger.warning(f"SPARQL error in select_local_void_dataset_metadata: {e}")
        return {}

    if not rows:
        return {}

    dataset_nodes = {row.asdict().get("s") for row in rows if row.asdict().get("s") is not None}
    if endpoint:
        dataset_nodes = _select_relevant_void_datasets(parsed_graph, endpoint, dataset_nodes)
    elif len(dataset_nodes) > 1:
        described_nodes = set()
        for description in parsed_graph.subjects(rdflib.RDF.type, rdflib.URIRef("http://rdfs.org/ns/void#DatasetDescription")):
            described_nodes.update(parsed_graph.objects(description, rdflib.URIRef("http://xmlns.com/foaf/0.1/primaryTopic")))
            described_nodes.update(parsed_graph.objects(description, rdflib.URIRef("http://xmlns.com/foaf/0.1/topic")))
        if described_nodes:
            dataset_nodes = dataset_nodes.intersection(described_nodes) or described_nodes

    if not dataset_nodes:
        return {}

    metadata = {
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
        "void_metadata": _extract_all_void_dataset_triples(parsed_graph, dataset_nodes),
    }

    DCTERMS_NS = rdflib.Namespace('http://purl.org/dc/terms/')
    RDFS_NS = rdflib.Namespace('http://www.w3.org/2000/01/rdf-schema#')
    VOID_NS = rdflib.Namespace('http://rdfs.org/ns/void#')
    DCAT_NS = rdflib.Namespace('http://www.w3.org/ns/dcat#')

    for dataset in dataset_nodes:
        metadata["title"].extend(str(value) for value in parsed_graph.objects(dataset, DCTERMS_NS.title))
        metadata["title"].extend(str(value) for value in parsed_graph.objects(dataset, RDFS_NS.label))
        metadata["dsc"].extend(str(value) for value in parsed_graph.objects(dataset, DCTERMS_NS.description))
        metadata["creator"].extend(str(value) for value in parsed_graph.objects(dataset, DCTERMS_NS.creator))
        metadata["contributor"].extend(str(value) for value in parsed_graph.objects(dataset, DCTERMS_NS.contributor))
        metadata["publisher"].extend(str(value) for value in parsed_graph.objects(dataset, DCTERMS_NS.publisher))
        metadata["source"].extend(str(value) for value in parsed_graph.objects(dataset, DCTERMS_NS.source))
        metadata["identifier"].extend(str(value) for value in parsed_graph.objects(dataset, DCTERMS_NS.identifier))
        metadata["date"].extend(str(value) for value in parsed_graph.objects(dataset, DCTERMS_NS.date))
        metadata["created"].extend(str(value) for value in parsed_graph.objects(dataset, DCTERMS_NS.created))
        metadata["issued"].extend(str(value) for value in parsed_graph.objects(dataset, DCTERMS_NS.issued))
        metadata["modified"].extend(str(value) for value in parsed_graph.objects(dataset, DCTERMS_NS.modified))
        metadata["license"].extend(str(value) for value in parsed_graph.objects(dataset, DCTERMS_NS.license))
        metadata["sbj"].extend(str(value) for value in parsed_graph.objects(dataset, DCTERMS_NS.subject))
        metadata["download"].extend(_extract_download_values(parsed_graph, dataset))
        metadata["voc"].extend(str(value) for value in parsed_graph.objects(dataset, VOID_NS.vocabulary))
        metadata["sparql"].extend(str(value) for value in parsed_graph.objects(dataset, VOID_NS.sparqlEndpoint))

        triples = next(parsed_graph.objects(dataset, VOID_NS.triples), None)
        entities = next(parsed_graph.objects(dataset, VOID_NS.entities), None)
        if triples is not None:
            try:
                metadata["statistics"]["triples"] = int(triples)
            except (TypeError, ValueError):
                pass
        if entities is not None:
            try:
                metadata["statistics"]["entities"] = int(entities)
            except (TypeError, ValueError):
                pass

        for partition in parsed_graph.objects(dataset, VOID_NS.classPartition):
            class_uri = next(parsed_graph.objects(partition, VOID_NS['class']), None)
            if class_uri:
                count = next(parsed_graph.objects(partition, VOID_NS.entities), 0)
                try:
                    count = int(count)
                except (TypeError, ValueError):
                    count = 0
                metadata["class_partitions"].append({"class": str(class_uri), "entities": count})

        for partition in parsed_graph.objects(dataset, VOID_NS.propertyPartition):
            property_uri = next(parsed_graph.objects(partition, VOID_NS.property), None)
            if property_uri:
                count = next(parsed_graph.objects(partition, VOID_NS.triples), 0)
                try:
                    count = int(count)
                except (TypeError, ValueError):
                    count = 0
                metadata["property_partitions"].append({"property": str(property_uri), "triples": count})

    for key in (
        "title", "dsc", "creator", "contributor", "publisher", "source", "identifier",
        "date", "created", "issued", "modified",
        "license", "sbj", "download", "voc", "sparql"
    ):
        metadata[key] = _dedupe(metadata[key])
    return metadata


def select_local_endpoint(parsed_graph):
    Q_LOCAL_VOID_SPARQL = prepareQuery("""
        SELECT DISTINCT ?o
        WHERE {
            ?s void:sparqlEndpoint ?o .
        }
        LIMIT 2
    """, initNs={"void": 'http://rdfs.org/ns/void#'})
    log_query(Q_LOCAL_VOID_SPARQL)
    try:
        qres = parsed_graph.query(Q_LOCAL_VOID_SPARQL)
    except Exception as e:
        logger.warning(f"SPARQL error in select_local_endpoint: {e}")
        return []
    return list({str(row.o) for row in qres})


def select_local_creator(parsed_graph):
    Q_LOCAL_DCTERMS_CREATOR = prepareQuery("""
        SELECT ?creator
        WHERE {
            ?s dcterms:creator ?creator .
        }
        LIMIT 5
    """, initNs={"dcterms": 'http://purl.org/dc/terms/'})
    log_query(Q_LOCAL_DCTERMS_CREATOR)
    try:
        qres = parsed_graph.query(Q_LOCAL_DCTERMS_CREATOR)
    except Exception as e:
        logger.warning(f"SPARQL error in select_local_creator: {e}")
        return set()
    return {str(row.creator) for row in qres}

def select_local_download(parsed_graph):
    Q_LOCAL_VOID_DOWNLOAD = prepareQuery("""
        SELECT ?download
        WHERE {
            ?s void:dataDump ?dump .
        }
        LIMIT 5
    """, initNs={"void": 'http://rdfs.org/ns/void#'})
    log_query(Q_LOCAL_VOID_DOWNLOAD)
    try:
        qres = parsed_graph.query(Q_LOCAL_VOID_DOWNLOAD)
    except Exception as e:
        logger.warning(f"SPARQL error in select_local_creator: {e}")
        return set()
    return {str(row.dump) for row in qres}



def select_local_license(parsed_graph):
    Q_LOCAL_DCTERMS_LICENSE = prepareQuery("""
        SELECT ?license
        WHERE {
            ?s dcterms:license ?license .
        }
        LIMIT 1
    """, initNs={"dcterms": 'http://purl.org/dc/terms/'})
    log_query(Q_LOCAL_DCTERMS_LICENSE)
    try:
        qres = parsed_graph.query(Q_LOCAL_DCTERMS_LICENSE)
    except Exception as e:
        logger.warning(f"SPARQL error in select_local_license: {e}")
        return set()
    return {str(row.license) for row in qres}


def select_local_void_subject(parsed_graph):
    Q_LOCAL_VOID_SUBJECT = prepareQuery("""
        SELECT DISTINCT ?s
        WHERE {
            ?s rdf:type void:Dataset .
        }
        LIMIT 100
    """, initNs={"rdf": rdflib.RDF, "void": 'http://rdfs.org/ns/void#'})
    log_query(Q_LOCAL_VOID_SUBJECT)

    try:
        qres = parsed_graph.query(Q_LOCAL_VOID_SUBJECT)
    except Exception as e:
        logger.warning(f"SPARQL error in select_local_void_subject: {e}")
        return set()

    dataset_uris = {str(row.s) for row in qres if str(row.s)}

    subject = set()
    for ds_uri in dataset_uris:
        query_str = f"""
            SELECT ?classUri
            WHERE {{
                <{ds_uri}> dcterms:subject ?classUri .
            }}
            LIMIT 100
        """
        log_query(query_str)
        try:
            result = parsed_graph.query(query_str, initNs={"dcterms": 'http://purl.org/dc/terms/'})
            for res in result:
                class_uri = str(res.classUri)
                if class_uri:
                    subject.add(class_uri)
        except Exception as e:
            logger.warning(f"SPARQL error in select_local_void_subject loop: {e}")
    return subject


def select_local_void_description(parsed_graph):
    Q_LOCAL_DCTERMS_DESCRIPTION = prepareQuery("""
        SELECT ?desc
        WHERE {
            ?s dcterms:description ?desc .
        }
        LIMIT 100
    """, initNs={"dcterms": 'http://purl.org/dc/terms/'})
    log_query(Q_LOCAL_DCTERMS_DESCRIPTION)
    try:
        qres = parsed_graph.query(Q_LOCAL_DCTERMS_DESCRIPTION)
    except Exception as e:
        logger.warning(f"SPARQL error in select_local_void_description: {e}")
        return set()
    return {str(row.desc) for row in qres}


def select_local_void_title(parsed_graph):
    Q_LOCAL_DCTERMS_TITLE = prepareQuery("""
        SELECT ?desc
        WHERE {
            ?s dcterms:title ?desc .
        }
        LIMIT 1
    """, initNs={"dcterms": 'http://purl.org/dc/terms/'})
    log_query(Q_LOCAL_DCTERMS_TITLE)
    try:
        qres = parsed_graph.query(Q_LOCAL_DCTERMS_TITLE)
    except Exception as e:
        logger.warning(f"SPARQL error in select_local_void_title: {e}")
        return []
    return [str(row.desc) for row in qres]


def select_local_con(parsed_graph):
    Q_LOCAL_CON = prepareQuery("""
        SELECT DISTINCT ?o
        WHERE {
            ?s owl:sameAs ?o .
        }
        LIMIT 1000
    """, initNs={"owl": 'http://www.w3.org/2002/07/owl#'})
    log_query(Q_LOCAL_CON)
    try:
        qres = parsed_graph.query(Q_LOCAL_CON)
    except Exception as e:
        logger.warning(f"SPARQL error in select_local_con: {e}")
        return []
    return [str(row.o) for row in qres]


def select_local_same_as_links(parsed_graph) -> list[dict[str, Any]]:
    Q_LOCAL_SAME_AS_LINKS = prepareQuery("""
        SELECT ?kg (COUNT(?o) AS ?count)
        WHERE {
            ?s owl:sameAs ?o .
            FILTER(isIRI(?o))
            BIND(REPLACE(STR(?o), "^(https?://[^/]+).*", "$1") AS ?kg)
        }
        GROUP BY ?kg
        ORDER BY DESC(?count)
    """, initNs={"owl": 'http://www.w3.org/2002/07/owl#'})
    log_query(Q_LOCAL_SAME_AS_LINKS)
    try:
        qres = parsed_graph.query(Q_LOCAL_SAME_AS_LINKS)
    except Exception as e:
        logger.warning(f"SPARQL error in select_local_same_as_links: {e}")
        return aggregate_same_as_links(select_local_con(parsed_graph))

    same_as_links = []
    for row in qres:
        try:
            row_dict = row.asdict()
            same_as_links.append({"dataset": str(row_dict["kg"]), "count": int(row_dict["count"])})
        except (KeyError, TypeError, ValueError):
            continue
    return same_as_links


def _guess_format_and_parse(path):
    g = Graph()
    for f in FORMATS:
        try:
            return g.parse(path, format=f)
        except Exception:
            continue
    raise Exception(f"Format not supported for file: {path}")


def process_file_full_inplace(
        file_path: str,
        ingest_lov: bool = False
) -> dict[str, Any] | None:
    if not file_path:
        return None

    try:
        logger.info(f"Processing graph file: {file_path}")
        parsed_graph = _guess_format_and_parse(file_path)
        void_dataset_metadata = select_local_void_dataset_metadata(parsed_graph)

        title_list = select_local_void_title(parsed_graph)
        void_subjects = select_local_void_subject(parsed_graph)
        void_descriptions = select_local_void_description(parsed_graph)
        vocabularies = select_local_vocabularies(parsed_graph)
        class_partitions = select_local_class_partitions(parsed_graph)
        property_partitions = select_local_property_partitions(parsed_graph)
        class_list = [partition["class"] for partition in class_partitions]
        property_list = [partition["property"] for partition in property_partitions]
        statistics = select_local_statistics(parsed_graph)
        labels = select_local_label(parsed_graph)
        tlds = select_local_tld(parsed_graph)
        endpoints = select_local_endpoint(parsed_graph)
        creators = select_local_creator(parsed_graph)
        download = select_local_download(parsed_graph)
        licenses = select_local_license(parsed_graph)
        connections = select_local_con(parsed_graph)
        same_as_links = select_local_same_as_links(parsed_graph)

        title_list = _merge_lists(void_dataset_metadata.get("title"), title_list)
        void_subjects = _merge_lists(void_dataset_metadata.get("sbj"), list(void_subjects))
        void_descriptions = _merge_lists(void_dataset_metadata.get("dsc"), list(void_descriptions))
        vocabularies = _merge_lists(void_dataset_metadata.get("voc"), list(vocabularies))
        class_partitions = _merge_partitions(
            void_dataset_metadata.get("class_partitions"), class_partitions, "class", "entities"
        )
        property_partitions = _merge_partitions(
            void_dataset_metadata.get("property_partitions"), property_partitions, "property", "triples"
        )
        class_list = [partition["class"] for partition in class_partitions]
        property_list = [partition["property"] for partition in property_partitions]
        statistics = _merge_statistics(void_dataset_metadata.get("statistics"), statistics)
        endpoints = _merge_lists(void_dataset_metadata.get("sparql"), endpoints)
        creators = _merge_lists(void_dataset_metadata.get("creator"), list(creators))
        contributors = _merge_lists(void_dataset_metadata.get("contributor"))
        publishers = _merge_lists(void_dataset_metadata.get("publisher"))
        sources = _merge_lists(void_dataset_metadata.get("source"))
        identifier = _merge_lists(void_dataset_metadata.get("identifier"))
        date = _merge_lists(void_dataset_metadata.get("date"))
        created = _merge_lists(void_dataset_metadata.get("created"))
        issued = _merge_lists(void_dataset_metadata.get("issued"))
        modified = _merge_lists(void_dataset_metadata.get("modified"))
        download = _merge_lists(void_dataset_metadata.get("download"), list(download))
        licenses = _merge_lists(void_dataset_metadata.get("license"), list(licenses))

        title = title_list[0] if title_list else (endpoints[0] if endpoints else "")
        class_list = list(class_list)
        property_list = list(property_list)
        vocabularies = list(vocabularies)
        voc_tags = []
        comments = []
        if ingest_lov or Config.QUERY_LOV:
            voc_tags = find_tags_from_list(vocabularies)
            comments = find_comments_from_lists(curi_list=class_list, puri_list=property_list)

        return {
            "id": title,
            "title": title,
            "sbj": list(void_subjects),
            "dsc": list(void_descriptions),
            "voc": list(vocabularies),
            "curi": list(class_list),
            "puri": list(property_list),
            "class_partitions": class_partitions,
            "property_partitions": property_partitions,
            "statistics": statistics,
            "lab": list(labels),
            "sparql": endpoints,
            "tlds": list(tlds),
            "creator": list(creators),
            "contributor": list(contributors),
            "publisher": list(publishers),
            "source": list(sources),
            "identifier": list(identifier),
            "date": list(date),
            "created": list(created),
            "issued": list(issued),
            "modified": list(modified),
            "download": list(download),
            "license": list(licenses),
            "con": connections,
            "same_as_links": same_as_links,
            "void_metadata": void_dataset_metadata.get("void_metadata", []),
            "tags": voc_tags,
            "comments": comments
        }

    except Exception as e:
        logger.warning(f"Error processing file {file_path}: {e}")
        return None


lod_frame_global: pd.DataFrame = pd.DataFrame()


def init_worker(lod_frame_path: str):
    global lod_frame_global
    df = pd.read_csv(lod_frame_path)
    lod_frame_global = df[~df["category"].fillna("").str.strip().eq("user_generated")].reset_index(drop=True)


def process_local_dataset_file(args):
    category, filename, offset, limit = args
    global lod_frame_global

    path = os.path.join("../data/raw/rdf_dump", category, filename)
    file_num = match_file_lod(filename, limit, offset, lod_frame_global)
    if file_num is None:
        return None

    row_id = lod_frame_global.at[file_num, "id"]
    try:
        parsed_graph = _guess_format_and_parse(path)
        vocab = select_local_vocabularies(parsed_graph)
        class_partitions = select_local_class_partitions(parsed_graph)
        property_partitions = select_local_property_partitions(parsed_graph)
        classes = [partition["class"] for partition in class_partitions]
        props = [partition["property"] for partition in property_partitions]
        statistics = select_local_statistics(parsed_graph)
        labels = select_local_label(parsed_graph)
        tlds = select_local_tld(parsed_graph)
        endpoints = select_local_endpoint(parsed_graph)
        creators = select_local_creator(parsed_graph)
        licenses = select_local_license(parsed_graph)
        connections = select_local_con(parsed_graph)
        same_as_links = select_local_same_as_links(parsed_graph)

        return [
            row_id,
            list(vocab),
            list(classes),
            list(props),
            class_partitions,
            property_partitions,
            statistics,
            list(labels),
            list(tlds),
            endpoints,
            list(creators),
            list(licenses),
            connections,
            same_as_links,
            lod_frame_global.at[file_num, "category"]
        ]
    except Exception as e:
        logger.warning(f"Error processing file {path}: {e}")
        return None


def process_local_void_dataset_file(args):
    category, filename, offset, limit = args
    global lod_frame_global

    path = os.path.join("../data/raw/rdf_dump", category, filename)
    file_num = match_file_lod(filename, limit, offset, lod_frame_global)
    if file_num is None:
        return None

    try:
        parsed_graph = _guess_format_and_parse(path)
        title_list = select_local_void_title(parsed_graph)
        void_subjects = select_local_void_subject(parsed_graph)
        void_descriptions = select_local_void_description(parsed_graph)
        download = select_local_download(parsed_graph)

        title = title_list[0] if title_list else ""

        return [
            lod_frame_global.at[file_num, "id"],
            title,
            list(void_subjects),
            list(void_descriptions),
            list(download),
            lod_frame_global.at[file_num, "category"],
        ]
    except Exception as e:
        logger.warning(f"Error processing file {path}: {e}")
        return None


def robust_pool_map(pool, func, tasks):
    results = []
    total = len(tasks)
    for i, result in enumerate(pool.imap_unordered(func, tasks), start=1):
        if result is not None:
            results.append(result)
        logger.info(f"Progress: {i}/{total} tasks completed.")
    return results


def create_local_dataset(
        offset: int = 0,
        limit: int = 10000,
):
    out_path = f"../data/raw/local/local_feature_set_{offset}_{limit}.json"
    # Check subito, uscita immediata se il file esiste
    if os.path.exists(out_path):
        logger.info(f"File already exists: {out_path} -- Skipping creation.")
        return

    lod_frame_path = "../data/raw/sparql_full_download.csv"
    tasks = []

    valid_categories = [cat for cat in CATEGORIES if cat != "user_generated"]

    for category in valid_categories:
        directory = os.path.join("../data/raw/rdf_dump", category)
        if not os.path.isdir(directory):
            logger.warning(f"Directory not found: {directory}")
            continue
        for filename in listdir(directory):
            if filename.startswith("."):
                continue
            tasks.append((category, filename, offset, limit))

    if not tasks:
        logger.warning("No tasks scheduled for local dataset.")
        return

    ctx = get_context("spawn")
    with ctx.Pool(
            processes=min(4, os.cpu_count() or 4),
            maxtasksperchild=4,
            initializer=init_worker,
            initargs=(lod_frame_path,),
    ) as pool:
        results = robust_pool_map(pool, process_local_dataset_file, tasks)

    if results:
        df = pd.DataFrame(
            results,
            columns=[
                "id",
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

        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        df.to_json(out_path, orient="records", index=False)
        logger.info(f"Saved local feature set to {out_path}")
    else:
        logger.warning("No results produced for local dataset.")


def create_local_void_dataset(offset: int = 0, limit: int = 10000):
    out_path = f"../data/raw/local/local_void_feature_set_{offset}_{limit}.json"
    # Check subito, uscita immediata se il file esiste
    if os.path.exists(out_path):
        logger.info(f"File already exists: {out_path} -- Skipping creation.")
        return

    lod_frame_path = "../data/raw/sparql_full_download.csv"
    tasks = []

    valid_categories = [cat for cat in CATEGORIES if cat != "user_generated"]

    for category in valid_categories:
        directory = os.path.join("../data/raw/rdf_dump", category)
        if not os.path.isdir(directory):
            logger.warning(f"Directory not found: {directory}")
            continue
        for filename in listdir(directory):
            if filename.startswith("."):
                continue
            tasks.append((category, filename, offset, limit))

    if not tasks:
        logger.warning("No tasks scheduled for local void dataset.")
        return

    ctx = get_context("spawn")
    with ctx.Pool(
            processes=min(4, os.cpu_count() or 4),
            maxtasksperchild=4,
            initializer=init_worker,
            initargs=(lod_frame_path,),
    ) as pool:
        results = robust_pool_map(pool, process_local_void_dataset_file, tasks)

    if results:
        df = pd.DataFrame(results, columns=[
            "id", "title", "sbj", "dsc", "download", "category"
        ])
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        df.to_json(out_path, orient="records", index=False)
        logger.info(f"Saved local void feature set to {out_path}")
    else:
        logger.warning("No results produced for local void dataset.")
