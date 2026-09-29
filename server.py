"""Flask HTTP API matching the frontend contract
(`frontend/src/services/httpGeospatialApi.ts`):

  POST /query   body {query, context?} -> QueryResponse (+ optional events)
  GET  /health  -> 200 {"status": "ok"}

Supports both plain JSON and SSE (`Accept: text/event-stream`), emitting the
AgentEvent frames the UI already understands.
"""

from __future__ import annotations

import json
import logging

from flask import Flask, Response, jsonify, request

from agent.agent import GeospatialAgent

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("geospatial-server")

app = Flask(__name__)
agent = GeospatialAgent()


@app.after_request
def add_cors_headers(response):
    # The Vite dev server (and any other origin) must be allowed to read the
    # API — without these headers the browser blocks cross-origin fetch/SSE
    # and the frontend reports "Backend offline" even when the server is up.
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = (
        "Content-Type, Accept, Authorization"
    )
    return response


@app.route("/query", methods=["OPTIONS"])
def query_preflight():
    return ("", 204)


@app.get("/health")
def health():
    return jsonify({"status": "ok"})


@app.get("/test-arcgis")
def test_arcgis():
    """Backend-only live ArcGIS connectivity check.

    Hits the Lucas County FeatureServer URLs *directly from this backend*
    (bypassing ARCGIS_USE_MOCK), so you can tell whether the host
    (e.g. Render) is blocked vs. the app just serving fixtures.

    Open in a browser or curl it — no frontend needed:
        GET https://<your-app>.onrender.com/test-arcgis

    Returns per-layer metadata + 1-feature query attempts with timings,
    plus the likely root cause when the app still serves demo data.
    """
    import socket
    import time
    from urllib.parse import urlparse

    import requests

    from agent.config import settings

    layers = {
        "septic_systems_0": settings.ARCGIS_SEPTIC_URL,
        "floodplains_0": settings.ARCGIS_FLOODPLAIN_0_URL,
        "floodplains_4": settings.ARCGIS_FLOODPLAIN_4_URL,
    }

    def probe(name: str, url: str):
        result: dict = {"layer": name, "url": url or "(not configured)"}
        if not url:
            result.update({"ok": False, "reason": "URL env var empty on this host"})
            return result
        parsed = urlparse(url)
        # 1. DNS — distinguishes "host network blocked" from HTTP-level blocks.
        try:
            result["dns_ip"] = socket.gethostbyname(parsed.hostname or "")
        except Exception as exc:
            result.update({
                "ok": False, "stage": "dns",
                "error": f"{type(exc).__name__}: {exc}",
            })
            return result
        # 2. Live metadata (?f=json) — proves TCP+TLS+HTTP works to the county.
        try:
            t0 = time.time()
            meta_resp = requests.get(url.rstrip("/") + "?f=json", timeout=12)
            result["metadata_ms"] = int((time.time() - t0) * 1000)
            result["metadata_status"] = meta_resp.status_code
            meta_resp.raise_for_status()
            meta = meta_resp.json()
            result["service_name"] = meta.get("name")
            result["geometryType"] = meta.get("geometryType")
            result["maxRecordCount"] = meta.get("maxRecordCount")
        except Exception as exc:
            result.update({
                "ok": False, "stage": "metadata",
                "error": f"{type(exc).__name__}: {exc}",
            })
            return result
        # 3. Live 1-feature query — proves the /query path the agent uses.
        try:
            t0 = time.time()
            q_resp = requests.get(
                url.rstrip("/") + "/query",
                params={"where": "1=1", "outFields": "*",
                        "returnGeometry": "false",
                        "f": "json", "resultRecordCount": 1},
                timeout=12,
            )
            result["query_ms"] = int((time.time() - t0) * 1000)
            result["query_status"] = q_resp.status_code
            q_resp.raise_for_status()
            payload = q_resp.json()
            if "error" in payload:
                result.update({"ok": False, "stage": "query",
                               "error": str(payload["error"])})
                return result
            result.update({
                "ok": True,
                "feature_count": len(payload.get("features", [])),
            })
        except Exception as exc:
            result.update({
                "ok": False, "stage": "query",
                "error": f"{type(exc).__name__}: {exc}",
            })
        return result

    probes = [probe(name, url) for name, url in layers.items()]
    live_ok = sum(1 for p in probes if p.get("ok"))

    # Root-cause hint: mock flag overrides live reachability everywhere.
    if settings.ARCGIS_USE_MOCK:
        verdict = (
            "ARCGIS_USE_MOCK=true on this host, so ALL queries serve demo "
            "fixtures even if the live servers below are reachable. "
            "Set ARCGIS_USE_MOCK=false in the Render env vars and redeploy "
            "to serve live data."
        )
    elif live_ok == len(probes):
        verdict = "Live ArcGIS reachable and mock disabled — app should serve live data."
    elif live_ok > 0:
        verdict = (
            "Partial live reachability — reachable layers serve live data, "
            "failed layers return data_unavailable errors (not demo data)."
        )
    else:
        verdict = (
            "Live ArcGIS unreachable from this host (all probes failed) — "
            "likely host egress firewall / county geo-allowlist. "
            "Keep ARCGIS_USE_MOCK=true here, or allowlist Render egress IPs "
            "on the county server."
        )

    try:
        import requests as _r
        egress_ip = _r.get("https://api.ipify.org", timeout=8).text.strip()
    except Exception:
        egress_ip = "(lookup failed)"

    return jsonify({
        "mock_enabled": settings.ARCGIS_USE_MOCK,
        "egress_ip": egress_ip,
        "live_reachable": f"{live_ok}/{len(probes)}",
        "verdict": verdict,
        "layers": probes,
    })


