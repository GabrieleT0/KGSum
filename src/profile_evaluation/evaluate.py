from __future__ import annotations
import argparse
import csv
import statistics
from collections import Counter
from pathlib import Path
from rdflib import Graph, URIRef
from rdflib.namespace import RDF


VOID_DATASET = URIRef("http://rdfs.org/ns/void#Dataset")
VOID_LINKSET = URIRef("http://rdfs.org/ns/void#Linkset")
VOID_DATA_DUMP = URIRef("http://rdfs.org/ns/void#dataDump")
VOID_VOCABULARY = URIRef("http://rdfs.org/ns/void#vocabulary")
VOID_TRIPLES = URIRef("http://rdfs.org/ns/void#triples")
VOID_CLASS_PARTITION = URIRef("http://rdfs.org/ns/void#classPartition")
VOID_PROPERTY_PARTITION = URIRef("http://rdfs.org/ns/void#propertyPartition")
VOID_ENTITIES = URIRef("http://rdfs.org/ns/void#entities")
VOID_CLASSES = URIRef("http://rdfs.org/ns/void#classes")
VOID_PROPERTIES = URIRef("http://rdfs.org/ns/void#properties")
VOID_DISTINCT_SUBJECTS = URIRef("http://rdfs.org/ns/void#distinctSubjects")
VOID_DISTINCT_OBJECTS = URIRef("http://rdfs.org/ns/void#distinctObjects")
VOID_FEATURE = URIRef("http://rdfs.org/ns/void#feature")
DCAT_DISTRIBUTION = URIRef("http://www.w3.org/ns/dcat#distribution")
DCTERMS_SUBJECT = URIRef("http://purl.org/dc/terms/subject")

PROFILE_INFORMATION_FIELDS = {
    "vocabularies": VOID_VOCABULARY,
    "domain": DCTERMS_SUBJECT,
    "triples": VOID_TRIPLES,
    "class_partition": VOID_CLASS_PARTITION,
    "property_partition": VOID_PROPERTY_PARTITION,
    "entities": VOID_ENTITIES,
    "classes": VOID_CLASSES,
    "properties": VOID_PROPERTIES,
    "distinct_subjects": VOID_DISTINCT_SUBJECTS,
    "distinct_objects": VOID_DISTINCT_OBJECTS,
}

DEFAULT_KGSUM_DIR = Path(__file__).parent / "kgsum_profiles"
DEFAULT_LODCLOUD_DIR = Path(__file__).parent / "lodcloud_profiles"
DEFAULT_TIMINGS_PATH = Path(__file__).parent / "kgsum_profile_timings.csv"
TIMINGS_LOG_FIELDS = [
    "source_id",
    "method",
    "target",
    "status",
    "status_code",
    "started_at",
    "ended_at",
    "elapsed_seconds",
    "error",
]

NAMESPACES = {
    "dcat": "http://www.w3.org/ns/dcat#",
    "dcterms": "http://purl.org/dc/terms/",
    "foaf": "http://xmlns.com/foaf/0.1/",
    "rdf": "http://www.w3.org/1999/02/22-rdf-syntax-ns#",
    "rdfs": "http://www.w3.org/2000/01/rdf-schema#",
    "void": "http://rdfs.org/ns/void#",
}


def parse_profile(path: Path) -> Graph:
    graph = Graph()
    graph.parse(path, format="turtle")
    return graph


def find_main_dataset(graph: Graph):
    datasets = list(graph.subjects(RDF.type, VOID_DATASET))
    if not datasets:
        return None

    return max(datasets, key=lambda dataset: len(metadata_fields(graph, dataset)))


def metadata_fields(graph: Graph, dataset) -> set[str]:
    return {
        str(predicate)
        for predicate in graph.predicates(dataset, None)
        if predicate != RDF.type
    }


def profile_fields(path: Path) -> set[str]:
    graph = parse_profile(path)
    dataset = find_main_dataset(graph)
    if dataset is None:
        return set()
    return metadata_fields(graph, dataset)


