
import csv
import gzip
import io
import json
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import requests


BASE_DIR = Path(__file__).resolve().parent
SOURCES_PATH = BASE_DIR / 'lodcloud_sources.json'
OUTPUT_DIR = BASE_DIR / 'kgsum_profiles'
TIMINGS_LOG_PATH = BASE_DIR / 'kgsum_profile_timings.csv'
PROFILE_API_BASE_URL = 'http://localhost:5000/api/v1/profile'
ALLOWED_RDF_EXTENSIONS = {'xml', 'trig', 'ttl', 'nq', 'nt', 'rdf', 'owl', 'n3', 'json', 'jsonld'}
GZIP_MAGIC = b'\x1f\x8b'
ZIP_MAGIC = b'PK\x03\x04'
TIMINGS_LOG_FIELDS = [
    'source_id',
    'method',
    'target',
    'status',
    'status_code',
    'started_at',
    'ended_at',
    'elapsed_seconds',
    'error',
]


def download_url_candidates(download_url):
    parsed = urlparse(download_url)
    if parsed.netloc.lower() != 'github.com':
        return [download_url]

    parts = parsed.path.lstrip('/').split('/')
    if len(parts) < 5 or parts[2] != 'blob':
        return [download_url]

    owner, repo, _, branch = parts[:4]
    path = '/'.join(parts[4:])
    return [
        f'https://github.com/{owner}/{repo}/raw/{branch}/{path}',
        f'https://raw.githubusercontent.com/{owner}/{repo}/{branch}/{path}',
    ]


def write_profile(source_id, profile):
    OUTPUT_DIR.mkdir(exist_ok=True)
    with (OUTPUT_DIR / f'{source_id}.ttl').open('w') as f:
        f.write(profile)


def profile_exists(source_id):
    return (OUTPUT_DIR / f'{source_id}.ttl').exists()


def append_timing_log(
        source_id,
        method,
        target,
        status,
        status_code,
        started_at,
        ended_at,
        elapsed_seconds,
        error='',
):
    log_exists = TIMINGS_LOG_PATH.exists()
    with TIMINGS_LOG_PATH.open('a', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=TIMINGS_LOG_FIELDS)
        if not log_exists:
            writer.writeheader()
        writer.writerow({
            'source_id': source_id,
            'method': method,
            'target': target,
            'status': status,
            'status_code': status_code if status_code is not None else '',
            'started_at': started_at.isoformat(),
            'ended_at': ended_at.isoformat(),
            'elapsed_seconds': f'{elapsed_seconds:.6f}',
            'error': error,
        })


def filename_from_download_url(source_id, download_url):
    path = Path(urlparse(download_url).path)
    suffixes = [suffix.lower().lstrip('.') for suffix in path.suffixes]

    if suffixes and suffixes[-1] in {'gz', 'zip'}:
        suffixes = suffixes[:-1]

    extension = suffixes[-1] if suffixes and suffixes[-1] in ALLOWED_RDF_EXTENSIONS else 'ttl'
    if extension == 'owl':
        extension = 'xml'
    return f'{source_id}.{extension}'


def unzip_rdf_payload(source_id, content):
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        for name in archive.namelist():
            suffix = Path(name).suffix.lower().lstrip('.')
            if suffix in ALLOWED_RDF_EXTENSIONS:
                if suffix == 'owl':
                    suffix = 'xml'
                return archive.read(name), f'{source_id}.{suffix}'

    raise ValueError('No supported RDF file found in zip archive')


def looks_like_html(content):
    sample = content[:4096].lstrip().lower()
    return sample.startswith((b'<!doctype html', b'<html')) or b'<html' in sample[:512]


def validate_download_response(source_id, response):
    content_type = response.headers.get('Content-Type', '')
    final_url = response.url
    if response.status_code != 200:
        raise ValueError(f'HTTP {response.status_code} from {final_url}')
    if looks_like_html(response.content) or 'text/html' in content_type.lower():
        raise ValueError(f'download returned HTML instead of RDF data: {final_url} ({content_type or "unknown content type"})')
    if not response.content:
        raise ValueError(f'download returned an empty payload: {final_url}')


