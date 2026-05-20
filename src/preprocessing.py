import argparse
import ast
import logging
import os
import re
import gc
from typing import Any

import pandas as pd
import spacy
from langdetect import detect, DetectorFactory, LangDetectException
from pandas import Series

from config import Config
from src.util import (
    is_curi_allowed,
    is_voc_allowed,
    merge_dataset,
    merge_void_dataset,
    RAW_DIR,
    PROCESSED_DIR,
)
from src.void_linksets import aggregate_same_as_links

DetectorFactory.seed = 42

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

SPACY_LANGS = {
    "en": "en_core_web_trf",
    "it": "it_core_news_lg",
    "es": "es_dep_news_trf",
    "de": "de_dep_news_trf",
    "nl": "nl_core_news_lg",
    "fr": "fr_dep_news_trf",
    "ru": "ru_core_news_lg",
    "zh": "zh_core_web_trf",
    "ja": "ja_core_news_trf",
    "pt": "pt_core_news_lg",
}

# Global flag to control GPU usage when loading pipelines
USE_GPU_ON_IMPORT = False


def _load_spacy_pipelines_on_demand(enable_gpu: bool = False):
    """Initialize an empty spaCy pipeline dictionary and optionally enable GPU."""
    if enable_gpu:
        try:
            spacy.require_gpu()
            logger.info("spaCy using GPU for pipelines")
        except Exception as exc:
            logger.warning(f"Could not enable spaCy GPU mode: {exc}")
    return {}, None


def unload_spacy_pipelines(pipeline_dict_local=None):
    """Clear references to spaCy pipelines and trigger garbage collection."""
    global pipeline_dict, fallback_pipeline

    use_dict = pipeline_dict_local if pipeline_dict_local is not None else pipeline_dict

    logger.info(f"Unloading {len(use_dict)} spaCy pipeline(s)...")
    use_dict.clear()

    if pipeline_dict_local is None:
        pipeline_dict = {}
        fallback_pipeline = None

    gc.collect()
    logger.info("spaCy pipelines unloaded and garbage collection triggered")


# Global spaCy pipeline registry (pipelines are loaded on demand)
pipeline_dict, fallback_pipeline = _load_spacy_pipelines_on_demand(enable_gpu=USE_GPU_ON_IMPORT)


def get_or_load_pipeline(lang_code: str, pipeline_dict_local=None, fallback_pipeline_local=None):
    use_dict = pipeline_dict_local if pipeline_dict_local is not None else pipeline_dict
    use_fallback = fallback_pipeline_local if fallback_pipeline_local is not None else fallback_pipeline

    if lang_code in use_dict:
        return use_dict[lang_code]
    if lang_code in SPACY_LANGS:
        model_name = SPACY_LANGS[lang_code]
        try:
            nlp = spacy.load(model_name)
            use_dict[lang_code] = nlp
            logger.info(f"Loaded spaCy pipeline for '{lang_code}': {model_name}")
            return nlp
        except Exception as exc:
            logger.warning(f"spaCy pipeline missing for '{lang_code}' ({model_name}): {exc}")
    if "xx" not in use_dict:
        if use_fallback is not None:
            use_dict["xx"] = use_fallback
            logger.info("Loaded fallback pipeline from provided fallback_pipeline")
        else:
            try:
                use_dict["xx"] = spacy.load("xx_sent_ud_sm")
                logger.info("Loaded multilingual fallback pipeline: xx_sent_ud_sm")
            except Exception as exc:
                logger.warning(f"Error loading multilingual fallback pipeline: {exc}")
                use_dict["xx"] = spacy.blank("en")
    return use_dict["xx"]


def setup_spacy_pipelines():
    global pipeline_dict, fallback_pipeline
    return pipeline_dict, fallback_pipeline


def get_spacy_lang_code(detected: str) -> str:
    return detected if detected in SPACY_LANGS else "xx"


def find_language(text: Any) -> str:
    if not isinstance(text, str) or not text:
        return ""
    try:
        code = detect(text)
        return code or ""
    except LangDetectException:
        return ""
    except Exception as exc:
        logger.error(f'Error in find_language("{str(text)[:50]}"): {exc}')
        return ""