def recovered_profile_fields(reference_fields: set[str], generated_fields: set[str]) -> set[str]:
    recovered_fields = reference_fields & generated_fields

    if (
        str(DCAT_DISTRIBUTION) in reference_fields
        and str(DCAT_DISTRIBUTION) not in generated_fields
        and str(VOID_DATA_DUMP) in generated_fields
    ):
        recovered_fields.add(str(DCAT_DISTRIBUTION))

    return recovered_fields


def profile_information_status(path: Path) -> tuple[set[str], set[str], bool]:
    graph = parse_profile(path)
    dataset = find_main_dataset(graph)
    fields = metadata_fields(graph, dataset) if dataset is not None else set()
    missing_information = {
        name
        for name, predicate in PROFILE_INFORMATION_FIELDS.items()
        if str(predicate) not in fields
    }

    if not any(graph.subjects(RDF.type, VOID_LINKSET)):
        missing_information.add("linkset")

    has_data_dump = str(VOID_DATA_DUMP) in fields
    has_feature = str(VOID_FEATURE) in fields
    unexpected_feature = has_feature and not has_data_dump

    if has_data_dump and not has_feature:
        missing_information.add("feature")

    return missing_information, {"feature"} if unexpected_feature else set(), has_data_dump


def compact_uri(uri: str) -> str:
    for prefix, namespace in NAMESPACES.items():
        if uri.startswith(namespace):
            return f"{prefix}:{uri[len(namespace):]}"
    return uri


def paired_profiles(kgsum_dir: Path, lodcloud_dir: Path) -> list[tuple[str, Path, Path]]:
    pairs = []
    for kgsum_path in sorted(kgsum_dir.glob("*.ttl")):
        lodcloud_path = lodcloud_dir / kgsum_path.name
        if lodcloud_path.exists():
            pairs.append((kgsum_path.stem, kgsum_path, lodcloud_path))
    return pairs


def read_timing_rows(timings_path: Path) -> list[dict[str, str]]:
    if not timings_path.exists():
        return []

    with timings_path.open(newline="", encoding="utf-8") as f:
        rows = list(csv.reader(f))

    if not rows:
        return []

    header = rows[0]
    data_rows = rows[1:]

    if header[: len(TIMINGS_LOG_FIELDS)] == TIMINGS_LOG_FIELDS:
        return [
            dict(zip(TIMINGS_LOG_FIELDS, row + [""] * (len(TIMINGS_LOG_FIELDS) - len(row))))
            for row in data_rows
        ]

    if (
        len(header) >= len(TIMINGS_LOG_FIELDS)
        and header[:8] == TIMINGS_LOG_FIELDS[:8]
        and header[8].startswith("error")
    ):
        first_source_id = header[8][len("error") :]
        if first_source_id:
            data_rows.insert(0, [first_source_id, *header[9:]])

        return [
            dict(zip(TIMINGS_LOG_FIELDS, row + [""] * (len(TIMINGS_LOG_FIELDS) - len(row))))
            for row in data_rows
        ]

    raise ValueError(
        f"{timings_path} does not start with the expected CSV header: "
        f"{', '.join(TIMINGS_LOG_FIELDS)}"
    )


def timing_statistics(timings_path: Path) -> dict[str, float | int]:
    elapsed_seconds = []
    for row in read_timing_rows(timings_path):
        try:
            elapsed_seconds.append(float(row.get("elapsed_seconds") or ""))
        except ValueError:
            continue

    return {
        "count": len(elapsed_seconds),
        "average_seconds": statistics.mean(elapsed_seconds) if elapsed_seconds else 0.0,
        "median_seconds": statistics.median(elapsed_seconds) if elapsed_seconds else 0.0,
        "stdev_seconds": statistics.stdev(elapsed_seconds) if len(elapsed_seconds) > 1 else 0.0,
    }


