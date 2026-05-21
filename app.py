import functools
import asyncio
import json
import os
import hashlib
import jwt
import psutil
import uuid
from concurrent.futures import ThreadPoolExecutor
from threading import Lock
from flasgger import Swagger
from flask import Flask, Response
from flask import request, jsonify, g
from werkzeug.utils import secure_filename

from config import Config
from src.service.generate_profile_service import load_classifier
from src.service.file_upload_service import UPLOAD_FOLDER, allowed_file
from src.service.generate_profile_service import generate_profile_service_store, generate_profile_service
from src.generate_profile import profile_to_rdf

AUTH = os.getenv("CLERK_MIDDLEWARE_ENABLED", "false").lower()
# PEM public key as string
PUBLIC_KEY = os.getenv("CLERK_MIDDLEWARE_PUBLIC_KEY", "false").lower()

app = Flask(__name__)

SECRET_KEY = os.environ.get("SECRET_KEY")
if not SECRET_KEY:
    raise ValueError("SECRET_KEY environment variable must be set.")

Swagger(app)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
active_requests = 0
profile_job_executor = ThreadPoolExecutor(max_workers=int(os.getenv("PROFILE_JOB_WORKERS", "4")))
profile_jobs: dict[str, dict] = {}
profile_jobs_lock = Lock()

load_classifier()


PROFILE_RESPONSE_FORMATS = {
    "json": ("json", "application/json"),
    "rdf": ("xml", "application/rdf+xml"),
    "rdfxml": ("xml", "application/rdf+xml"),
    "xml": ("xml", "application/rdf+xml"),
    "ttl": ("turtle", "text/turtle"),
    "turtle": ("turtle", "text/turtle"),
    "nt": ("nt", "application/n-triples"),
    "ntriples": ("nt", "application/n-triples"),
    "n-triples": ("nt", "application/n-triples"),
    "jsonld": ("json-ld", "application/ld+json"),
    "json-ld": ("json-ld", "application/ld+json"),
}

PROFILE_ACCEPT_FORMATS = {
    "application/json": "json",
    "application/rdf+xml": "rdf",
    "text/turtle": "ttl",
    "application/x-turtle": "ttl",
    "application/n-triples": "nt",
    "application/ld+json": "jsonld",
}


def clerk_jwt_required(fn):
    @functools.wraps(fn)
    async def wrapper(*args, **kwargs):
        if AUTH == "true":
            auth_header = request.headers.get("Authorization", None)
            if not auth_header or not auth_header.startswith("Bearer "):
                return jsonify({"error": "Missing or invalid Authorization header"}), 401
            token = auth_header.split(" ", 1)[1]
            try:
                payload = jwt.decode(
                    token,
                    PUBLIC_KEY,
                    algorithms=["RS256"],
                    options={"verify_aud": False}
                )
                g.current_user = payload
            except jwt.PyJWTError as e:
                app.logger.error(f"Token validation error: {e}")  # Only log internally
                return jsonify({"error": "Token validation error"}), 401

        return await fn(*args, **kwargs)

    return wrapper

def check_system_load(func):
    @functools.wraps(func)
    async def wrapper(*args, **kwargs):
        global active_requests
        cpu = psutil.cpu_percent(interval=0.1)
        ram = psutil.virtual_memory().percent
        if cpu > 90 or ram > 90:
            return jsonify({
                "error": "Server overloaded",
                "cpu_usage": cpu,
                "ram_usage": ram
            }), 500

        if active_requests >= 8:
            return jsonify({"error": "Too many active requests", "active_requests": active_requests}), 429

        active_requests += 1
        try:
            return await func(*args, **kwargs)
        finally:
            active_requests -= 1

    return wrapper


def _requested_profile_format(data: dict | None = None) -> str | None:
    requested_format = request.args.get("format")
    if requested_format is None and data is not None:
        requested_format = data.get("format")

    if requested_format:
        normalized = str(requested_format).strip().lower()
        if normalized in PROFILE_RESPONSE_FORMATS:
            return normalized
        return None

    accepted = request.accept_mimetypes.best_match(
        list(PROFILE_ACCEPT_FORMATS.keys()),
        default="application/json"
    )
    return PROFILE_ACCEPT_FORMATS.get(accepted, "json")


def _profile_has_id(result: dict) -> bool:
    profile_id = result.get("id")
    if isinstance(profile_id, list):
        return any(str(item).strip() for item in profile_id if item is not None)
    return bool(str(profile_id).strip()) if profile_id is not None else False


def _ensure_profile_id(result: dict | None, fallback_id: str | None) -> dict | None:
    if result is None or "error" in result or not fallback_id or _profile_has_id(result):
        return result

    result["id"] = fallback_id
    if not result.get("title"):
        result["title"] = fallback_id
    return result