def spacy_clean_normalize_single(text, pipeline_dict_local=None, fallback_pipeline_local=None):
    """Lemmatize and clean a single text using spaCy, no batching."""
    if not isinstance(text, str) or not text.strip():
        return ""

    use_dict = pipeline_dict_local if pipeline_dict_local is not None else pipeline_dict
    use_fallback = fallback_pipeline_local if fallback_pipeline_local is not None else fallback_pipeline

    try:
        lang_code = find_language(text)
        nlp = get_or_load_pipeline(lang_code, use_dict, use_fallback)
        doc = nlp(text)
        tokens = [
            token.lemma_.lower()
            for token in doc
            if not token.is_stop and not token.is_punct and not token.is_space
        ]
        return " ".join(tokens)
    except Exception as exc:
        logger.error(f"Error processing text: {exc}")
        return ""


def spacy_clean_normalize_list(texts, pipeline_dict_local=None, fallback_pipeline_local=None):
    """Normalize a list of texts one by one."""
    if not isinstance(texts, list) or not texts:
        return []

    result = []
    for text in texts:
        normalized = spacy_clean_normalize_single(text, pipeline_dict_local, fallback_pipeline_local)
        result.append(normalized)
    return result


def sanitize_field(value: Any) -> Any:
    if isinstance(value, list) and not value:
        return ""
    if isinstance(value, str) and value.strip() == "[]":
        return ""
    if isinstance(value, list):
        return remove_duplicates(value)
    return value


def analyze_uri(uri: str) -> dict[str, str]:
    uri_fragment_pattern = re.compile(r"[#/](?P<fragment>[^#/]+)$")
    uri_namespace_pattern = re.compile(r"^(?P<ns>.*?)[#/][^#/]+$")
    tld_pattern = re.compile(r"^(?:https?://)?(?:www\.)?(?P<tld>[^/]+)")
    result: dict[str, str] = {"namespace": "", "local_name": "", "tld": ""}
    if not uri or not isinstance(uri, str):
        return result
    frag_match = uri_fragment_pattern.search(uri)
    if frag_match:
        result["local_name"] = frag_match.group("fragment")
    ns_match = uri_namespace_pattern.match(uri)
    if ns_match:
        result["namespace"] = ns_match.group("ns")
    else:
        result["namespace"] = uri
    tld_match = tld_pattern.match(uri)
    if tld_match:
        result["tld"] = tld_match.group("tld")
    return result


def normalize_text_list(text_list: Any) -> str:
    if not text_list:
        return ""
    if isinstance(text_list, str):
        return text_list
    if isinstance(text_list, list):
        return " ".join(str(x) for x in text_list if x is not None)
    return ""


def remove_duplicates(series_or_list: Any) -> list[str]:
    if isinstance(series_or_list, pd.Series):
        items = series_or_list.dropna().astype(str).tolist()
    elif isinstance(series_or_list, list):
        items = [str(x) for x in series_or_list]
    else:
        return []
    unique = set(items)
    unique.discard("None")
    unique.discard("")
    return sorted(unique)


def flatten_text_values(value: Any) -> list[str]:
    result: list[str] = []

    def _visit(item: Any) -> None:
        if item is None:
            return
        if isinstance(item, pd.Series):
            for subitem in item.dropna().tolist():
                _visit(subitem)
            return
        if isinstance(item, list | tuple | set):
            for subitem in item:
                _visit(subitem)
            return
        text = str(item).strip()
        if not text or text in {"None", "[]"}:
            return
        result.append(text)

    _visit(value)
    return remove_duplicates(result)


def parse_mapping(value: Any) -> dict[str, Any]:
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


def remove_empty_list_values(df: pd.DataFrame) -> pd.DataFrame:
    def _replacer(x: Any) -> Any:
        if isinstance(x, list) and not x:
            return ""
        if isinstance(x, str) and x.strip() == "[]":
            return ""
        return x

    return df.map(_replacer)


