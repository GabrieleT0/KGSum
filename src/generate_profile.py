import ast
import asyncio
import os
import urllib.parse
from typing import Any

import aiohttp
import pandas as pd
from rdflib import BNode, Graph, Literal, Namespace, URIRef
from rdflib.namespace import DCTERMS, FOAF, OWL, RDF, XSD

from src.lov_data_preparation import IS_URI
from src.dataset_preparation import process_file_full_inplace, logger
from src.dataset_preparation_remote import process_endpoint_full_inplace
from src.predict_category import CategoryPredictor
from src.preprocessing import process_all_from_input
from src.void_linksets import aggregate_same_as_links

LOCAL_ENDPOINT = os.environ['LOCAL_ENDPOINT']
PREDICTOR: CategoryPredictor | None = None


def load_predictor():
    global PREDICTOR
    PREDICTOR = CategoryPredictor.get_predictor()


import aiohttp
import asyncio
import logging
import os

user = os.getenv("GRAPHDB_USER")
pwd = os.getenv("GRAPHDB_PASSWORD")


async def _update_query(query: str, timeout: int = 300) -> str:
    """Execute SPARQL update query against local endpoint with Authentication."""
    auth = aiohttp.BasicAuth(login=user, password=pwd)
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                    LOCAL_ENDPOINT + '/statements',
                    data={'update': query},
                    auth=auth,
                    timeout=timeout
            ) as response:
                if response.status == 401:
                    logger.error("Authentication failed: Invalid username or password.")
                    response.raise_for_status()
                elif response.status != 200:
                    logger.error(f"API Error {response.status}: {await response.text()}")
                    response.raise_for_status()

                return await response.text()

    except asyncio.TimeoutError:
        logger.error(f"Query timeout after {timeout} seconds")
        raise
    except Exception as e:
        logger.error(f"Query execution failed: {e}")
        raise


async def generate_profile(endpoint: str | None = None, file: str | None = None) -> dict[str, Any]:
    """Generate profile from either file or endpoint."""
    try:
        if file is not None:
            processed_data = process_all_from_input(process_file_full_inplace(file))
        elif endpoint is not None:
            processed_data = process_all_from_input(await process_endpoint_full_inplace(endpoint))
        else:
            return {
                'error': 'Upload a file or input a valid SPARQL endpoint'
            }

        profile = create_profile(processed_data)

        # Ensure predictor is loaded
        if PREDICTOR is None:
            load_predictor()

        predicted_category = PREDICTOR.predict_category(processed_data)
        profile['category'] = predicted_category if predicted_category else "UNKNOWN"
        return profile

    except Exception as e:
        logger.error(f"Profile generation failed: {e}")
        return {
            'error': 'An internal error occurred during profile generation.'
        }


async def generate_and_store_profile(
        endpoint: str | None = None,
        file: str | None = None,
        base_uri: str = "http://localhost:8000/"
) -> dict[str, Any]:
    """Generate profile and store it in the triplestore."""
    try:
        row = await generate_profile(endpoint=endpoint, file=file)

        if 'error' in row:
            return row

        await store_profile(profile=row, category=row['category'], base_iri=base_uri)
        return row

    except Exception as e:
        logger.error(f"Profile generation and storage failed: {e}")
        return {
            'error': 'An internal error occurred during profile generation and storage.'
        }


async def generate_profile_from_store(base_url: str = "https://www.isislab.it/"):
    """Generate profiles from stored dataset."""
    try:
        dataset = pd.read_json('../data/processed/combined.json')
        for index, col in dataset.iterrows():
            try:
                print(f"Processing: {col['id']}")
                profile = create_profile(data=col)
                await store_profile(
                    profile=profile,
                    category=str(col['category']),
                    base_iri=base_url
                )
            except Exception as e:
                logger.warning(f"Failed to process row {index}: {e}")
                continue

    except Exception as e:
        logger.error(f"Failed to process dataset: {e}")
        raise