def _profile_response(result: dict | None, requested_format: str, fallback_id: str | None = None):
    if result is None:
        return jsonify({"error": "Profile generation failed unexpectedly"}), 500

    if "error" in result:
        app.logger.error(f"Profile generation returned an error: {result['error']}")
        return jsonify({"error": result["error"]}), 500

    result = _ensure_profile_id(result, fallback_id)

    if requested_format == "json":
        return jsonify(result), 200

    rdf_format, mimetype = PROFILE_RESPONSE_FORMATS[requested_format]
    try:
        body = profile_to_rdf(result, base_iri=Config.BASE_DOMAIN, rdf_format=rdf_format)
    except Exception as e:
        app.logger.error(f"Profile RDF serialization failed: {e}")
        return jsonify({"error": "Profile RDF serialization failed"}), 500

    return Response(body, status=200, mimetype=mimetype)


def _store_job_update(job_id: str, **updates):
    with profile_jobs_lock:
        if job_id in profile_jobs:
            profile_jobs[job_id].update(updates)


async def _run_profile_job(job_id: str, target: str, sparql: bool, store: bool, fallback_id: str | None):
    _store_job_update(job_id, status="running")
    try:
        if store:
            result = await generate_profile_service_store(target, sparql=sparql)
        else:
            result = await generate_profile_service(target, sparql=sparql)

        if result is None:
            _store_job_update(job_id, status="failed", error="Profile generation failed unexpectedly")
        elif "error" in result:
            _store_job_update(job_id, status="failed", error=result["error"])
        else:
            result = _ensure_profile_id(result, fallback_id)
            _store_job_update(job_id, status="completed", result=result)
    except Exception as e:
        app.logger.error(f"Profile job {job_id} failed: {e}")
        _store_job_update(job_id, status="failed", error="Profile generation failed")


def _run_profile_job_sync(job_id: str, target: str, sparql: bool, store: bool, fallback_id: str | None):
    asyncio.run(_run_profile_job(job_id, target, sparql, store, fallback_id))


def _submit_profile_job(target: str, sparql: bool, store: bool, fallback_id: str | None = None) -> str:
    job_id = uuid.uuid4().hex
    with profile_jobs_lock:
        profile_jobs[job_id] = {
            "id": job_id,
            "status": "queued",
            "result": None,
            "error": None,
        }
    profile_job_executor.submit(_run_profile_job_sync, job_id, target, sparql, store, fallback_id)
    return job_id


def _job_status_response(job_id: str):
    with profile_jobs_lock:
        job = profile_jobs.get(job_id)
        if job is None:
            return jsonify({"error": "Job not found"}), 404
        payload = dict(job)

    requested_format = _requested_profile_format()
    if requested_format is None:
        return jsonify({"error": "Unsupported profile response format"}), 400

    if payload.get("status") == "completed" and requested_format != "json":
        rdf_format, _ = PROFILE_RESPONSE_FORMATS[requested_format]
        try:
            serialized = profile_to_rdf(payload.get("result"), base_iri=Config.BASE_DOMAIN, rdf_format=rdf_format)
            payload["result"] = json.loads(serialized) if requested_format in ("jsonld", "json-ld") else serialized
        except Exception as e:
            app.logger.error(f"Profile job RDF serialization failed: {e}")
            return jsonify({"error": "Profile RDF serialization failed"}), 500

    return jsonify(payload), 200


# ----- Endpoints -----
@app.route('/api/v1/profile/sparql', methods=['POST'])
@check_system_load
@clerk_jwt_required
async def sparql_profile():
    """
    Generate a profile from a SPARQL endpoint.
    ---
    tags:
      - Profile
    consumes:
      - application/json
    parameters:
      - in: body
        name: body
        required: true
        schema:
          type: object
          properties:
            endpoint:
              type: string
              description: SPARQL endpoint URL
            store:
              type: boolean
              description: Whether to store the profile result
            format:
              type: string
              enum: [json, rdf, ttl, nt, jsonld]
              description: Response format. Defaults to json; can also be requested via the Accept header.
          required:
            - endpoint
    responses:
      200:
        description: Successfully generated profile
        schema:
          type: object
          properties:
            status:
              type: string
            data:
              type: object
      400:
        description: Bad request (missing or invalid parameters)
      429:
        description: Too many active requests
      500:
        description: Server overloaded or internal error
    """
    data = request.get_json() or {}
    requested_format = _requested_profile_format(data)
    if requested_format is None:
        return jsonify({"error": "Unsupported profile response format"}), 400

    endpoint = data.get('endpoint')
    if not endpoint:
        return jsonify({"error": "Missing 'endpoint' parameter"}), 400

    store_value = data.get('store', False)
    if isinstance(store_value, bool):
        store_flag = store_value
    elif isinstance(store_value, str) and store_value.lower() in ['true', 'false']:
        store_flag = store_value.lower() == 'true'
    else:
        store_flag = False
    try:
        if store_flag:
            result = await generate_profile_service_store(endpoint, sparql=True)
        else:
            result = await generate_profile_service(endpoint, sparql=True)
    except Exception as e:
        app.logger.error(f"Profile generation failed: {e}")  # Only log internally
        return jsonify({"error": "Profile generation failed"}), 500

    return _profile_response(result, requested_format, fallback_id=endpoint)