def prepare_rdf_payload(source_id, download_url, content):
    parsed_path = urlparse(download_url).path.lower()
    filename = filename_from_download_url(source_id, download_url)

    if parsed_path.endswith('.gz'):
        if not content.startswith(GZIP_MAGIC):
            if looks_like_html(content):
                raise ValueError(f'URL ends with .gz but payload is HTML; first bytes: {content[:16]!r}')
            return content, filename
        return gzip.decompress(content), filename

    if parsed_path.endswith('.zip'):
        if not content.startswith(ZIP_MAGIC):
            raise ValueError(f'URL ends with .zip but payload is not zip data; first bytes: {content[:16]!r}')
        return unzip_rdf_payload(source_id, content)

    return content, filename


def request_profile_from_file(source_id, download_url):
    last_error = None
    for candidate_url in download_url_candidates(download_url):
        try:
            download_response = requests.get(candidate_url, timeout=600)
        except requests.RequestException as exc:
            last_error = exc
            print(f"Failed to download {source_id} from {candidate_url}: {exc}")
            continue

        try:
            validate_download_response(source_id, download_response)
        except ValueError as exc:
            last_error = exc
            print(f"Failed to download {source_id} from {candidate_url}: {exc}")
            continue

        download_url = download_response.url
        break
    else:
        if last_error is not None:
            print(f"Failed to download {source_id}: {last_error}")
        return None

    try:
        content, filename = prepare_rdf_payload(source_id, download_url, download_response.content)
    except (OSError, ValueError, zipfile.BadZipFile) as exc:
        print(f"Failed to unpack {source_id}: {exc}")
        return None

    files = {
        'file': (
            filename,
            content,
            'text/turtle',
        )
    }
    return requests.post(
        f'{PROFILE_API_BASE_URL}/file',
        params={'format': 'ttl'},
        files=files,
    )


def create_kgsum_profiles():
    with SOURCES_PATH.open('r') as f:
        sources = json.load(f)

    for source in sources:
        print(f"Processing {source['id']}...")
        if profile_exists(source['id']):
            print(f"Skipping {source['id']}: profile already exists")
            continue

        if source.get('sparql_endpoint'):
            sparql_endpoint = source['sparql_endpoint']
            print(f"{source['id']}: {sparql_endpoint}")
            started_at = datetime.now(timezone.utc)
            started = time.perf_counter()
            response = None
            status = 'failed'
            error = ''
            try:
                response = requests.post(
                    f'{PROFILE_API_BASE_URL}/sparql',
                    json={'endpoint': sparql_endpoint, 'format': 'ttl'},
                    headers={'Content-Type': 'application/json'}
                )
                if response.status_code == 200:
                    write_profile(source['id'], response.text)
                    status = 'success'
                else:
                    status = 'failed'
                    error = response.text.strip()
                    print(
                        f"Failed to profile {source['id']} with SPARQL endpoint: "
                        f"{response.status_code} {error[:1000]}"
                    )
            except requests.RequestException as exc:
                status = 'failed'
                error = str(exc)
                print(f"Failed to profile {source['id']} with SPARQL endpoint: {exc}")
            finally:
                ended_at = datetime.now(timezone.utc)
                append_timing_log(
                    source['id'],
                    'sparql_endpoint',
                    sparql_endpoint,
                    status,
                    response.status_code if response is not None else None,
                    started_at,
                    ended_at,
                    time.perf_counter() - started,
                    error,
                )
        if source.get('rdf_dump'):
            download_url = source['rdf_dump']
            print(f"{source['id']}: {download_url}")
            started_at = datetime.now(timezone.utc)
            started = time.perf_counter()
            response = None
            status = 'failed'
            error = ''
            try:
                response = request_profile_from_file(source['id'], download_url)
                if response is None:
                    status = 'failed'
                    error = 'download_or_unpack_failed'
                    continue

                if response.status_code == 200:
                    write_profile(source['id'], response.text)
                    status = 'success'
                else:
                    status = 'failed'
                    error = response.text.strip()
                    print(
                        f"Failed to profile {source['id']} with download URL: "
                        f"{response.status_code} {error[:1000]}"
                    )
            except requests.RequestException as exc:
                status = 'failed'
                error = str(exc)
                print(f"Failed to profile {source['id']} with download URL: {exc}")
            finally:
                ended_at = datetime.now(timezone.utc)
                append_timing_log(
                    source['id'],
                    'rdf_dump',
                    download_url,
                    status,
                    response.status_code if response is not None else None,
                    started_at,
                    ended_at,
                    time.perf_counter() - started,
                    error,
                )


if __name__ == "__main__":
    create_kgsum_profiles()