def aggregate_partitions(values: Any, uri_key: str, count_key: str) -> list[dict[str, Any]]:
    totals: dict[str, int] = {}

    def _visit(item: Any) -> None:
        if isinstance(item, list):
            for subitem in item:
                _visit(subitem)
            return
        if not isinstance(item, dict):
            return
        uri = item.get(uri_key)
        if not uri:
            return
        try:
            count = int(item.get(count_key, 0))
        except (TypeError, ValueError):
            count = 0
        totals[str(uri)] = totals.get(str(uri), 0) + count

    _visit(values)
    return [
        {uri_key: uri, count_key: count}
        for uri, count in sorted(totals.items(), key=lambda pair: (-pair[1], pair[0]))
    ]


def aggregate_statistics(values: Any) -> dict[str, int]:
    totals = {"triples": 0, "entities": 0, "classes": 0, "properties": 0}

    def _visit(item: Any) -> None:
        if isinstance(item, list):
            for subitem in item:
                _visit(subitem)
            return
        parsed = parse_mapping(item)
        if not parsed:
            return
        for key in totals:
            try:
                totals[key] += int(parsed.get(key, 0))
            except (TypeError, ValueError):
                continue

    _visit(values)
    return {key: value for key, value in totals.items() if value > 0}


def extract_named_entities(
    lab_list: Any, pipeline_dict_local=None, fallback_pipeline_local=None, use_ner: bool = True
) -> list[str]:
    if not use_ner or not isinstance(lab_list, list):
        return []

    use_dict = pipeline_dict_local if pipeline_dict_local is not None else pipeline_dict
    use_fallback = fallback_pipeline_local if fallback_pipeline_local is not None else fallback_pipeline
    entity_types: set[str] = set()

    for text in lab_list:
        if not isinstance(text, str) or not text:
            continue
        try:
            lang_code = find_language(text)
            chosen_nlp = get_or_load_pipeline(lang_code, use_dict, use_fallback)
            doc = chosen_nlp(text)
            for ent in doc.ents:
                if ent.label_:
                    entity_types.add(ent.label_)
        except Exception as exc:
            logger.error(f'NER failure on "{text[:50]}": {exc}')
    return sorted(entity_types)


def filter_uri_list(uri_list, filter_func=None):
    if uri_list is None:
        return []
    if not isinstance(uri_list, list):
        uri_list = [uri_list] if isinstance(uri_list, str) and uri_list else []
    if filter_func is not None:
        return [uri for uri in uri_list if filter_func(uri)]
    return uri_list


def extract_local_names(uri_list):
    if uri_list is None:
        return []
    if not isinstance(uri_list, list):
        uri_list = [uri_list] if isinstance(uri_list, str) and uri_list else []

    local_names: set[str] = set()
    for uri in uri_list:
        if not uri or not isinstance(uri, str):
            continue
        if "#" in uri:
            local_name = uri.split("#")[-1]
        elif "/" in uri:
            local_name = uri.rstrip("/").split("/")[-1]
        else:
            local_name = uri
        if local_name:
            local_names.add(local_name)
    return sorted(local_names)


def process_row(
    row: dict[str, Any] | Series,
    idx: int,
    total: int,
    pipeline_dict_int=None,
    fallback_pipeline_int=None,
    enable_filter: bool = Config.USE_FILTER,
) -> tuple[str, list[str], list[str], list[str], list[str], list[str]]:
    logger.info(f"Processing row {idx}/{total}...")

    lab_raw = row.get("lab", [])
    if not isinstance(lab_raw, list):
        lab_raw = [lab_raw] if lab_raw else []

    lab_normalized: list[str] = []
    for lab_item in lab_raw:
        if isinstance(lab_item, str):
            lab_item_stripped = lab_item.strip()
            if lab_item_stripped:
                normalized = spacy_clean_normalize_single(
                    lab_item_stripped, pipeline_dict_int, fallback_pipeline_int
                )
                if normalized and normalized.strip():
                    lab_normalized.append(normalized.strip())

    lab_text = " ".join(lab_normalized)

    if enable_filter:
        curi = filter_uri_list(sanitize_field(row.get("curi", [])), is_curi_allowed)
        puri = filter_uri_list(sanitize_field(row.get("puri", [])), is_voc_allowed)
        voc = filter_uri_list(sanitize_field(row.get("voc", [])), is_voc_allowed)
    else:
        curi = sanitize_field(row.get("curi", []))
        puri = sanitize_field(row.get("puri", []))
        voc = sanitize_field(row.get("voc", []))

    lcn = extract_local_names(curi)
    lpn = extract_local_names(puri)

    logger.info(f"Completed row {idx}/{total}")
    return lab_text, lcn, lpn, curi, puri, voc