@app.route('/api/v1/profile/sparql/jobs', methods=['POST'])
@check_system_load
@clerk_jwt_required
async def sparql_profile_job():
    data = request.get_json() or {}
    endpoint = data.get('endpoint')
    if not endpoint:
        return jsonify({"error": "Missing 'endpoint' parameter"}), 400

    store_value = data.get('store', False)
    if isinstance(store_value, bool):
        store_flag = store_value
    elif isinstance(store_value, str) and store_value.lower() in ['true', 'false']:
        store_flag = store_value.lower() == 'true'
    else:
        store_flag = False

    job_id = _submit_profile_job(endpoint, sparql=True, store=store_flag, fallback_id=endpoint)
    return jsonify({"job_id": job_id, "status": "queued"}), 202


@app.route('/api/v1/profile/jobs/<job_id>', methods=['GET'])
@clerk_jwt_required
async def profile_job_status(job_id: str):
    return _job_status_response(job_id)


@app.route('/api/v1/profile/file', methods=['POST'])
@check_system_load
@clerk_jwt_required
async def rdf_profile():
    """
    Generate a profile from an uploaded RDF file.
    ---
    tags:
      - Profile
    consumes:
      - multipart/form-data
    parameters:
      - in: formData
        name: file
        type: file
        required: true
        description: The RDF file to upload
      - in: query
        name: store
        type: boolean
        required: false
        description: Whether to store the profile result
      - in: query
        name: format
        type: string
        enum: [json, rdf, ttl, nt, jsonld]
        required: false
        description: Response format. Defaults to json; can also be requested via the Accept header.
    responses:
      200:
        description: Successfully generated profile
        schema:
          type: object
          properties:
            status:
              type: string
            data:
              type: object
      400:
        description: Bad request (missing file or invalid parameters)
      403:
        description: Permission denied
      429:
        description: Too many active requests
      500:
        description: Server overloaded or internal error
    """
    if not Config.ALLOW_UPLOAD:
        app.logger.error(f"Profile generation returned an error: No permission to upload file")  # Log the error details
        return jsonify({"error": "No permission to upload file"}), 403

    requested_format = _requested_profile_format()
    if requested_format is None:
        return jsonify({"error": "Unsupported profile response format"}), 400

    if 'file' not in request.files:
        return jsonify({"error": "No file part"}), 400

    file = request.files['file']
    if file.filename == '':
        return jsonify({"error": "No selected file"}), 400

    if not allowed_file(file.filename):
        return jsonify({"error": "File type not allowed"}), 400

    filename = secure_filename(file.filename)
    save_path = os.path.join(app.config['UPLOAD_FOLDER'], hashlib.sha256(str(filename).encode()).hexdigest())
    try:
        file.save(save_path)
    except Exception as e:
        app.logger.error(f"Error saving file: {e}")  # Only log internally
        return jsonify({"error": "Error saving file"}), 500

    store_param = request.args.get('store', 'false').lower()
    store_flag = store_param in ('true', '1', 'yes')

    try:
        if store_flag:
            result = await generate_profile_service_store(save_path, sparql=False)
        else:
            result = await generate_profile_service(save_path, sparql=False)
    except Exception as e:
        app.logger.error(f"Profile generation failed: {e}")  # Only log internally
        return jsonify({"error": "Profile generation failed"}), 500

    fallback_id = os.path.splitext(filename)[0]
    return _profile_response(result, requested_format, fallback_id=fallback_id)


@app.route('/api/v1/profile/file/jobs', methods=['POST'])
@check_system_load
@clerk_jwt_required
async def rdf_profile_job():
    if not Config.ALLOW_UPLOAD:
        app.logger.error("Profile generation returned an error: No permission to upload file")
        return jsonify({"error": "No permission to upload file"}), 403

    if 'file' not in request.files:
        return jsonify({"error": "No file part"}), 400

    file = request.files['file']
    if file.filename == '':
        return jsonify({"error": "No selected file"}), 400

    if not allowed_file(file.filename):
        return jsonify({"error": "File type not allowed"}), 400

    filename = secure_filename(file.filename)
    save_path = os.path.join(app.config['UPLOAD_FOLDER'], hashlib.sha256(str(filename).encode()).hexdigest())
    try:
        file.save(save_path)
    except Exception as e:
        app.logger.error(f"Error saving file: {e}")
        return jsonify({"error": "Error saving file"}), 500

    store_param = request.args.get('store', 'false').lower()
    store_flag = store_param in ('true', '1', 'yes')

    fallback_id = os.path.splitext(filename)[0]
    job_id = _submit_profile_job(save_path, sparql=False, store=store_flag, fallback_id=fallback_id)
    return jsonify({"job_id": job_id, "status": "queued"}), 202


if __name__ == '__main__':
    app.run()