def create_profile(data: dict[str, Any] | pd.DataFrame | pd.Series) -> dict[str, Any]:
    """Create profile from input data."""
    try:
        if isinstance(data, pd.DataFrame):
            data = data.dropna()
            data = data.drop_duplicates()
            data = data.to_dict('records')
        elif isinstance(data, pd.Series):
            data = data.dropna().to_dict()

        return data if isinstance(data, dict) else {}

    except Exception as e:
        logger.error(f"Profile creation failed: {e}")
        return {}


def profile_to_rdf(
        profile: dict[str, Any],
        base_iri: str = "https://www.isislab.it/resource/",
        rdf_format: str = "xml"
) -> str:
    """Serialize a generated profile as RDF using the same VoID/DCAT mapping used for storage."""
    raw_id_str = _extract_first_valid_uri(profile.get('id'))
    if not raw_id_str:
        raise ValueError("Cannot serialize profile as RDF without a valid id.")

    if IS_URI.match(raw_id_str):
        iri = raw_id_str
    else:
        iri = base_iri + urllib.parse.quote(raw_id_str, safe="")

    dataset = URIRef(iri)
    graph = Graph()

    DCAT = Namespace("http://www.w3.org/ns/dcat#")
    VOID = Namespace("http://rdfs.org/ns/void#")

    graph.bind("dcat", DCAT)
    graph.bind("dcterms", DCTERMS)
    graph.bind("foaf", FOAF)
    graph.bind("owl", OWL)
    graph.bind("rdf", RDF)
    graph.bind("void", VOID)
    graph.bind("xsd", XSD)

    graph.add((dataset, RDF.type, VOID.Dataset))

    literal_fields = (
        ("title", DCTERMS.title),
        ("language", DCTERMS.language),
        ("dsc", DCTERMS.description),
        ("creator", DCTERMS.creator),
        ("contributor", DCTERMS.contributor),
        ("publisher", DCTERMS.publisher),
        ("source", DCTERMS.source),
        ("identifier", DCTERMS.identifier),
        ("date", DCTERMS.date),
        ("created", DCTERMS.created),
        ("issued", DCTERMS.issued),
        ("modified", DCTERMS.modified),
        ("license", DCTERMS.license),
    )
    for field_name, predicate in literal_fields:
        for value in _flatten_and_stringify(profile.get(field_name)):
            if value and not (field_name == "language" and value in {"UNKNOWN", "xx", "ND"}):
                graph.add((dataset, predicate, Literal(value)))

    for sparql in _flatten_and_stringify(profile.get("sparql")):
        if sparql and IS_URI.match(sparql):
            graph.add((dataset, VOID.sparqlEndpoint, URIRef(sparql)))

    for homepage in _flatten_and_stringify(profile.get("homepage")):
        if homepage and IS_URI.match(homepage):
            graph.add((dataset, FOAF.homepage, URIRef(homepage)))

    for uri_regex_pattern in _flatten_and_stringify(profile.get("uri_regex_pattern")):
        if uri_regex_pattern:
            graph.add((dataset, VOID.uriRegexPattern, Literal(uri_regex_pattern)))

    for feature in _flatten_and_stringify(profile.get("feature")):
        if feature and IS_URI.match(feature):
            graph.add((dataset, VOID.feature, URIRef(feature)))

    for example_resource in _flatten_and_stringify(profile.get("example_resource")):
        if example_resource and IS_URI.match(example_resource):
            graph.add((dataset, VOID.exampleResource, URIRef(example_resource)))

    for uri_space in _flatten_and_stringify(profile.get("uri_space")):
        if uri_space:
            graph.add((dataset, VOID.uriSpace, Literal(uri_space)))

    graph.add((dataset, DCTERMS.identifier, Literal(raw_id_str)))

    category = profile.get("category")
    if category:
        graph.add((dataset, DCTERMS.subject, Literal(str(category))))

    statistics = _extract_statistics(profile.get("statistics"))
    triple_count = _coerce_positive_int(statistics.get("triples"))
    entity_count = _coerce_positive_int(statistics.get("entities"))
    class_count = _coerce_positive_int(statistics.get("classes"))
    property_count = _coerce_positive_int(statistics.get("properties"))
    if triple_count:
        graph.add((dataset, VOID.triples, Literal(triple_count, datatype=XSD.integer)))
    if entity_count:
        graph.add((dataset, VOID.entities, Literal(entity_count, datatype=XSD.integer)))
    if class_count:
        graph.add((dataset, VOID.classes, Literal(class_count, datatype=XSD.integer)))
    if property_count:
        graph.add((dataset, VOID.properties, Literal(property_count, datatype=XSD.integer)))

    for partition in _normalize_partition_list(profile.get("class_partitions"), "class", "entities"):
        node = BNode()
        graph.add((dataset, VOID.classPartition, node))
        graph.add((node, VOID["class"], URIRef(partition["class"])))
        if partition["entities"]:
            graph.add((node, VOID.entities, Literal(partition["entities"], datatype=XSD.integer)))

    for partition in _normalize_partition_list(profile.get("property_partitions"), "property", "triples"):
        node = BNode()
        graph.add((dataset, VOID.propertyPartition, node))
        graph.add((node, VOID.property, URIRef(partition["property"])))
        if partition["triples"]:
            graph.add((node, VOID.triples, Literal(partition["triples"], datatype=XSD.integer)))

    for voc in _flatten_and_stringify(profile.get("voc")):
        if voc and IS_URI.match(voc):
            graph.add((dataset, VOID.vocabulary, URIRef(voc)))

    for tag in _flatten_and_stringify(profile.get("tags")):
        if tag:
            graph.add((dataset, DCAT.keyword, Literal(tag)))

    for subject in _flatten_and_stringify(profile.get("sbj")):
        if subject and IS_URI.match(subject):
            graph.add((dataset, DCTERMS.subject, URIRef(subject)))

    for download in _flatten_and_stringify(profile.get("download")):
        if download and IS_URI.match(download):
            graph.add((dataset, VOID.dataDump, URIRef(download)))

    for link in aggregate_same_as_links(profile.get("same_as_links") or profile.get("con")):
        target_dataset = link.get("dataset")
        count = _coerce_positive_int(link.get("count"))
        if not target_dataset or not IS_URI.match(str(target_dataset)) or not count:
            continue

        target = URIRef(str(target_dataset))
        encoded_target = urllib.parse.quote(str(target_dataset), safe="")
        linkset = URIRef(f"{iri.rstrip('/#')}/linkset/{encoded_target}")
        graph.add((linkset, RDF.type, VOID.Linkset))
        graph.add((linkset, VOID.target, dataset))
        graph.add((linkset, VOID.target, target))
        graph.add((linkset, VOID.subjectsTarget, dataset))
        graph.add((linkset, VOID.objectsTarget, target))
        graph.add((linkset, VOID.linkPredicate, OWL.sameAs))
        graph.add((linkset, VOID.triples, Literal(count, datatype=XSD.integer)))
        graph.add((linkset, VOID.subset, dataset))
        graph.add((target, RDF.type, VOID.Dataset))
        graph.add((target, FOAF.homepage, target))

    return graph.serialize(format=rdf_format)