def preprocess_combined(
    input_frame: pd.DataFrame,
    pipeline_dict_int,
    fallback_pipeline_int,
    use_ner: bool = True,
    enable_filter: bool = Config.USE_FILTER,
) -> pd.DataFrame:
    total = len(input_frame)
    combined_rows: list[dict[str, Any]] = []

    for i, (_, row) in enumerate(input_frame.iterrows(), start=1):
        lab_text, lcn, lpn, curi, puri, voc = process_row(
            row, i, total, pipeline_dict_int, fallback_pipeline_int, enable_filter=enable_filter
        )

        title_raw = sanitize_field(row.get("title", ""))
        title = title_raw
        dsc = row.get("dsc", "")
        tlds = sanitize_field(row.get("tlds", ""))
        sparql = sanitize_field(row.get("sparql", ""))
        creator = row.get("creator", "")
        contributor = row.get("contributor", "")
        publisher = row.get("publisher", "")
        source = row.get("source", "")
        identifier = row.get("identifier", "")
        date = row.get("date", "")
        created = row.get("created", "")
        issued = row.get("issued", "")
        modified = row.get("modified", "")
        uri_regex_pattern = row.get("uri_regex_pattern", "")
        feature = row.get("feature", "")
        example_resource = row.get("example_resource", "")
        uri_space = row.get("uri_space", "")
        void_metadata = row.get("void_metadata", "")
        license_ = row.get("license", "")

        lab_list = row.get("lab", [])
        if not isinstance(lab_list, list):
            lab_list = [lab_list] if lab_list else []

        ner_types = extract_named_entities(
            lab_list, pipeline_dict_int, fallback_pipeline_int, use_ner=use_ner
        )
        language = find_language(lab_text[:1000])

        combined_rows.append(
            {
                "id": row.get("id", ""),
                "category": row.get("category", ""),
                "title": title,
                "dsc": dsc,
                "lab": lab_text,
                "lcn": lcn,
                "lpn": lpn,
                "curi": curi,
                "puri": puri,
                "class_partitions": row.get("class_partitions", ""),
                "property_partitions": row.get("property_partitions", ""),
                "statistics": row.get("statistics", ""),
                "voc": voc,
                "tlds": tlds,
                "sparql": sparql,
                "creator": creator,
                "contributor": contributor,
                "publisher": publisher,
                "source": source,
                "identifier": identifier,
                "date": date,
                "created": created,
                "issued": issued,
                "modified": modified,
                "uri_regex_pattern": uri_regex_pattern,
                "feature": feature,
                "example_resource": example_resource,
                "uri_space": uri_space,
                "void_metadata": void_metadata,
                "license": license_,
                "ner": ner_types,
                "language": language,
                "con": row.get("con", ""),
                "same_as_links": row.get("same_as_links", ""),
            }
        )

    combined_df = pd.DataFrame(combined_rows)
    logger.info(f"Combined processing complete: {len(combined_df)}/{total}")
    return combined_df