@app.get("/api/datasets")
def list_datasets():
    from agent.registry import available_datasets, build_registry

    reg = build_registry()
    return jsonify({
        "datasets": [ds.to_dict() for ds in reg.values()],
        "available": available_datasets(reg),
    })


@app.post("/api/datasets/upload")
def upload_dataset():
    from agent.uploads import ingest_upload

    if "file" not in request.files:
        return jsonify({"ok": False, "error": "no file part; send multipart 'file'"}), 400
    upload = request.files["file"]
    if not upload.filename:
        return jsonify({"ok": False, "error": "empty filename"}), 400
    result = ingest_upload(upload.filename, upload.read())
    return jsonify(result), (200 if result.get("ok") else 400)


@app.delete("/api/datasets/<name>")
def delete_dataset(name: str):
    from agent.registry import build_registry
    from agent.uploads import delete_upload

    reg = build_registry()
    info = reg.get(name)
    if info is None or info.source_type != "user_upload":
        return jsonify({"ok": False,
                        "error": f"'{name}' is not a user-uploaded dataset"}), 404
    result = delete_upload(name)
    return jsonify(result), (200 if result.get("ok") else 400)


@app.post("/query")
def query():
    body = request.get_json(force=True, silent=True) or {}
    text = (body.get("query") or "").strip()
    mode = (body.get("mode") or "research").strip()
    history = body.get("history") or []
    aims = (body.get("aims") or "").strip() if isinstance(body.get("aims"), str) else ""
    wants_sse = "text/event-stream" in (request.headers.get("Accept") or "")

    if wants_sse:
        def generate():
            events: list = []

            def sink(event):
                events.append(event)
                yield f"data: {json.dumps(event)}\n\n"

            # Collect-then-stream: execution is fast and this keeps ordering exact.
            collected: list = []
            response = agent.ask(text, mode=mode, history=history, aims=aims,
                                 on_event=collected.append)
            yield f"data: {json.dumps({'type': 'query_received', 'queryId': response['queryId']})}\n\n"
            for event in collected:
                if event.get("type") == "query_received":
                    continue
                yield f"data: {json.dumps(event)}\n\n"
            for layer in response.get("results", []) or []:
                yield f"data: {json.dumps({'type': 'result', 'data': layer})}\n\n"
            if response.get("status") == "completed":
                yield f"data: {json.dumps({'type': 'completed', 'explanation': response.get('explanation'), 'dataset': response.get('dataset'), 'count': response.get('count'), 'references': response.get('references'), 'tables': response.get('tables')})}\n\n"
            else:
                err = response.get("error", {})
                yield f"data: {json.dumps({'type': 'error', 'code': err.get('code', 'query_failed'), 'message': err.get('message', 'failed'), 'detail': err.get('detail'), 'hint': err.get('hint')})}\n\n"

            _ = sink  # (per-event streaming hook point for future async execution)

        return Response(generate(), mimetype="text/event-stream")

    response = agent.answer_stream(text, mode=mode, history=history, aims=aims)
    return jsonify(response)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000, debug=True)