def _flatten_and_stringify(val: Any) -> list[str]:
    """
    Flatten nested lists and convert all items to strings.
    This fixes the 'expected string or bytes-like object, got list' error.
    """
    if val is None:
        return []

    def _flatten_recursive(item: Any) -> list[str]:
        if isinstance(item, list):
            result = []
            for subitem in item:
                result.extend(_flatten_recursive(subitem))
            return result
        else:
            # Convert to string and filter out empty values
            item_str = str(item).strip() if item is not None else ""
            return [item_str] if item_str else []

    if isinstance(val, list):
        return _flatten_recursive(val)
    else:
        val_str = str(val).strip() if val is not None else ""
        return [val_str] if val_str else []


def _extract_first_valid_uri(val: Any) -> str:
    """
    Extract the first valid URI from a value that might be a list, string, or other type.
    Returns empty string if no valid URI is found.
    """
    if val is None:
        return ""

    # If it's a list, try to find the first valid URI
    if isinstance(val, list):
        for item in val:
            if item is not None:
                item_str = str(item).strip()
                if item_str and IS_URI.match(item_str):
                    return item_str
        # If no valid URI found in list, return the first non-empty item as string
        for item in val:
            if item is not None:
                item_str = str(item).strip()
                if item_str:
                    return item_str
        return ""
    else:
        # Single value - convert to string
        val_str = str(val).strip()
        return val_str if val_str else ""