def evaluate(kgsum_dir: Path, lodcloud_dir: Path, timings_path: Path) -> tuple[dict, list[dict]]:
    rows = []
    missing_counter = Counter()
    profile_information_missing_counter = Counter()
    profile_information_unexpected_counter = Counter()
    feature_expected_profiles = 0
    kgsum_files = set(kgsum_dir.glob("*.ttl"))
    lodcloud_files = set(lodcloud_dir.glob("*.ttl"))

    for kg_id, kgsum_path, lodcloud_path in paired_profiles(kgsum_dir, lodcloud_dir):
        generated_fields = profile_fields(kgsum_path)
        reference_fields = profile_fields(lodcloud_path)
        (
            missing_profile_information,
            unexpected_profile_information,
            has_data_dump,
        ) = profile_information_status(kgsum_path)

        recovered_fields = recovered_profile_fields(reference_fields, generated_fields)
        missing_fields = reference_fields - recovered_fields

        coverage = (
            len(recovered_fields) / len(reference_fields)
            if reference_fields
            else 1.0
        )
        is_complete = not missing_fields

        missing_counter.update(missing_fields)
        profile_information_missing_counter.update(missing_profile_information)
        profile_information_unexpected_counter.update(unexpected_profile_information)
        if has_data_dump:
            feature_expected_profiles += 1

        rows.append(
            {
                "kg_id": kg_id,
                "reference_fields": reference_fields,
                "generated_fields": generated_fields,
                "recovered_fields": recovered_fields,
                "missing_fields": missing_fields,
                "missing_profile_information": missing_profile_information,
                "unexpected_profile_information": unexpected_profile_information,
                "coverage": coverage,
                "is_complete": is_complete,
            }
        )

    total = len(rows)
    summary = {
        "profiles": total,
        "kgsum_profiles": len(kgsum_files),
        "lodcloud_profiles": len(lodcloud_files),
        "complete_coverage_rate": (
            sum(row["is_complete"] for row in rows) / total if total else 0.0
        ),
        "average_coverage": (
            sum(row["coverage"] for row in rows) / total if total else 0.0
        ),
        "missing_field_counts": missing_counter,
        "profile_information_missing_counts": profile_information_missing_counter,
        "profile_information_unexpected_counts": profile_information_unexpected_counter,
        "feature_expected_profiles": feature_expected_profiles,
        "timing_statistics": timing_statistics(timings_path),
    }

    return summary, rows


def write_details_csv(rows: list[dict], output_path: Path) -> None:
    with output_path.open("w", newline="", encoding="utf-8") as csv_file:
        writer = csv.DictWriter(
            csv_file,
            fieldnames=[
                "kg_id",
                "complete",
                "coverage",
                "reference_fields",
                "generated_fields",
                "missing_fields",
                "missing_profile_information",
                "unexpected_profile_information",
            ],
        )
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    "kg_id": row["kg_id"],
                    "complete": int(row["is_complete"]),
                    "coverage": f"{row['coverage']:.4f}",
                    "reference_fields": "; ".join(
                        sorted(compact_uri(field) for field in row["reference_fields"])
                    ),
                    "generated_fields": "; ".join(
                        sorted(compact_uri(field) for field in row["generated_fields"])
                    ),
                    "missing_fields": "; ".join(
                        sorted(compact_uri(field) for field in row["missing_fields"])
                    ),
                    "missing_profile_information": "; ".join(
                        sorted(row["missing_profile_information"])
                    ),
                    "unexpected_profile_information": "; ".join(
                        sorted(row["unexpected_profile_information"])
                    ),
                }
            )


