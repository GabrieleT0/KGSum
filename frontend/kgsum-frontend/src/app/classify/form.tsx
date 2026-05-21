"use client";
import React, {useMemo, useRef, useState} from "react";
import {Tabs, TabsContent, TabsList, TabsTrigger,} from "@/components/ui/tabs";
import {Label} from "@/components/ui/label";
import {Input} from "@/components/ui/input";
import {Card, CardContent} from "@/components/ui/card";
import {Separator} from "@/components/ui/separator";
import {Checkbox} from "@/components/ui/checkbox";
import {Button} from "@/components/ui/button";
import {Badge} from "@/components/ui/badge";
import {ScrollArea} from "@/components/ui/scroll-area";
import {Braces, Database, Download, ExternalLink, FileCode, Hash, Network, Tags} from "lucide-react";
import Link from "next/link";
const UPLOAD = true
const BASE_PATH = process.env.NEXT_PUBLIC_BASE_PATH || "";

type JsonLdNode = Record<string, unknown>;

type DownloadFormat = {
    format: string;
    label: string;
    extension: string;
    mimeType: string;
};

const DOWNLOAD_FORMATS: DownloadFormat[] = [
    {format: "jsonld", label: "JSON-LD", extension: "jsonld", mimeType: "application/ld+json"},
    {format: "rdf", label: "RDF/XML", extension: "rdf", mimeType: "application/rdf+xml"},
    {format: "ttl", label: "TTL", extension: "ttl", mimeType: "text/turtle"},
    {format: "nt", label: "N-Triples", extension: "nt", mimeType: "application/n-triples"},
];

const FIELD_KEYS = {
    title: ["dcterms:title", "http://purl.org/dc/terms/title", "title"],
    description: ["dcterms:description", "http://purl.org/dc/terms/description", "description"],
    creator: ["dcterms:creator", "http://purl.org/dc/terms/creator", "creator"],
    contributor: ["dcterms:contributor", "http://purl.org/dc/terms/contributor", "contributor"],
    publisher: ["dcterms:publisher", "http://purl.org/dc/terms/publisher", "publisher"],
    source: ["dcterms:source", "http://purl.org/dc/terms/source", "source"],
    identifier: ["dcterms:identifier", "http://purl.org/dc/terms/identifier", "identifier"],
    language: ["dcterms:language", "http://purl.org/dc/terms/language", "language"],
    license: ["dcterms:license", "http://purl.org/dc/terms/license", "license"],
    homepage: ["foaf:homepage", "http://xmlns.com/foaf/0.1/homepage", "homepage"],
    date: ["dcterms:date", "http://purl.org/dc/terms/date", "date"],
    created: ["dcterms:created", "http://purl.org/dc/terms/created", "created"],
    issued: ["dcterms:issued", "http://purl.org/dc/terms/issued", "issued"],
    modified: ["dcterms:modified", "http://purl.org/dc/terms/modified", "modified"],
    subject: ["dcterms:subject", "http://purl.org/dc/terms/subject", "subject"],
    theme: ["dcat:theme", "http://www.w3.org/ns/dcat#theme", "theme"],
    triples: ["void:triples", "http://rdfs.org/ns/void#triples", "triples"],
    entities: ["void:entities", "http://rdfs.org/ns/void#entities", "entities"],
    classes: ["void:classes", "http://rdfs.org/ns/void#classes", "classes"],
    properties: ["void:properties", "http://rdfs.org/ns/void#properties", "properties"],
    sparql: ["void:sparqlEndpoint", "http://rdfs.org/ns/void#sparqlEndpoint", "sparqlEndpoint"],
    dataDump: ["void:dataDump", "http://rdfs.org/ns/void#dataDump", "dataDump"],
    vocabulary: ["void:vocabulary", "http://rdfs.org/ns/void#vocabulary", "vocabulary"],
    feature: ["void:feature", "http://rdfs.org/ns/void#feature", "feature"],
    exampleResource: ["void:exampleResource", "http://rdfs.org/ns/void#exampleResource", "exampleResource"],
    uriSpace: ["void:uriSpace", "http://rdfs.org/ns/void#uriSpace", "uriSpace"],
    uriRegexPattern: ["void:uriRegexPattern", "http://rdfs.org/ns/void#uriRegexPattern", "uriRegexPattern"],
};

const GRAPH_KEYS = {
    id: ["@id", "id"],
    classPartition: ["void:classPartition", "http://rdfs.org/ns/void#classPartition", "classPartition"],
    propertyPartition: ["void:propertyPartition", "http://rdfs.org/ns/void#propertyPartition", "propertyPartition"],
    class: ["void:class", "http://rdfs.org/ns/void#class", "class"],
    property: ["void:property", "http://rdfs.org/ns/void#property", "property"],
    linkPredicate: ["void:linkPredicate", "http://rdfs.org/ns/void#linkPredicate", "linkPredicate"],
    objectsTarget: ["void:objectsTarget", "http://rdfs.org/ns/void#objectsTarget", "objectsTarget"],
    subjectsTarget: ["void:subjectsTarget", "http://rdfs.org/ns/void#subjectsTarget", "subjectsTarget"],
    target: ["void:target", "http://rdfs.org/ns/void#target", "target"],
};

type PartitionItem = {
    label: string;
    count: number;
};

type LinkedDataset = {
    name: string;
    url?: string;
    triples: number;
};

function FileIcon(props: React.SVGProps<SVGSVGElement>) {
    return (
        <svg
            {...props}
            xmlns="http://www.w3.org/2000/svg"
            width="24"
            height="24"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
        >
            <path d="M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7Z"/>
            <path d="M14 2v4a2 2 0 0 0 2 2h4"/>
        </svg>
    );
}

function CopyIcon(props: React.SVGProps<SVGSVGElement>) {
    return (
        <svg
            {...props}
            xmlns="http://www.w3.org/2000/svg"
            width="24"
            height="24"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
        >
            <rect width="14" height="14" x="8" y="8" rx="2" ry="2"/>
            <path d="M4 16c-1.1 0-2-.9-2-2V4c0-1.1.9-2 2-2h10c1.1 0 2 .9 2 2"/>
        </svg>
    );
}