def _escape_sparql_literal(value: str) -> str:
    """Escape special characters in SPARQL literals."""
    if not isinstance(value, str):
        value = str(value)

    # Escape quotes and other special characters
    value = value.replace('\\', '\\\\')  # Escape backslashes first
    value = value.replace('"', '\\"')  # Escape double quotes
    value = value.replace('\n', '\\n')  # Escape newlines
    value = value.replace('\r', '\\r')  # Escape carriage returns
    value = value.replace('\t', '\\t')  # Escape tabs

    return value


def _coerce_positive_int(value: Any) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return 0
    return number if number > 0 else 0


def _parse_statistics_mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        text = value.strip()
        if not text or text == "[]":
            return {}
        try:
            parsed = ast.literal_eval(text)
        except (SyntaxError, ValueError):
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _extract_statistics(value: Any) -> dict[str, int]:
    if isinstance(value, list):
        totals: dict[str, int] = {}
        for item in value:
            for key, val in _parse_statistics_mapping(item).items():
                totals[str(key)] = totals.get(str(key), 0) + _coerce_positive_int(val)
        return totals
    return {str(key): _coerce_positive_int(val) for key, val in _parse_statistics_mapping(value).items()}


def _normalize_partition_list(value: Any, uri_key: str, count_key: str) -> list[dict[str, Any]]:
    if value is None:
        return []
    if isinstance(value, dict):
        value = [value]
    if not isinstance(value, list):
        return []

    partitions = []
    for item in value:
        if isinstance(item, list):
            partitions.extend(_normalize_partition_list(item, uri_key, count_key))
            continue
        if not isinstance(item, dict):
            continue
        uri = item.get(uri_key)
        count = _coerce_positive_int(item.get(count_key))
        if uri and IS_URI.match(str(uri)):
            partitions.append({uri_key: str(uri), count_key: count})
    return partitions