def write_missing_fields_chart(missing_field_counts: Counter, output_path: Path) -> None:
    if not missing_field_counts:
        return

    fields_and_counts = [
        (compact_uri(field), count)
        for field, count in missing_field_counts.most_common()
    ]
    max_count = max(count for _, count in fields_and_counts)
    row_height = 34
    label_width = 210
    chart_width = 620
    value_width = 60
    top_margin = 58
    bottom_margin = 42
    width = label_width + chart_width + value_width + 44
    height = top_margin + len(fields_and_counts) * row_height + bottom_margin

    def escape_xml(value: str) -> str:
        return (
            value.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;")
        )

    lines = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="#ffffff"/>',
        '<text x="24" y="32" font-family="Arial, sans-serif" font-size="20" font-weight="700" fill="#1f2933">Missing-field analysis</text>',]

    for index, (field, count) in enumerate(fields_and_counts):
        y = top_margin + index * row_height
        bar_width = (count / max_count) * chart_width if max_count else 0
        lines.extend(
            [
                f'<text x="24" y="{y + 20}" font-family="Arial, sans-serif" font-size="14" fill="#323f4b">{escape_xml(field)}</text>',
                f'<rect x="{label_width}" y="{y + 4}" width="{chart_width}" height="22" fill="#eef2f7"/>',
                f'<rect x="{label_width}" y="{y + 4}" width="{bar_width:.2f}" height="22" fill="#4c78a8"/>',
                f'<text x="{label_width + bar_width + 8:.2f}" y="{y + 20}" font-family="Arial, sans-serif" font-size="14" fill="#1f2933">{count}</text>',
            ]
        )

    lines.append("</svg>")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(lines), encoding="utf-8")


def print_results(summary: dict, rows: list[dict]) -> None:
    print(f"Profiles evaluated: {summary['profiles']}")
    print(f"KGSum profiles: {summary['kgsum_profiles']}")
    print(f"LOD Cloud profiles: {summary['lodcloud_profiles']}")
    print(f"Complete Coverage Rate (CCR): {summary['complete_coverage_rate']:.4f}")
    print(f"Average Coverage: {summary['average_coverage']:.4f}")

    incomplete_rows = [row for row in rows if not row["is_complete"]]
    print(f"Incomplete profiles: {len(incomplete_rows)}")

    if summary["missing_field_counts"]:
        print("\nMissing-field analysis:")
        for field, count in summary["missing_field_counts"].most_common():
            print(f"- {compact_uri(field)}: {count}")

    if summary["profile_information_missing_counts"]:
        print("\nKGSum profile information missing:")
        for field, count in summary["profile_information_missing_counts"].most_common():
            print(f"- {field}: {count}")
        print(f"Feature expected profiles with void:dataDump: {summary['feature_expected_profiles']}")

    if summary["profile_information_unexpected_counts"]:
        print("\nKGSum profile information unexpectedly present:")
        for field, count in summary["profile_information_unexpected_counts"].most_common():
            print(f"- {field} without void:dataDump: {count}")

    timing_stats = summary["timing_statistics"]
    print("\nKGSum profile computation time:")
    print(f"Timing entries: {timing_stats['count']}")
    print(f"Average seconds: {timing_stats['average_seconds']:.4f}")
    print(f"Median seconds: {timing_stats['median_seconds']:.4f}")
    print(f"Standard deviation seconds: {timing_stats['stdev_seconds']:.4f}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Evaluate KGSum metadata coverage against LOD Cloud VoID profiles."
    )
    parser.add_argument("--kgsum-dir", type=Path, default=DEFAULT_KGSUM_DIR)
    parser.add_argument("--lodcloud-dir", type=Path, default=DEFAULT_LODCLOUD_DIR)
    parser.add_argument("--timings", type=Path, default=DEFAULT_TIMINGS_PATH)
    parser.add_argument(
        "--details-csv",
        type=Path,
        help="Optional path where per-profile results are written as CSV.",
    )
    parser.add_argument(
        "--missing-fields-chart",
        type=Path,
        help="Optional path where the missing-field analysis is written as a horizontal bar chart.",
    )
    args = parser.parse_args()

    summary, rows = evaluate(args.kgsum_dir, args.lodcloud_dir, args.timings)
    print_results(summary, rows)

    if args.details_csv:
        write_details_csv(rows, args.details_csv)
        print(f"\nDetailed results written to: {args.details_csv}")

    if args.missing_fields_chart:
        write_missing_fields_chart(
            summary["missing_field_counts"],
            args.missing_fields_chart,
        )
        print(f"\nMissing-field chart written to: {args.missing_fields_chart}")


if __name__ == "__main__":
    main()