function CheckIcon(props: React.SVGProps<SVGSVGElement>) {
    return (
        <svg
            {...props}
            xmlns="http://www.w3.org/2000/svg"
            width="24"
            height="24"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
        >
            <path d="M20 6 9 17l-5-5"/>
        </svg>
    );
}

function AlertTriangleIcon(props: React.SVGProps<SVGSVGElement>) {
    return (
        <svg
            {...props}
            xmlns="http://www.w3.org/2000/svg"
            width="24"
            height="24"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
        >
            <path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3Z"/>
            <path d="M12 9v4"/>
            <path d="m12 17 .01 0"/>
        </svg>
    );
}

function asArray(value: unknown): unknown[] {
    if (value === undefined || value === null) return [];
    return Array.isArray(value) ? value : [value];
}

function valueToText(value: unknown): string | undefined {
    if (value === undefined || value === null) return undefined;
    if (typeof value === "string" || typeof value === "number" || typeof value === "boolean") {
        return String(value);
    }
    if (typeof value === "object") {
        const objectValue = value as JsonLdNode;
        const candidate = objectValue["@value"] ?? objectValue["@id"] ?? objectValue["id"] ?? objectValue["value"];
        if (candidate !== undefined) return valueToText(candidate);
    }
    return undefined;
}

function uniqueValues(values: string[]): string[] {
    return Array.from(new Set(values.map((value) => value.trim()).filter(Boolean)));
}