def process_void_row(
    row: dict[str, Any] | Series, idx: int, total: int, pipeline_dict_int=None, fallback_pipeline_int=None
) -> dict[str, str]:
    logger.info(f"Processing void row {idx}/{total}...")

    dsc_raw = normalize_text_list(row.get("dsc", []))
    dsc_text = spacy_clean_normalize_single(dsc_raw, pipeline_dict_int, fallback_pipeline_int)
    if not dsc_text and dsc_raw:
        dsc_text = dsc_raw

    sbj_raw = normalize_text_list(row.get("sbj", []))
    sbj_text = spacy_clean_normalize_single(sbj_raw, pipeline_dict_int, fallback_pipeline_int)
    if not sbj_text and sbj_raw:
        sbj_text = sbj_raw

    download_raw = normalize_text_list(row.get("download", []))

    logger.info(f"Completed void row {idx}/{total}")
    return {"sbj": sbj_text, "dsc": dsc_text, "download": download_raw}


def preprocess_void(
    input_frame: pd.DataFrame, pipeline_dict_int=None, fallback_pipeline_int=None
) -> pd.DataFrame:
    total = len(input_frame)
    processed_rows: list[dict[str, str]] = []

    for i, (_, row) in enumerate(input_frame.iterrows(), start=1):
        processed_rows.append(process_void_row(row, i, total, pipeline_dict_int, fallback_pipeline_int))

    out_df = pd.DataFrame(
        {
            "id": input_frame["id"] if "id" in input_frame.columns else list(range(total)),
            "sbj": [r["sbj"] for r in processed_rows],
            "dsc": [r["dsc"] for r in processed_rows],
            "download": [r["download"] for r in processed_rows],
        }
    )
    logger.info(f"Void processing complete: {len(out_df)}/{total}")
    return out_df


def combine_with_void(combined_df: pd.DataFrame, void_df: pd.DataFrame) -> pd.DataFrame:
    merged_final = pd.merge(combined_df, void_df, on="id", how="outer", suffixes=("", "_dup"))
    dup_cols = [col for col in merged_final.columns if col.endswith("_dup")]
    if dup_cols:
        merged_final = merged_final.drop(columns=dup_cols)
    if "id" in merged_final.columns:
        merged_final = merged_final.drop_duplicates(subset="id")
    if "category" in merged_final.columns:
        merged_final = merged_final.dropna(subset=["category"])
        merged_final = merged_final[merged_final["category"].astype(str).ne("")]
    logger.info(f"Merged with void; resulting rows: {len(merged_final)}")
    return merged_final


def combine_with_void_and_lov_data(
    combined_df: pd.DataFrame, void_df: pd.DataFrame, lov_df: pd.DataFrame
) -> pd.DataFrame:
    temp = combine_with_void(combined_df, void_df)
    final = combine_with_void(temp, lov_df)
    return final


def process_lov_data_row(
    row: dict[str, Any] | Series, idx: int, total: int, pipeline_dict_int=None, fallback_pipeline_int=None
) -> dict[str, Any]:
    logger.info(f"Processing LOV row {idx}/{total}...")
    tags = sanitize_field(row.get("tags", []))

    def _flatten(l):
        if l is None:
            return
        for el in l:
            if isinstance(el, list):
                yield from _flatten(el)
            else:
                yield el

    comments_value = row.get("comments", [])
    if isinstance(comments_value, list):
        comments_list = list(_flatten(comments_value))
    else:
        comments_list = [comments_value]

    comments_normalized: list[str] = []
    for comment in comments_list:
        if isinstance(comment, str) and comment.strip():
            normalized = spacy_clean_normalize_single(comment, pipeline_dict_int, fallback_pipeline_int)
            if normalized:
                comments_normalized.append(normalized)

    comments = " ".join(comments_normalized)

    logger.info(f"Completed LOV row {idx}/{total}")
    return {"tags": tags, "comments": comments}


def preprocess_lov_data(
    input_frame: pd.DataFrame, pipeline_dict_int=None, fallback_pipeline_int=None
) -> pd.DataFrame:
    total = len(input_frame)
    processed_rows: list[dict[str, Any]] = []

    for i, (_, row) in enumerate(input_frame.iterrows(), start=1):
        processed_rows.append(process_lov_data_row(row, i, total, pipeline_dict_int, fallback_pipeline_int))

    out_df = pd.DataFrame(
        {
            "id": input_frame["id"] if "id" in input_frame.columns else list(range(total)),
            "tags": [r["tags"] for r in processed_rows],
            "comments": [r["comments"] for r in processed_rows],
        }
    )
    logger.info(f"LOV processing complete: {len(out_df)}/{total}")
    return out_df