async def store_profile(
        profile: dict[str, Any],
        category: str,
        base_iri: str = "https://www.isislab.it/resource/"
) -> None:
    """Store profile data in triplestore with proper error handling."""

    raw_id = profile.get('id')
    if not raw_id:
        logger.warning("Missing profile id. Skipping insertion.")
        return

    # Initialize iri to avoid "might be referenced before assignment" error
    iri = ""

    try:
        # Extract the actual ID value (handles both lists and single values)
        raw_id_str = _extract_first_valid_uri(raw_id)

        if not raw_id_str:
            logger.warning(f"No valid ID found in raw_id: {raw_id}. Skipping insertion.")
            return

        logger.info(f"Extracted ID: '{raw_id_str}' from raw_id: {raw_id}")

        # Generate IRI - preserve original form if it's already a valid URI
        if IS_URI.match(raw_id_str):
            # Keep the original URI as-is
            iri = raw_id_str
            logger.info(f"Using original URI as IRI: {iri}")
        else:
            # Generate IRI from raw_id
            encoded_id = urllib.parse.quote(raw_id_str, safe="")
            iri = base_iri + encoded_id
            logger.info(f"Generated IRI {iri} from raw id {raw_id_str}")

        # Wrap the final IRI in angle brackets for SPARQL syntax
        iri_formatted = f"<{iri}>"

        # Build main triples with proper literal escaping
        triples = [f"{iri_formatted} rdf:type void:Dataset"]

        # Process basic metadata fields
        for title in _flatten_and_stringify(profile.get('title')):
            if title:
                escaped_title = _escape_sparql_literal(title)
                triples.append(f'{iri_formatted} dcterms:title "{escaped_title}"')

        for language in _flatten_and_stringify(profile.get('language')):
            if language and language not in {'UNKNOWN', 'xx', 'ND'}:
                escaped_lang = _escape_sparql_literal(language)
                triples.append(f'{iri_formatted} dcterms:language "{escaped_lang}"')

        for dsc in _flatten_and_stringify(profile.get('dsc')):
            if dsc:
                escaped_dsc = _escape_sparql_literal(dsc)
                triples.append(f'{iri_formatted} dcterms:description "{escaped_dsc}"')

        for creator in _flatten_and_stringify(profile.get('creator')):
            if creator:
                escaped_creator = _escape_sparql_literal(creator)
                triples.append(f'{iri_formatted} dcterms:creator "{escaped_creator}"')

        for contributor in _flatten_and_stringify(profile.get('contributor')):
            if contributor:
                escaped_contributor = _escape_sparql_literal(contributor)
                triples.append(f'{iri_formatted} dcterms:contributor "{escaped_contributor}"')

        for publisher in _flatten_and_stringify(profile.get('publisher')):
            if publisher:
                escaped_publisher = _escape_sparql_literal(publisher)
                triples.append(f'{iri_formatted} dcterms:publisher "{escaped_publisher}"')

        for source in _flatten_and_stringify(profile.get('source')):
            if source:
                escaped_source = _escape_sparql_literal(source)
                triples.append(f'{iri_formatted} dcterms:source "{escaped_source}"')

        for identifier in _flatten_and_stringify(profile.get('identifier')):
            if identifier:
                escaped_identifier = _escape_sparql_literal(identifier)
                triples.append(f'{iri_formatted} dcterms:identifier "{escaped_identifier}"')

        for date in _flatten_and_stringify(profile.get('date')):
            if date:
                escaped_date = _escape_sparql_literal(date)
                triples.append(f'{iri_formatted} dcterms:date "{escaped_date}"')

        for created in _flatten_and_stringify(profile.get('created')):
            if created:
                escaped_created = _escape_sparql_literal(created)
                triples.append(f'{iri_formatted} dcterms:created "{escaped_created}"')

        for issued in _flatten_and_stringify(profile.get('issued')):
            if issued:
                escaped_issued = _escape_sparql_literal(issued)
                triples.append(f'{iri_formatted} dcterms:issued "{escaped_issued}"')

        for modified in _flatten_and_stringify(profile.get('modified')):
            if modified:
                escaped_modified = _escape_sparql_literal(modified)
                triples.append(f'{iri_formatted} dcterms:modified "{escaped_modified}"')

        for lic in _flatten_and_stringify(profile.get('license')):
            if lic:
                escaped_lic = _escape_sparql_literal(lic)
                triples.append(f'{iri_formatted} dcterms:license "{escaped_lic}"')

        # Process URIs (sparql endpoints) - preserve original form
        for sparql in _flatten_and_stringify(profile.get('sparql')):
            if sparql and IS_URI.match(sparql):
                triples.append(f'{iri_formatted} void:sparqlEndpoint <{sparql}>')

        for homepage in _flatten_and_stringify(profile.get('homepage')):
            if homepage and IS_URI.match(homepage):
                triples.append(f'{iri_formatted} foaf:homepage <{homepage}>')

        for uri_regex_pattern in _flatten_and_stringify(profile.get('uri_regex_pattern')):
            if uri_regex_pattern:
                escaped_uri_regex_pattern = _escape_sparql_literal(uri_regex_pattern)
                triples.append(f'{iri_formatted} void:uriRegexPattern "{escaped_uri_regex_pattern}"')

        for feature in _flatten_and_stringify(profile.get('feature')):
            if feature and IS_URI.match(feature):
                triples.append(f'{iri_formatted} void:feature <{feature}>')

        for example_resource in _flatten_and_stringify(profile.get('example_resource')):
            if example_resource and IS_URI.match(example_resource):
                triples.append(f'{iri_formatted} void:exampleResource <{example_resource}>')

        for uri_space in _flatten_and_stringify(profile.get('uri_space')):
            if uri_space:
                escaped_uri_space = _escape_sparql_literal(uri_space)
                triples.append(f'{iri_formatted} void:uriSpace "{escaped_uri_space}"')

        # Add identifier and category/domain (use the extracted string, not the original raw_id)
        escaped_raw_id = _escape_sparql_literal(raw_id_str)
        triples.append(f'{iri_formatted} dcterms:identifier "{escaped_raw_id}"')

        escaped_category = _escape_sparql_literal(str(category))
        triples.append(f'{iri_formatted} dcterms:subject "{escaped_category}"')

        statistics = _extract_statistics(profile.get("statistics"))
        triple_count = _coerce_positive_int(statistics.get("triples"))
        entity_count = _coerce_positive_int(statistics.get("entities"))
        class_count = _coerce_positive_int(statistics.get("classes"))
        property_count = _coerce_positive_int(statistics.get("properties"))
        if triple_count:
            triples.append(f"{iri_formatted} void:triples {triple_count}")
        if entity_count:
            triples.append(f"{iri_formatted} void:entities {entity_count}")
        if class_count:
            triples.append(f"{iri_formatted} void:classes {class_count}")
        if property_count:
            triples.append(f"{iri_formatted} void:properties {property_count}")

        insert_data = " .\n".join(triples) + " ."

        query_main = f"""
            PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
            PREFIX dcat: <http://www.w3.org/ns/dcat#>
            PREFIX owl: <http://www.w3.org/2002/07/owl#>
            PREFIX dcterms: <http://purl.org/dc/terms/>
            PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>
            PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
            PREFIX foaf: <http://xmlns.com/foaf/0.1/>
            PREFIX void: <http://rdfs.org/ns/void#>

            INSERT DATA {{
            {insert_data}
            }}
            """.strip()

        await _update_query(query_main)
        logger.info(f"Successfully inserted main profile data for IRI: {iri}")

    except Exception as error:
        logger.error(f"Cannot insert main profile data with iri: {iri}. Error: {error}")
        return

    # Insert VoID linksets for owl:sameAs connections grouped by linked KG
    try:
        same_as_links = aggregate_same_as_links(profile.get('same_as_links') or profile.get('con'))
        linkset_triples = ""
        for link in same_as_links:
            target_dataset = link.get("dataset")
            count = link.get("count")
            if not target_dataset or not IS_URI.match(str(target_dataset)):
                continue
            try:
                count_int = int(count)
            except (TypeError, ValueError):
                continue
            if count_int <= 0:
                continue

            encoded_target = urllib.parse.quote(str(target_dataset), safe="")
            linkset_iri = f"{iri.rstrip('/#')}/linkset/{encoded_target}"
            linkset_formatted = f"<{linkset_iri}>"
            target_formatted = f"<{target_dataset}>"
            linkset_triples += (
                f"{linkset_formatted} rdf:type void:Linkset .\n"
                f"{linkset_formatted} void:target {iri_formatted} .\n"
                f"{linkset_formatted} void:target {target_formatted} .\n"
                f"{linkset_formatted} void:subjectsTarget {iri_formatted} .\n"
                f"{linkset_formatted} void:objectsTarget {target_formatted} .\n"
                f"{linkset_formatted} void:linkPredicate owl:sameAs .\n"
                f"{linkset_formatted} void:triples {count_int} .\n"
                f"{linkset_formatted} void:subset {iri_formatted} .\n"
                f"{target_formatted} rdf:type void:Dataset .\n"
                f"{target_formatted} foaf:homepage {target_formatted} .\n"
            )

        if linkset_triples:
            query_linksets = f"""
                PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
                PREFIX void: <http://rdfs.org/ns/void#>
                PREFIX owl: <http://www.w3.org/2002/07/owl#>
                PREFIX foaf: <http://xmlns.com/foaf/0.1/>
                INSERT DATA {{
                {linkset_triples.rstrip()}
                }}
            """.strip()

            await _update_query(query_linksets)
            logger.info(f"Successfully inserted owl:sameAs linksets for IRI: {iri}")

    except Exception as error:
        logger.warning(f"Cannot insert owl:sameAs linksets for IRI: {iri}. Error: {error}")

    # Insert VoID class and property partitions
    try:
        partition_triples = ""
        for partition in _normalize_partition_list(profile.get("class_partitions"), "class", "entities"):
            partition_triples += f"{iri_formatted} void:classPartition [\n"
            if partition["entities"]:
                partition_triples += (
                    f"    void:class <{partition['class']}> ;\n"
                    f"    void:entities {partition['entities']}\n"
                )
            else:
                partition_triples += f"    void:class <{partition['class']}>\n"
            partition_triples += "] .\n"

        for partition in _normalize_partition_list(profile.get("property_partitions"), "property", "triples"):
            partition_triples += f"{iri_formatted} void:propertyPartition [\n"
            if partition["triples"]:
                partition_triples += (
                    f"    void:property <{partition['property']}> ;\n"
                    f"    void:triples {partition['triples']}\n"
                )
            else:
                partition_triples += f"    void:property <{partition['property']}>\n"
            partition_triples += "] .\n"

        if partition_triples:
            query_partitions = f"""
                PREFIX void: <http://rdfs.org/ns/void#>
                INSERT DATA {{
                {partition_triples.rstrip()}
                }}
            """.strip()

            await _update_query(query_partitions)
            logger.info(f"Successfully inserted class/property partitions for IRI: {iri}")

    except Exception as error:
        logger.warning(f"Cannot insert class/property partitions for IRI: {iri}. Error: {error}")

    # Insert vocabulary and keyword data
    try:
        vocab_triples = ""
        for voc in _flatten_and_stringify(profile.get('voc')):
            if voc and IS_URI.match(voc):
                # Preserve original URI form
                vocab_triples += f"{iri_formatted} void:vocabulary <{voc}> .\n"

        keyword_triples = ""
        for tag in _flatten_and_stringify(profile.get('tags')):
            if tag:
                escaped_tag = _escape_sparql_literal(tag)
                keyword_triples += f'{iri_formatted} dcat:keyword "{escaped_tag}" .\n'

        if vocab_triples or keyword_triples:
            query_vocab = f"""
                PREFIX void: <http://rdfs.org/ns/void#>
                PREFIX dcat: <http://www.w3.org/ns/dcat#>
                INSERT DATA {{
                {vocab_triples.rstrip()}
                {keyword_triples.rstrip()}
            }}
            """.strip()

            await _update_query(query_vocab)
            logger.info(f"Successfully inserted vocabulary and keyword data for IRI: {iri}")

    except Exception as error:
        logger.warning(f"Cannot insert vocabulary or keyword data for IRI: {iri}. Error: {error}")

    # Insert subject data
    try:
        subject_triples = ""
        for subj in _flatten_and_stringify(profile.get('sbj')):
            if subj and IS_URI.match(subj):
                subject_triples += f'{iri_formatted} dcterms:subject <{subj}> .\n'

        if subject_triples:
            query_subject = f"""
            PREFIX dcterms: <http://purl.org/dc/terms/>
            INSERT DATA {{
            {subject_triples.rstrip()}
            }}
            """.strip()

            await _update_query(query_subject)
            logger.info(f"Successfully inserted subject data for IRI: {iri}")
    except Exception as error:
        logger.warning(f"Cannot insert subject for IRI: {iri}. Error: {error}")

    try:

        download_triples = ""
        if profile.get('download'):
            for download in _flatten_and_stringify(profile.get('download')):
                if download and IS_URI.match(download):
                    download_triples += f'{iri_formatted} void:dataDump <{download}> .\n'

        if download_triples:
            query_download = f"""
            PREFIX void: <http://rdfs.org/ns/void#>
            INSERT DATA {{
            {download_triples.rstrip()}
            }}
            """.strip()

            await _update_query(query_download)
            logger.info(f"Successfully inserted dump data for IRI: {iri}")

    except Exception as error:
        logger.warning(f"Cannot insert download data for IRI: {iri}. Error: {error}")


if __name__ == '__main__':
    load_predictor()
    asyncio.run(generate_profile_from_store())