function normalizePredicate(value: string): string {
    if (/^https?:\/\//i.test(value)) {
        return value.split(/[\/#]/).pop() || value;
    }
    return value.includes(":") ? value.split(":").pop() || value : value.split(/[\/#]/).pop() || value;
}

function isDatasetNode(node: JsonLdNode): boolean {
    return asArray(node["@type"]).some((type) => {
        const typeText = valueToText(type) || "";
        return typeText === "void:Dataset" || typeText.endsWith("#Dataset") || typeText.endsWith("/Dataset");
    });
}

function isLinksetNode(node: JsonLdNode): boolean {
    return asArray(node["@type"]).some((type) => {
        const typeText = valueToText(type) || "";
        return typeText === "void:Linkset" || typeText.endsWith("#Linkset") || typeText.endsWith("/Linkset");
    });
}

function jsonLdNodes(data: unknown): JsonLdNode[] {
    if (!data || typeof data !== "object") return [];
    if (Array.isArray(data)) return data.filter((item): item is JsonLdNode => !!item && typeof item === "object" && !Array.isArray(item));

    const objectData = data as JsonLdNode;
    const graph = objectData["@graph"];
    if (Array.isArray(graph)) {
        return graph.filter((item): item is JsonLdNode => !!item && typeof item === "object" && !Array.isArray(item));
    }
    return [objectData];
}

function getNodeId(node: JsonLdNode | undefined): string | undefined {
    return node ? valueToText(node["@id"]) || valueToText(node["id"]) : undefined;
}

function nodeMap(data: unknown): Map<string, JsonLdNode> {
    return new Map(jsonLdNodes(data).map((node) => [getNodeId(node), node]).filter((entry): entry is [string, JsonLdNode] => !!entry[0]));
}

function hasAnyValue(node: JsonLdNode, keys: string[]): boolean {
    return getValues(node, keys).length > 0;
}

function hasAnyKey(node: JsonLdNode, keys: string[]): boolean {
    return Object.keys(node).some((key) => {
        const normalizedKey = normalizePredicate(key);
        return keys.some((candidate) => key === candidate || normalizedKey === normalizePredicate(candidate));
    });
}

function profileNodeScore(node: JsonLdNode): number {
    let score = isDatasetNode(node) ? 10 : 0;

    for (const keys of [
        FIELD_KEYS.triples,
        FIELD_KEYS.entities,
        FIELD_KEYS.classes,
        FIELD_KEYS.properties,
        FIELD_KEYS.sparql,
        FIELD_KEYS.title,
        FIELD_KEYS.description,
        FIELD_KEYS.identifier,
    ]) {
        if (hasAnyValue(node, keys)) score += 4;
    }

    for (const keys of [
        ["void:classPartition", "http://rdfs.org/ns/void#classPartition", "classPartition"],
        ["void:propertyPartition", "http://rdfs.org/ns/void#propertyPartition", "propertyPartition"],
        FIELD_KEYS.vocabulary,
        FIELD_KEYS.dataDump,
    ]) {
        if (hasAnyKey(node, keys)) score += 2;
    }

    return score;
}

function profileNode(data: unknown): JsonLdNode | undefined {
    const nodes = jsonLdNodes(data);
    return nodes
        .map((node, index) => ({node, index, score: profileNodeScore(node)}))
        .sort((a, b) => b.score - a.score || a.index - b.index)[0]?.node;
}

function getValues(node: JsonLdNode | undefined, keys: string[]): string[] {
    if (!node) return [];

    const values: string[] = [];
    for (const [key, rawValue] of Object.entries(node)) {
        const normalizedKey = normalizePredicate(key);
        const matches = keys.some((candidate) => key === candidate || normalizedKey === normalizePredicate(candidate));
        if (!matches) continue;

        for (const item of asArray(rawValue)) {
            const text = valueToText(item);
            if (text) values.push(text);
        }
    }

    return uniqueValues(values);
}

function getRawValues(node: JsonLdNode | undefined, keys: string[]): unknown[] {
    if (!node) return [];

    const values: unknown[] = [];
    for (const [key, rawValue] of Object.entries(node)) {
        const normalizedKey = normalizePredicate(key);
        const matches = keys.some((candidate) => key === candidate || normalizedKey === normalizePredicate(candidate));
        if (matches) values.push(...asArray(rawValue));
    }

    return values;
}

function referencedNodes(data: unknown, node: JsonLdNode | undefined, keys: string[]): JsonLdNode[] {
    const nodesById = nodeMap(data);
    return getRawValues(node, keys)
        .map((value) => {
            if (value && typeof value === "object" && !Array.isArray(value)) {
                const objectValue = value as JsonLdNode;
                const referenceId = getNodeId(objectValue);
                return referenceId ? nodesById.get(referenceId) || objectValue : objectValue;
            }
            const text = valueToText(value);
            return text ? nodesById.get(text) : undefined;
        })
        .filter((value): value is JsonLdNode => !!value);
}

function parseCount(value: string | undefined): number {
    const numberValue = Number(value);
    return Number.isFinite(numberValue) ? numberValue : 0;
}

function topPartitions(data: unknown, node: JsonLdNode | undefined, partitionKeys: string[], valueKeys: string[], countKeys: string[]): PartitionItem[] {
    return referencedNodes(data, node, partitionKeys)
        .map((partition) => ({
            label: getValues(partition, valueKeys)[0] || "Unknown",
            count: parseCount(getValues(partition, countKeys)[0]),
        }))
        .filter((item) => item.label !== "Unknown" || item.count > 0)
        .sort((a, b) => b.count - a.count)
        .slice(0, 5);
}

function linkedDatasets(data: unknown, node: JsonLdNode | undefined): LinkedDataset[] {
    const profileId = getNodeId(node);
    if (!profileId) return [];

    return jsonLdNodes(data)
        .filter(isLinksetNode)
        .filter((linkset) => {
            const subjectTargets = getValues(linkset, GRAPH_KEYS.subjectsTarget);
            return !subjectTargets.length || subjectTargets.includes(profileId);
        })
        .map((linkset) => {
            const objectTarget = getValues(linkset, GRAPH_KEYS.objectsTarget)[0];
            const targets = getValues(linkset, GRAPH_KEYS.target).filter((target) => target !== profileId);
            const target = objectTarget || targets[0] || "Linked dataset";
            return {
                name: datasetName(target),
                url: isLikelyUrl(target) ? target : undefined,
                triples: parseCount(getValues(linkset, FIELD_KEYS.triples)[0]),
            };
        })
        .filter((dataset) => dataset.name !== profileId)
        .sort((a, b) => b.triples - a.triples || a.name.localeCompare(b.name));
}

function firstValue(node: JsonLdNode | undefined, keys: string[], fallback = "Untitled KG profile"): string {
    return getValues(node, keys)[0] || fallback;
}

function compactUri(value: string): string {
    if (value.length <= 54) return value;
    return `${value.slice(0, 28)}...${value.slice(-20)}`;
}

function formatCount(value: string | undefined): string {
    if (!value) return "-";
    const numberValue = Number(value);
    return Number.isFinite(numberValue) ? numberValue.toLocaleString() : value;
}

function isLikelyUrl(value: string): boolean {
    return /^https?:\/\//i.test(value);
}

function datasetName(value: string): string {
    if (!isLikelyUrl(value)) return value;
    try {
        return new URL(value).hostname.replace(/^www\./, "");
    } catch {
        return value;
    }
}

function FieldList({label, values}: { label: string; values: string[] }) {
    const [isExpanded, setIsExpanded] = useState(false);
    const visibleValues = isExpanded ? values : values.slice(0, 4);
    const hiddenCount = values.length - visibleValues.length;

    if (!values.length) return null;

    return (
        <div className="min-w-0 space-y-1.5">
            <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">{label}</p>
            <div className="space-y-1.5">
                {visibleValues.map((value) => (
                    <div key={`${label}-${value}`} className="min-w-0 overflow-hidden rounded-md border bg-muted/30 px-3 py-2 text-sm text-foreground">
                        {isLikelyUrl(value) ? (
                            <a href={value} target="_blank" rel="noreferrer" className="flex min-w-0 max-w-full items-center gap-1 hover:underline">
                                <span className="min-w-0 truncate">{compactUri(value)}</span>
                                <ExternalLink className="h-3.5 w-3.5 shrink-0"/>
                            </a>
                        ) : <span className="block truncate">{value}</span>}
                    </div>
                ))}
                {values.length > 4 && (
                    <button
                        type="button"
                        onClick={() => setIsExpanded((current) => !current)}
                        className="text-xs font-medium text-muted-foreground hover:text-foreground hover:underline"
                    >
                        {isExpanded ? "Show less" : `+${hiddenCount} more`}
                    </button>
                )}
            </div>
        </div>
    );
}

function RankedList({label, items, valueLabel}: { label: string; items: PartitionItem[]; valueLabel: string }) {
    if (!items.length) return null;

    return (
        <div className="space-y-2">
            <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">{label}</p>
            <div className="space-y-2">
                {items.map((item) => (
                    <div key={`${label}-${item.label}`} className="flex min-w-0 items-center justify-between gap-3 rounded-md border bg-muted/30 px-3 py-2 text-sm">
                        <span className="min-w-0 truncate text-foreground" title={item.label}>{compactUri(item.label)}</span>
                        <span className="shrink-0 text-muted-foreground">{formatCount(String(item.count))} {valueLabel}</span>
                    </div>
                ))}
            </div>
        </div>
    );
}

function LinkedDatasetList({items}: { items: LinkedDataset[] }) {
    const [isExpanded, setIsExpanded] = useState(false);
    const visibleItems = isExpanded ? items : items.slice(0, 8);
    const hiddenCount = items.length - visibleItems.length;

    if (!items.length) return null;

    return (
        <div className="space-y-2">
            <div className="flex items-center gap-2 text-sm font-medium text-foreground">
                <Network className="h-4 w-4"/>
                <span>Linked datasets</span>
            </div>
            <div className="grid gap-2 md:grid-cols-2">
                {visibleItems.map((item) => (
                    <div key={`${item.name}-${item.url || ""}`} className="flex min-w-0 items-center justify-between gap-3 rounded-md border bg-muted/30 px-3 py-2 text-sm">
                        {item.url ? (
                            <a href={item.url} target="_blank" rel="noreferrer" className="flex min-w-0 items-center gap-1 text-foreground hover:underline">
                                <span className="min-w-0 truncate" title={item.url}>{item.name}</span>
                                <ExternalLink className="h-3.5 w-3.5 shrink-0"/>
                            </a>
                        ) : <span className="min-w-0 truncate text-foreground" title={item.name}>{item.name}</span>}
                        <span className="shrink-0 text-muted-foreground">{formatCount(String(item.triples))} triples</span>
                    </div>
                ))}
            </div>
            {items.length > 8 && (
                <button
                    type="button"
                    onClick={() => setIsExpanded((current) => !current)}
                    className="text-xs font-medium text-muted-foreground hover:text-foreground hover:underline"
                >
                    {isExpanded ? "Show less" : `+${hiddenCount} more linked datasets`}
                </button>
            )}
        </div>
    );
}

function ChipList({label, icon, values}: { label: string; icon: React.ReactNode; values: string[] }) {
    const [isExpanded, setIsExpanded] = useState(false);
    const visibleValues = isExpanded ? values : values.slice(0, 14);
    const hiddenCount = values.length - visibleValues.length;

    if (!values.length) return null;

    return (
        <div className="space-y-2">
            <div className="flex items-center gap-2 text-sm font-medium text-foreground">
                {icon}
                <span>{label}</span>
            </div>
            <div className="flex flex-wrap gap-2">
                {visibleValues.map((value) => (
                    <Badge key={`${label}-${value}`} variant="secondary" className="max-w-full justify-start rounded-md">
                        {isLikelyUrl(value) ? (
                            <a href={value} target="_blank" rel="noreferrer" className="flex min-w-0 max-w-full items-center gap-1 hover:underline">
                                <span className="min-w-0 truncate" title={value}>{compactUri(value)}</span>
                                <ExternalLink className="h-3 w-3 shrink-0"/>
                            </a>
                        ) : (
                            <span className="min-w-0 truncate" title={value}>{compactUri(value)}</span>
                        )}
                    </Badge>
                ))}
                {values.length > 14 && (
                    <button type="button" onClick={() => setIsExpanded((current) => !current)}>
                        <Badge variant="outline" className="cursor-pointer rounded-md hover:bg-muted">
                            {isExpanded ? "Show less" : `+${hiddenCount}`}
                        </Badge>
                    </button>
                )}
            </div>
        </div>
    );
}

// Infinite Progress Component with proper animation and dark mode support
function InfiniteProgress({isVisible}: { isVisible: boolean }) {
    if (!isVisible) return null;

    return (
        <div className="w-full mt-4">
            <div className="flex items-center space-x-3 mb-2">
                <div className="flex-1 relative h-2 bg-muted rounded-full overflow-hidden">
                    <div className="absolute inset-0 h-full bg-primary rounded-full animate-progress-infinite"></div>
                </div>
                <span className="text-sm text-muted-foreground font-medium">Computing...</span>
            </div>
            <style jsx>{`
        @keyframes progress-infinite {
          0% {
            transform: translateX(-100%);
            width: 30%;
          }
          50% {
            width: 50%;
          }
          100% {
            transform: translateX(400%);
            width: 30%;
          }
        }
        .animate-progress-infinite {
          animation: progress-infinite 2s ease-in-out infinite;
        }
      `}</style>
        </div>
    );
}

// File size formatter utility
function formatFileSize(bytes: number): string {
    const sizes = ['Bytes', 'KB', 'MB', 'GB'];
    if (bytes === 0) return '0 Bytes';
    const i = Math.floor(Math.log(bytes) / Math.log(1024));
    return Math.round(bytes / Math.pow(1024, i) * 100) / 100 + ' ' + sizes[i];
}

function ProfileSummary({
                            data,
                            displayResponse,
                            onCopy,
                            isCopied,
                            onDownload,
                            isDownloading,
                            currentJobId,
                        }: {
    data: unknown | undefined;
    displayResponse: string;
    onCopy: () => void;
    isCopied: boolean;
    onDownload: (format: DownloadFormat) => void;
    isDownloading: string | null;
    currentJobId: string | null;
}) {
    const node = profileNode(data);
    const title = firstValue(node, FIELD_KEYS.title);
    const description = firstValue(node, FIELD_KEYS.description, "No description available for this profile.");
    const endpoint = getValues(node, FIELD_KEYS.sparql);
    const downloads = getValues(node, FIELD_KEYS.dataDump);
    const vocabularies = getValues(node, FIELD_KEYS.vocabulary);
    const features = getValues(node, FIELD_KEYS.feature);
    const examples = getValues(node, FIELD_KEYS.exampleResource);
    const subjects = getValues(node, FIELD_KEYS.subject);
    const themes = getValues(node, FIELD_KEYS.theme);
    const linkedDatasetItems = linkedDatasets(data, node);
    const topClasses = topPartitions(data, node, GRAPH_KEYS.classPartition, GRAPH_KEYS.class, FIELD_KEYS.entities);
    const topProperties = topPartitions(data, node, GRAPH_KEYS.propertyPartition, GRAPH_KEYS.property, FIELD_KEYS.triples);
    const stats = [
        {label: "Triples", value: formatCount(getValues(node, FIELD_KEYS.triples)[0]), icon: <Database className="h-4 w-4"/>},
        {label: "Entities", value: formatCount(getValues(node, FIELD_KEYS.entities)[0]), icon: <Network className="h-4 w-4"/>},
        {label: "Classes", value: formatCount(getValues(node, FIELD_KEYS.classes)[0]), icon: <Tags className="h-4 w-4"/>},
        {label: "Properties", value: formatCount(getValues(node, FIELD_KEYS.properties)[0]), icon: <Hash className="h-4 w-4"/>},
    ];

    if (!data) {
        return (
            <div className="flex h-[35rem] flex-col items-center justify-center rounded-lg border border-dashed bg-muted/20 p-8 text-center">
                <FileCode className="mb-4 h-12 w-12 text-muted-foreground"/>
                <p className="text-sm font-medium text-foreground">Your KG profile will appear here</p>
                <p className="mt-2 max-w-md text-sm text-muted-foreground">
                    Run a classification to see all the statistics about your KG.
                </p>
                <InfiniteProgress isVisible={false}/>
            </div>
        );
    }

    return (
        <div className="space-y-4">
            <div className="rounded-lg border bg-muted/20 p-5">
                <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
                    <div className="min-w-0 space-y-2">
                        <Badge variant="outline" className="rounded-md">KG Profile</Badge>
                        <h3 className="break-words text-2xl font-semibold leading-tight text-foreground">{title}</h3>
                        <p className="line-clamp-4 text-sm leading-6 text-muted-foreground">{description}</p>
                    </div>
                    <Button
                        type="button"
                        variant="outline"
                        size="sm"
                        onClick={onCopy}
                        className="h-9 shrink-0 gap-2"
                    >
                        {isCopied ? <CheckIcon className="h-4 w-4 text-green-600 dark:text-green-400"/> : <CopyIcon className="h-4 w-4"/>}
                        {isCopied ? "Copied" : "Copy JSON-LD"}
                    </Button>
                </div>
            </div>

            <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
                {stats.map((stat) => (
                    <div key={stat.label} className="rounded-lg border bg-background p-3">
                        <div className="mb-2 flex items-center gap-2 text-muted-foreground">
                            {stat.icon}
                            <span className="text-xs font-medium uppercase tracking-wide">{stat.label}</span>
                        </div>
                        <p className="truncate text-xl font-semibold text-foreground">{stat.value}</p>
                    </div>
                ))}
            </div>

            <ScrollArea className="h-[22rem] rounded-lg border">
                <div className="space-y-5 p-4">
                    <div className="grid min-w-0 gap-4 md:grid-cols-2">
                        <FieldList label="Identifier" values={getValues(node, FIELD_KEYS.identifier)}/>
                        <FieldList label="Language" values={getValues(node, FIELD_KEYS.language)}/>
                        <FieldList label="Creator" values={getValues(node, FIELD_KEYS.creator)}/>
                        <FieldList label="Contributor" values={getValues(node, FIELD_KEYS.contributor)}/>
                        <FieldList label="Publisher" values={getValues(node, FIELD_KEYS.publisher)}/>
                        <FieldList label="Homepage" values={getValues(node, FIELD_KEYS.homepage)}/>
                        <FieldList label="License" values={getValues(node, FIELD_KEYS.license)}/>
                        <FieldList label="Source" values={getValues(node, FIELD_KEYS.source)}/>
                        <FieldList label="Issued" values={getValues(node, FIELD_KEYS.issued)}/>
                        <FieldList label="Created" values={getValues(node, FIELD_KEYS.created)}/>
                        <FieldList label="Modified" values={getValues(node, FIELD_KEYS.modified)}/>
                        <FieldList label="Date" values={getValues(node, FIELD_KEYS.date)}/>
                        <FieldList label="URI regex pattern" values={getValues(node, FIELD_KEYS.uriRegexPattern)}/>
                        <FieldList label="URI space" values={getValues(node, FIELD_KEYS.uriSpace)}/>
                        <FieldList label="SPARQL endpoint" values={endpoint}/>
                    </div>

                    <Separator/>

                    <ChipList label="Domain (inferred)" icon={<Hash className="h-4 w-4"/>} values={themes}/>
                    <ChipList label="Vocabularies" icon={<Tags className="h-4 w-4"/>} values={vocabularies}/>
                    <ChipList label="Serialization features" icon={<FileCode className="h-4 w-4"/>} values={features}/>
                    <ChipList label="Subjects" icon={<Hash className="h-4 w-4"/>} values={subjects}/>

                    <Separator/>

                    <LinkedDatasetList items={linkedDatasetItems}/>

                    <div className="grid min-w-0 gap-4 md:grid-cols-2">
                        <RankedList label="Top classes" items={topClasses} valueLabel="entities"/>
                        <RankedList label="Top properties" items={topProperties} valueLabel="triples"/>
                    </div>

                    <Separator/>

                    <div className="grid min-w-0 gap-4 md:grid-cols-2">
                        <FieldList label="Data dumps" values={downloads}/>
                        <FieldList label="Example resources" values={examples}/>
                    </div>

                    <details className="rounded-lg border bg-muted/20 p-3">
                        <summary className="flex cursor-pointer items-center gap-2 text-sm font-medium text-foreground">
                            <Braces className="h-4 w-4"/>
                            Raw JSON-LD
                        </summary>
                        <pre className="mt-3 max-h-80 overflow-auto whitespace-pre-wrap break-words rounded-md bg-background p-3 text-xs text-muted-foreground">
                            {displayResponse}
                        </pre>
                    </details>
                </div>
            </ScrollArea>

            <div className="rounded-lg border p-4">
                <div className="mb-3 flex items-center gap-2 text-sm font-medium">
                    <Download className="h-4 w-4"/>
                    <span>Download profile</span>
                </div>
                <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
                    {DOWNLOAD_FORMATS.map((format) => (
                        <Button
                            key={format.format}
                            type="button"
                            variant="outline"
                            size="sm"
                            disabled={!currentJobId || isDownloading !== null}
                            onClick={() => onDownload(format)}
                            className="h-9"
                        >
                            {isDownloading === format.format ? "..." : format.label}
                        </Button>
                    ))}
                </div>
            </div>
        </div>
    );
}

export const Form = () => {
    const [tab, setTab] = useState<"SPARQL" | "DUMP">("SPARQL");
    const [sparqlUrl, setSparqlUrl] = useState("");
    const [hasFile, setHasFile] = useState(false);
    const [selectedFile, setSelectedFile] = useState<File | null>(null);
    const [privacyConsent, setPrivacyConsent] = useState(false);
    const [isCopied, setIsCopied] = useState(false);
    const [fileSizeWarning, setFileSizeWarning] = useState("");
    const [message, setMessage] = useState("");
    const [resultData, setResultData] = useState<unknown | undefined>(undefined);
    const [completedJobId, setCompletedJobId] = useState<string | null>(null);
    const [isDownloading, setIsDownloading] = useState<string | null>(null);
    const [isPending, setIsPending] = useState(false);
    const fileInputRef = useRef<HTMLInputElement>(null);

    // Constants
    const MAX_FILE_SIZE = 524288000; // 500MB in bytes
    const LARGE_FILE_THRESHOLD = 104857600; // 100MB in bytes

    // Calculate if form is valid based on current tab and inputs
    const isFormValid = useMemo(() => {
        if (!privacyConsent) return false;

        if (tab === "SPARQL") {
            return sparqlUrl.trim() !== "";
        }

        if (tab === "DUMP") {
            return hasFile && selectedFile && selectedFile.size <= MAX_FILE_SIZE;
        }

        return false;
    }, [tab, sparqlUrl, hasFile, selectedFile, privacyConsent]);

    const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
        const file = e.target.files?.[0];

        if (file) {
            // Reset warnings
            setFileSizeWarning("");

            // Check file size (500MB limit)
            if (file.size > MAX_FILE_SIZE) {
                const sizeMB = Math.round(file.size / (1024 * 1024));
                setFileSizeWarning(`Error: The file (${sizeMB}MB) is over the 500MB size threshold. Upload a smaller file.`);
                e.target.value = ''; // Clear the input
                setHasFile(false);
                setSelectedFile(null);
                return;
            }

            // Warn for large files
            if (file.size > LARGE_FILE_THRESHOLD) {
                const sizeMB = Math.round(file.size / (1024 * 1024));
                setFileSizeWarning(`Large file (${sizeMB}MB) - the processing could take a few minutes.`);
            }

            // Validate file extension
            const allowedExtensions = ['.rdf', '.ttl', '.nq', '.nt', '.xml', '.json'];
            const fileName = file.name.toLowerCase();
            const fileExtension = '.' + fileName.split('.').pop();

            if (!allowedExtensions.includes(fileExtension)) {
                setFileSizeWarning(`Error: File format "${fileExtension}" not support. Accepted format: ${allowedExtensions.join(', ')}`);
                e.target.value = ''; // Clear the input
                setHasFile(false);
                setSelectedFile(null);
                return;
            }

            setHasFile(true);
            setSelectedFile(file);
        } else {
            setHasFile(false);
            setSelectedFile(null);
            setFileSizeWarning("");
        }
    };

    // Format JSON-LD response for display
    const formatResponse = (response: unknown | undefined): string => {
        if (!response) return "";

        try {
            return JSON.stringify(response, null, 2);
        } catch {
            return String(response);
        }
    };

    const displayResponse = resultData ? formatResponse(resultData) : "";

    const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

    const pollProfileJob = async (jobId: string): Promise<unknown> => {
        while (true) {
            await sleep(5000);
            const response = await fetch(`${BASE_PATH}/api/profile/jobs/${jobId}?format=jsonld`, {
                method: "GET",
                headers: {"Accept": "application/json"},
            });

            if (!response.ok) {
                throw new Error(`Job status request failed (${response.status})`);
            }

            const payload = await response.json();
            if (payload.status === "completed") {
                return payload.result;
            }
            if (payload.status === "failed") {
                throw new Error(payload.error || "Profile generation failed");
            }
        }
    };

    const handleSubmit = async (event: React.FormEvent<HTMLFormElement>) => {
        event.preventDefault();
        if (!isFormValid || isPending) return;

        setMessage("");
        setResultData(undefined);
        setCompletedJobId(null);
        setIsPending(true);

        const saveProfile = new FormData(event.currentTarget).get("saveProfile");

        try {
            if (tab === "SPARQL") {
                const response = await fetch(`${BASE_PATH}/api/profile/sparql/jobs`, {
                    method: "POST",
                    headers: {
                        "Content-Type": "application/json",
                        "Accept": "application/json",
                    },
                    body: JSON.stringify({endpoint: sparqlUrl, store: !!saveProfile}),
                });

                const payload = await response.json();
                if (!response.ok) {
                    throw new Error(payload.error || `Error API (${response.status})`);
                }

                const apiResult = await pollProfileJob(payload.job_id);
                setCompletedJobId(payload.job_id);
                setMessage("SPARQL endpoint profiled successfully!");
                setResultData(apiResult);
                return;
            }

            if (tab === "DUMP" && selectedFile) {
                const apiFormData = new FormData();
                apiFormData.append("file", selectedFile);
                const storeParam = saveProfile ? "true" : "false";
                const response = await fetch(`${BASE_PATH}/api/profile/file/jobs?store=${storeParam}`, {
                    method: "POST",
                    headers: {"Accept": "application/json"},
                    body: apiFormData,
                });

                const payload = await response.json();
                if (!response.ok) {
                    throw new Error(payload.error || `Error API (${response.status})`);
                }

                const apiResult = await pollProfileJob(payload.job_id);
                setCompletedJobId(payload.job_id);
                setMessage("RDF file profiled successfully!");
                setResultData(apiResult);
            }
        } catch (error) {
            console.error("Profile job error:", error);
            setMessage(`Error: ${error instanceof Error ? error.message : "An unknown error occurred during profiling."}`);
        } finally {
            setIsPending(false);
        }
    };

    const handleDownload = async (format: DownloadFormat) => {
        if (!completedJobId || isDownloading) return;

        setIsDownloading(format.format);
        try {
            const response = await fetch(`${BASE_PATH}/api/profile/jobs/${completedJobId}?format=${format.format}`, {
                method: "GET",
                headers: {"Accept": "application/json"},
            });
            const payload = await response.json();

            if (!response.ok) {
                throw new Error(payload.error || `Download request failed (${response.status})`);
            }
            if (payload.status !== "completed") {
                throw new Error("The profile is not ready yet.");
            }

            const body = typeof payload.result === "string" ? payload.result : JSON.stringify(payload.result, null, 2);
            const blob = new Blob([body], {type: format.mimeType});
            const url = URL.createObjectURL(blob);
            const anchor = document.createElement("a");
            anchor.href = url;
            anchor.download = `kg-profile.${format.extension}`;
            document.body.appendChild(anchor);
            anchor.click();
            anchor.remove();
            URL.revokeObjectURL(url);
        } catch (error) {
            console.error("Profile download error:", error);
            setMessage(`Error: ${error instanceof Error ? error.message : "Unable to download the selected format."}`);
        } finally {
            setIsDownloading(null);
        }
    };

    // Copy to clipboard functionality
    const handleCopy = async () => {
        if (!displayResponse) return;

        try {
            await navigator.clipboard.writeText(displayResponse);
            setIsCopied(true);
            setTimeout(() => setIsCopied(false), 2000);
        } catch (err) {
            console.error('Failed to copy:', err);
        }
    };

    // Reset form when switching tabs
    const handleTabChange = (newTab: string) => {
        if (UPLOAD) {
            setTab(newTab as "SPARQL" | "DUMP");
        } else {
            setTab(newTab as "SPARQL");
        }
        // Reset form state when switching tabs
        setSparqlUrl("");
        setHasFile(false);
        setSelectedFile(null);
        setFileSizeWarning("");
        setResultData(undefined);
        setCompletedJobId(null);
        setMessage("");
        if (fileInputRef.current) {
            fileInputRef.current.value = "";
        }
    };

    return (
        <div className="min-h-screen bg-background py-8">
            <div className="container mx-auto px-4 max-w-[120rem]">
                <div className="grid grid-cols-1 xl:grid-cols-2 gap-8">
                    {/* Form Section */}
                    <div className="bg-card border rounded-xl shadow-xl p-8 min-h-[50rem]">
                        <h2 className="text-xl font-bold text-foreground mb-6 text-center">
                            Classify RDF data
                        </h2>

                        <form
                            onSubmit={handleSubmit}
                            className="space-y-6"
                            autoComplete="off"
                        >
                            {/* Hidden input to specify the mode */}
                            <input type="hidden" name="mode" value={tab}/>

                            <div className="space-y-5">
                                <Tabs
                                    defaultValue="SPARQL"
                                    value={tab}
                                    onValueChange={handleTabChange}
                                    className="w-full"
                                >
                                    <div className="flex justify-center mb-6">
                                        {UPLOAD ? <TabsList className="grid w-full max-w-md grid-cols-2 h-10">
                                            <TabsTrigger value="SPARQL" id="tab-sparql" className="text-center text-sm">
                                                SPARQL
                                            </TabsTrigger>
                                            <TabsTrigger value="DUMP" id="tab-dump" className="text-center text-sm">
                                                DUMP
                                            </TabsTrigger>
                                        </TabsList> : <TabsList className="grid w-full max-w-md grid-cols-1 h-10">
                                            <TabsTrigger value="SPARQL" id="tab-sparql" className="text-center text-sm">
                                                SPARQL
                                            </TabsTrigger>
                                        </TabsList>
                                        }
                                    </div>

                                    {/* Fixed height container for consistent tab content height */}
                                    <div className="min-h-[220px]">
                                        <TabsContent value="SPARQL" className="space-y-4 mt-0">
                                            <div className="space-y-2">
                                                <Label htmlFor="sparql-url" className="text-sm font-medium">
                                                    SPARQL Endpoint
                                                </Label>
                                                <Input
                                                    type="url"
                                                    id="sparql-url"
                                                    name="sparqlUrl"
                                                    placeholder="https://example.com/sparql"
                                                    autoComplete="off"
                                                    value={sparqlUrl}
                                                    onChange={(e) => setSparqlUrl(e.target.value)}
                                                    required={tab === "SPARQL"}
                                                    disabled={tab !== "SPARQL" || isPending}
                                                    className="w-full h-10 text-sm"
                                                />
                                                <p className="text-xs text-muted-foreground">
                                                    Input the full URL of the SPARQL endpoint to analyze
                                                </p>
                                            </div>
                                        </TabsContent>

                                        {UPLOAD && <TabsContent value="DUMP" className="space-y-4 mt-0">
                                            <Card
                                                className="border-2 border-dashed border-muted hover:border-muted-foreground/50 transition-colors min-h-[180px]">
                                                <CardContent
                                                    className="p-6 space-y-4 flex flex-col justify-center min-h-[180px]">
                                                    <div className="text-center space-y-3">
                                                        <div className="flex justify-center">
                                                            <FileIcon className="w-12 h-12 text-muted-foreground"/>
                                                        </div>
                                                        <div className="space-y-1">
                                                            <p className="text-sm font-medium text-foreground">
                                                                Drag an RDF file or click here to select
                                                            </p>
                                                            <p className="text-xs text-muted-foreground">
                                                                Supported format: RDF, TTL, NQ, NT, XML, JSON
                                                            </p>
                                                            <p className="text-xs text-muted-foreground font-medium dark:text-blue-400">
                                                                Max size: 500MB
                                                            </p>
                                                        </div>
                                                    </div>

                                                    <div className="space-y-2">
                                                        <Label htmlFor="file-upload" className="text-sm font-medium">
                                                            Select RDF File
                                                        </Label>
                                                        <Input
                                                            id="file-upload"
                                                            name="file"
                                                            type="file"
                                                            accept=".rdf,.ttl,.nq,.nt,.xml,.json"
                                                            ref={fileInputRef}
                                                            onChange={handleFileChange}
                                                            required={tab === "DUMP"}
                                                            disabled={tab !== "DUMP" || isPending}
                                                            className="w-full h-10 text-sm"
                                                        />
                                                        <p className="text-xs text-muted-foreground">
                                                            Extension: .rdf, .ttl, .nq, .nt, .xml, .json (max 500MB)
                                                        </p>

                                                        {/* File info display */}
                                                        {selectedFile && (
                                                            <div className="mt-3 p-3 bg-muted/30 rounded-lg border">
                                                                <div className="flex items-center justify-between">
                                                                    <div className="flex-1 min-w-0">
                                                                        <p className="text-sm font-medium text-foreground truncate">
                                                                            {selectedFile.name}
                                                                        </p>
                                                                        <p className="text-xs text-muted-foreground">
                                                                            {formatFileSize(selectedFile.size)} • {selectedFile.type || 'Tipo sconosciuto'}
                                                                        </p>
                                                                    </div>
                                                                    <CheckIcon
                                                                        className="w-4 h-4 text-green-600 dark:text-green-400 ml-2 flex-shrink-0"/>
                                                                </div>
                                                            </div>
                                                        )}
                                                    </div>
                                                </CardContent>
                                            </Card>

                                            {/* File size warning */}
                                            {fileSizeWarning && (
                                                <div
                                                    className={`mt-4 p-3 rounded-lg border flex items-start space-x-2 ${
                                                        fileSizeWarning.includes('supera il limite') || fileSizeWarning.includes('non supportato')
                                                            ? 'border-destructive/50 bg-destructive/10'
                                                            : 'border-orange-500/50 bg-orange-500/10'
                                                    }`}>
                                                    <AlertTriangleIcon className={`w-4 h-4 mt-0.5 flex-shrink-0 ${
                                                        fileSizeWarning.includes('supera il limite') || fileSizeWarning.includes('non supportato')
                                                            ? 'text-destructive'
                                                            : 'text-orange-600 dark:text-orange-400'
                                                    }`}/>
                                                    <p className={`text-sm ${
                                                        fileSizeWarning.includes('supera il limite') || fileSizeWarning.includes('non supportato')
                                                            ? 'text-destructive'
                                                            : 'text-orange-700 dark:text-orange-300'
                                                    }`}>
                                                        {fileSizeWarning}
                                                    </p>
                                                </div>
                                            )}
                                        </TabsContent> }
                                    </div>
                                </Tabs>
                            </div>

                            <Separator className="my-6"/>

                            <div className="space-y-4">
                                {/* Save Profile Checkbox - First */}
                                <div className="flex items-start space-x-3 p-4 bg-muted/30 rounded-lg border">
                                    <Checkbox
                                        id="save-profile"
                                        name="saveProfile"
                                        disabled={isPending}
                                        className="mt-1"
                                    />
                                    <div className="flex-1">
                                        <Label htmlFor="save-profile" className="text-sm font-medium cursor-pointer">
                                            Save profile
                                        </Label>
                                        <p className="text-xs text-muted-foreground mt-1">
                                            Make the generated profile public
                                        </p>
                                    </div>
                                </div>

                                {/* Privacy Consent Checkbox - Second */}
                                <div className="flex items-start space-x-3 p-4 bg-muted/50 rounded-lg border">
                                    <Checkbox
                                        id="privacy-consent"
                                        name="privacyConsent"
                                        checked={privacyConsent}
                                        onCheckedChange={(checked) => setPrivacyConsent(!!checked)}
                                        required
                                        disabled={isPending}
                                        className="mt-1"
                                    />
                                    <div className="flex-1">
                                        <Label htmlFor="privacy-consent" className="text-sm font-medium cursor-pointer">
                                            Accept<Link href="/privacy" className="underline ml-0">terms and
                                            condition</Link>*
                                        </Label>
                                        <p className="text-xs text-muted-foreground mt-1">
                                            Obligatory to proceed
                                        </p>
                                    </div>
                                </div>
                            </div>

                            <Separator className="my-6"/>

                            <div className="flex justify-center pt-2">
                                <Button
                                    disabled={isPending || !isFormValid}
                                    id="submit"
                                    type="submit"
                                    aria-disabled={isPending || !isFormValid}
                                    className="w-full max-w-lg py-3 text-base font-semibold h-12"
                                    size="lg"
                                >
                                    {isPending ? (
                                        <div className="flex items-center space-x-2">
                                            <div
                                                className="w-4 h-4 border-2 border-current border-t-transparent rounded-full animate-spin"></div>
                                            <span>
                        {selectedFile && selectedFile.size > LARGE_FILE_THRESHOLD
                            ? 'Computing large file..'
                            : 'Computing...'
                        }
                      </span>
                                        </div>
                                    ) : (
                                        "Classify"
                                    )}
                                </Button>
                            </div>

                            {/* Display server validation errors */}
                            {message && message.includes("Error") && (
                                <div className="mt-6 p-4 rounded-lg border border-destructive/50 bg-destructive/10">
                                    <div className="flex items-start space-x-2">
                                        <AlertTriangleIcon className="w-5 h-5 text-destructive mt-0.5 flex-shrink-0"/>
                                        <p className="text-destructive text-sm">{message}</p>
                                    </div>
                                </div>
                            )}
                        </form>
                    </div>

                    {/* Response Section */}
                    <div className="bg-card border rounded-xl shadow-xl p-8 min-h-[50rem]">
                        <h2 className="text-xl font-bold text-foreground mb-6 text-center">
                            KG Profile
                        </h2>

                        <div className="space-y-4">
                            <ProfileSummary
                                data={resultData}
                                displayResponse={displayResponse}
                                onCopy={handleCopy}
                                isCopied={isCopied}
                                onDownload={handleDownload}
                                isDownloading={isDownloading}
                                currentJobId={completedJobId}
                            />

                            <InfiniteProgress isVisible={isPending}/>

                            {displayResponse && !isPending && (
                                <div className="mt-4 p-4 rounded-lg border border-green-500/50 bg-green-500/10">
                                    <div className="flex items-start space-x-2">
                                        <CheckIcon
                                            className="w-5 h-5 text-green-600 dark:text-green-400 mt-0.5 flex-shrink-0"/>
                                        <div className="flex-1">
                                            <p className="text-green-700 dark:text-green-300 text-sm font-medium">
                                                Classification completed successfully!
                                            </p>
                                            {selectedFile && (
                                                <p className="text-green-600 dark:text-green-400 text-xs mt-1">
                                                    File
                                                    elaborated: {selectedFile.name} ({formatFileSize(selectedFile.size)})
                                                </p>
                                            )}
                                        </div>
                                    </div>
                                </div>
                            )}
                        </div>
                    </div>
                </div>
            </div>
        </div>
    );
};