def process_all_from_input(
    input_data: Any,
    use_ner: bool = True,
    enable_filter: bool = True,
) -> dict[str, list[Any]]:
    """
    Preprocess input data and return aggregated features.
    spaCy pipelines are loaded on demand and always unloaded in a finally block.
    """
    global pipeline_dict, fallback_pipeline

    pipeline_dict, fallback_pipeline = _load_spacy_pipelines_on_demand(
        enable_gpu=USE_GPU_ON_IMPORT
    )

    try:
        if isinstance(input_data, dict):
            if not input_data:
                raise ValueError("Input dict is empty")
            converted: dict[str, list[Any]] = {}
            for k, v in input_data.items():
                converted[k] = v if isinstance(v, list) else [v]
            max_len = max(len(lst) for lst in converted.values())
            for k, lst in converted.items():
                if len(lst) < max_len:
                    converted[k] = lst + [None] * (max_len - len(lst))
            df = pd.DataFrame(converted)
        elif isinstance(input_data, pd.DataFrame):
            if input_data.empty:
                raise ValueError("Input DataFrame is empty")
            df = input_data.copy()
        else:
            raise ValueError("Input must be a dict or a pandas DataFrame")

        logger.info(f"Converted input data to DataFrame ({len(df)} rows)")

        combined_df = preprocess_combined(
            df,
            pipeline_dict,
            fallback_pipeline,
            use_ner=use_ner,
            enable_filter=enable_filter,
        )
        void_df = preprocess_void(df, pipeline_dict, fallback_pipeline)

        tags: list[Any] = []
        if Config.QUERY_LOV and isinstance(input_data, dict):
            tags = remove_duplicates(input_data.get("tags", []))

        if isinstance(input_data, dict):
            same_as_links = aggregate_same_as_links(input_data.get("same_as_links") or input_data.get("con", []))
        else:
            same_as_links = aggregate_same_as_links(combined_df["same_as_links"].tolist())
            if not same_as_links:
                same_as_links = aggregate_same_as_links(combined_df["con"].tolist())

        result: dict[str, list[Any]] = {
            "id": remove_duplicates(combined_df["id"].tolist()),
            "title": remove_duplicates(combined_df["title"].tolist()),
            "lab": remove_duplicates(combined_df["lab"].tolist()),
            "lcn": remove_duplicates(sum(combined_df["lcn"].tolist(), [])),
            "lpn": remove_duplicates(sum(combined_df["lpn"].tolist(), [])),
            "curi": remove_duplicates(sum(combined_df["curi"].tolist(), [])),
            "puri": remove_duplicates(sum(combined_df["puri"].tolist(), [])),
            "class_partitions": aggregate_partitions(combined_df["class_partitions"].tolist(), "class", "entities"),
            "property_partitions": aggregate_partitions(
                combined_df["property_partitions"].tolist(), "property", "triples"
            ),
            "statistics": aggregate_statistics(combined_df["statistics"].tolist()),
            "voc": remove_duplicates(sum(combined_df["voc"].tolist(), [])),
            "tlds": remove_duplicates(combined_df["tlds"].tolist()),
            "sparql": remove_duplicates(combined_df["sparql"].tolist()),
            "creator": remove_duplicates(combined_df["creator"].tolist()),
            "contributor": remove_duplicates(combined_df["contributor"].tolist()),
            "publisher": remove_duplicates(combined_df["publisher"].tolist()),
            "source": remove_duplicates(combined_df["source"].tolist()),
            "identifier": remove_duplicates(combined_df["identifier"].tolist()),
            "date": remove_duplicates(combined_df["date"].tolist()),
            "created": remove_duplicates(combined_df["created"].tolist()),
            "issued": remove_duplicates(combined_df["issued"].tolist()),
            "modified": remove_duplicates(combined_df["modified"].tolist()),
            "uri_regex_pattern": remove_duplicates(combined_df["uri_regex_pattern"].tolist()),
            "feature": flatten_text_values(combined_df["feature"].tolist() if "feature" in combined_df else []),
            "example_resource": flatten_text_values(
                combined_df["example_resource"].tolist() if "example_resource" in combined_df else []
            ),
            "uri_space": flatten_text_values(combined_df["uri_space"].tolist() if "uri_space" in combined_df else []),
            "void_metadata": combined_df["void_metadata"].dropna().tolist(),
            "download": flatten_text_values(void_df["download"].tolist()),
            "license": remove_duplicates(combined_df["license"].tolist()),
            "language": remove_duplicates([value for value in combined_df["language"].tolist() if value]),
            "dsc": flatten_text_values(combined_df["dsc"].tolist() if "dsc" in combined_df else [])
            or flatten_text_values(void_df["dsc"].tolist() if "dsc" in void_df else []),
            "sbj": flatten_text_values(void_df["sbj"].tolist()),
            "ner": remove_duplicates(sum(combined_df["ner"].tolist(), [])),
            "con": remove_duplicates(combined_df["con"].tolist()),
            "same_as_links": same_as_links,
            "tags": tags,
        }

        if isinstance(input_data, dict):
            result["dsc"] = result["dsc"] or flatten_text_values(input_data.get("dsc", []))

        return result

    finally:
        unload_spacy_pipelines()


