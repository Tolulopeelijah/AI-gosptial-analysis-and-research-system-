# Gunicorn production settings.
# Launch with: gunicorn -c gunicorn.conf.py server:app
#
# Why timeout=300: the county ArcGIS server answers slowly (seconds per
# request), so legitimate multi-step spatial queries (reference fetch across
# 2 layer URLs + server-side proximity + count) take well over a minute.
# The 30s default SIGKILLs healthy workers mid-query, surfacing as
# HTTP 500/502 at ~31s. Threads keep concurrent layer fetches cheap.
timeout = 300
graceful_timeout = 30
workers = 2
threads = 4
worker_class = "gthread"
keepalive = 5
