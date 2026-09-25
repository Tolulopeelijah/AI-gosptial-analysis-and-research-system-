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