def main(use_ner: bool = True, use_gpu: bool = False, enable_filter: bool = True) -> None:
    """
    Batch preprocessing pipeline invoked from CLI.
    spaCy pipelines are always unloaded in a finally block.
    """
    global USE_GPU_ON_IMPORT, pipeline_dict, fallback_pipeline

    logger.info(
        f"Starting preprocessing workflow. NER enabled: {use_ner}, GPU enabled: {use_gpu}, filter enabled: {enable_filter}"
    )

    USE_GPU_ON_IMPORT = use_gpu
    pipeline_dict, fallback_pipeline = _load_spacy_pipelines_on_demand(enable_gpu=USE_GPU_ON_IMPORT)

    try:
        df = merge_dataset()
        logger.info(f"Merged dataset contains {len(df)} rows")

        combined_df = preprocess_combined(
            df,
            pipeline_dict,
            fallback_pipeline,
            use_ner=use_ner,
            enable_filter=enable_filter,
        )
        logger.info(f"After combined preprocessing: {len(combined_df)} rows")

        void_df = preprocess_void(merge_void_dataset(), pipeline_dict, fallback_pipeline)
        logger.info(f"After void preprocessing: {len(void_df)} rows")

        lov_raw = pd.read_json(os.path.join(RAW_DIR, "lov_cloud", "voc_cmt.json"))
        logger.info(f"Loaded LOV raw data: {len(lov_raw)} rows")

        lov_data = preprocess_lov_data(lov_raw, pipeline_dict, fallback_pipeline)
        logger.info(f"After LOV preprocessing: {len(lov_data)} rows")

        final_df = combine_with_void_and_lov_data(combined_df, void_df, lov_data)
        final_df = remove_empty_list_values(final_df)
        logger.info(f"Final merged DataFrame: {len(final_df)} rows")

        output_path = os.path.join(PROCESSED_DIR, "combined.json")
        final_df.to_json(output_path, orient="records", lines=False)
        logger.info(f"Preprocessing complete. Saved to {output_path}")

    finally:
        unload_spacy_pipelines()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Preprocess dataset with optional NER, GPU, and filter.")
    parser.add_argument("--no-ner", action="store_true", help="Disable NER and set ner field to [].")
    parser.add_argument("--gpu", action="store_true", help="Enable GPU for spaCy pipelines if available.")
    parser.add_argument("--no-filter", action="store_true", help="Disable the filter checks for is_*_allowed.")
    args = parser.parse_args()

    main(
        use_ner=args.no_ner,
        use_gpu=args.gpu,
        enable_filter=args.no_filter,
    )
