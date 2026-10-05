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

# Bumped on every deploy-relevant change so /health reveals which code a
# host is actually running (Render redeploys take minutes; poll until this
# flips before re-testing a fix).
APP_VERSION = "2026-10-05-single-row-salvage"


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
    return jsonify({"status": "ok", "version": APP_VERSION})


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

    # MapServer counterparts supplied by the operator (county exposes the
    # same views as MapServer; FeatureServer metadata 500s on every layer).
    mapserver_layers = {
        "septic_MapServer_0":
            "https://lcenggis.co.lucas.oh.us/gisengserver/rest/services/"
            "LCHD_SEPTIC/SEPTIC_SYSTEM_VIEW/MapServer/0",
        "floodplain_MapServer_7":
            "https://lcenggis.co.lucas.oh.us/gisengserver/rest/services/"
            "FLOODPLAIN/FLOODPLAIN_VIEW/MapServer/7",
        "floodplain_MapServer_6":
            "https://lcenggis.co.lucas.oh.us/gisengserver/rest/services/"
            "FLOODPLAIN/FLOODPLAIN_VIEW/MapServer/6",
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
            result["metadata_raw_snippet"] = meta_resp.text[:600]
            meta_resp.raise_for_status()
            meta = meta_resp.json()
            result["metadata_keys"] = sorted(meta.keys())[:30]
            if "error" in meta:
                result.update({
                    "ok": False, "stage": "metadata",
                    "error": str(meta["error"]),
                })
                return result
            result["service_name"] = meta.get("name")
            result["geometryType"] = meta.get("geometryType")
            result["maxRecordCount"] = meta.get("maxRecordCount")
            result["fields_count"] = len(meta.get("fields", []) or [])
        except Exception as exc:
            result.update({
                "ok": False, "stage": "metadata",
                "error": f"{type(exc).__name__}: {exc}",
            })
            return result
        # 3. Live query attempts — the single probe above used:
        #      /query?where=1=1&outFields=*&returnGeometry=false
        #              &f=json&resultRecordCount=1
        #    That is what returned the 500. Try variants to isolate whether
        #    the failure is outFields=*, f=json, returnGeometry, or the
        #    service itself being broken.
        variants = [
            ("a_where_count_only",
             {"where": "1=1", "returnCountOnly": "true", "f": "json"}),
            ("b_app_style_geojson",
             {"where": "1=1", "outFields": "*", "returnGeometry": "true",
              "f": "geojson", "resultRecordCount": 1}),
            ("c_objectid_only",
             {"where": "1=1", "outFields": "OBJECTID",
              "returnGeometry": "false", "f": "json",
              "resultRecordCount": 1}),
            ("d_star_nogeom_json",
             {"where": "1=1", "outFields": "*", "returnGeometry": "false",
              "f": "json", "resultRecordCount": 1}),
        ]
        attempts = []
        for label, params in variants:
            try:
                t0 = time.time()
                q_resp = requests.get(
                    url.rstrip("/") + "/query", params=params, timeout=12)
                ms = int((time.time() - t0) * 1000)
                payload = q_resp.json()
                if "error" in payload:
                    attempts.append({"variant": label, "params": params,
                                     "ok": False, "http": q_resp.status_code,
                                     "ms": ms, "error": str(payload["error"])})
                else:
                    n = (len(payload.get("features", []))
                         if "features" in payload else payload.get("count"))
                    attempts.append({"variant": label, "params": params,
                                     "ok": True, "http": q_resp.status_code,
                                     "ms": ms, "count": n})
            except Exception as exc:
                attempts.append({"variant": label, "params": params,
                                 "ok": False,
                                 "error": f"{type(exc).__name__}: {exc}"})
        result["query_attempts"] = attempts
        good = [a for a in attempts if a.get("ok")]
        if good:
            result.update({
                "ok": True,
                "feature_count": good[0].get("count"),
                "working_variant": good[0].get("variant"),
            })
        else:
            first_err = attempts[0].get("error", "") if attempts else ""
            result.update({
                "ok": False, "stage": "query",
                "error": (attempts[3].get("error", "") if len(attempts) > 3
                          else first_err),
            })
        # Back-compat flat fields for the original single probe (variant d).
        if len(attempts) > 3:
            result["query_ms"] = attempts[3].get("ms")
            result["query_status"] = attempts[3].get("http")
        return result

    probes = [probe(name, url) for name, url in layers.items()]
    live_ok = sum(1 for p in probes if p.get("ok"))

    map_probes = [probe(name, url) for name, url in mapserver_layers.items()]
    map_ok = sum(1 for p in map_probes if p.get("ok"))

    # 4. Service-root probes: if the layers 500 but the parent
    # FeatureServer / services directory answers, the county DB/service
    # is broken; if the roots also 500, the whole gisengserver instance
    # is down (not a Render block — we already got HTTP 200s from it).
    roots = {}
    for label, root_url in {
        "services_directory": "https://lcenggis.co.lucas.oh.us/gisengserver/rest/services?f=json",
        "septic_service": "https://lcenggis.co.lucas.oh.us/gisengserver/rest/services/LCHD_SEPTIC/SEPTIC_SYSTEM_VIEW/FeatureServer?f=json",
        "floodplain_service": "https://lcenggis.co.lucas.oh.us/gisengserver/rest/services/FLOODPLAIN/FLOODPLAIN_VIEW/FeatureServer?f=json",
        "septic_map_service": "https://lcenggis.co.lucas.oh.us/gisengserver/rest/services/LCHD_SEPTIC/SEPTIC_SYSTEM_VIEW/MapServer?f=json",
        "floodplain_map_service": "https://lcenggis.co.lucas.oh.us/gisengserver/rest/services/FLOODPLAIN/FLOODPLAIN_VIEW/MapServer?f=json",
    }.items():
        try:
            t0 = time.time()
            rr = requests.get(
                root_url,
                timeout=12,
                headers={"User-Agent": "Mozilla/5.0 (diagnostic probe)"},
            )
            ms = int((time.time() - t0) * 1000)
            try:
                body = rr.json()
            except Exception:
                body = None
            snippet = rr.text[:400]
            if isinstance(body, dict) and "error" in body:
                roots[label] = {"ok": False, "http": rr.status_code,
                                "ms": ms, "error": str(body["error"]),
                                "snippet": snippet}
            elif rr.status_code != 200:
                roots[label] = {"ok": False, "http": rr.status_code,
                                "ms": ms, "snippet": snippet}
            else:
                keys = sorted(body.keys())[:20] if isinstance(body, dict) else []
                roots[label] = {"ok": True, "http": rr.status_code, "ms": ms,
                                "keys": keys, "snippet": snippet,
                                "layers": body.get("layers")
                                if isinstance(body, dict) else None,
                                "services": (body.get("services")[:5]
                                             if isinstance(body, dict)
                                             and isinstance(body.get("services"),
                                                              list) else None)}
        except Exception as exc:
            roots[label] = {"ok": False,
                            "error": f"{type(exc).__name__}: {exc}"}

    # Root-cause hint: mock flag overrides live reachability everywhere.
    meta_all_500 = (
        live_ok == 0
        and all("metadata_keys" in p and p.get("metadata_keys") == ["error"]
                for p in probes if p.get("metadata_keys"))
    )
    if map_ok == len(map_probes) and map_ok > 0:
        verdict = (
            f"MapServer paths work ({map_ok}/{len(map_probes)}) — switch the "
            "ARCGIS_*_URL env vars to these MapServer layer URLs and set "
            "ARCGIS_USE_MOCK=false to serve live data. FeatureServer paths "
            "remain broken county-side."
        )
    elif map_ok > 0:
        verdict = (
            f"MapServer partially works ({map_ok}/{len(map_probes)}). "
            "Use the working MapServer URLs in ARCGIS_*_URL and keep mock "
            "off only if all needed layers work; otherwise working layers go "
            "live and failed ones return data_unavailable."
        )
    elif meta_all_500:
        verdict = (
            "County ArcGIS server reached OK from this host (HTTP 200), but "
            "the application itself returns code 500 with empty message for "
            "EVERY layer metadata request. This is a county-side failure "
            "(service down / SDE database offline / service retired), NOT a "
            "Render egress block. Keep ARCGIS_USE_MOCK=true until the county "
            "fixes it; flipping to false will only surface data_unavailable "
            "errors. See service_roots below: if the services directory is "
            "also 500, the whole gisengserver instance is down."
        )
    elif settings.ARCGIS_USE_MOCK:
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
        "mapserver_reachable": f"{map_ok}/{len(map_probes)}",
        "verdict": verdict,
        "layers": probes,
        "mapserver_layers": map_probes,
        "service_roots": roots,
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
