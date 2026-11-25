# Per-Container & Server-Wide Wake-on-Request Auto-Sleep Implementation Plan

> **For Antigravity:** REQUIRED SUB-SKILL: Load executing-plans to implement this plan task-by-task.

**Goal:** Upgrade Auto Sleep Mode to track per-container and server-wide request activity, sleep idle containers or the entire stack automatically, and transparently wake sleeping containers (+ dependencies) on the very next incoming request via an ultralight in-process `asyncio` Wake-Proxy.

**Architecture:** Track `container_last_request` and `server_last_request` in `ops_resources.py`, attach dependency-aware single-flight `wake_service_and_wait()`, run zero-overhead `asyncio.start_server` TCP wake-proxies in `app.py` (for `nextcloud:8081->80`, `navidrome:4533->4533`, `maloja:42010->42010`, `samba:445->445`) plus HTTP `/svc/{service}` fallback, ignore `X-Background-Poll: 1` UI polling when measuring idle time, and expose per-container idle status + settings in `dashboard.html` and `docker-compose.yml`.

**Tech Stack:** Python `asyncio` stdlib, FastAPI, Docker SDK, `psutil`, Vanilla JS. Zero new dependencies or containers.

---

### Task 1: Per-Container & Server-Wide Idle Tracking + Dependency-Aware Wake State Machine (`ops_resources.py`)
- Add settings (`container_idle_sleep_enabled`, `container_idle_minutes`, `server_idle_sleep_enabled`, `server_idle_minutes`, `wake_all_on_server_wake`, `wake_timeout_sec`) cleanly into `get_sleep_settings` / `save_sleep_settings`.
- Implement in-memory thread-safe request tracker (`touch_container_request(service)`, `touch_server_request()`, `evaluate_idle_sleep_and_sleep(...)`) with dependency graph (`SERVICE_DEPENDENCIES = {"nextcloud": ["mariadb", "redis"]}`, auto-sleeping `mariadb`/`redis` only when all dependents are sleeping!).
- Implement single-flight per-service `asyncio`/thread-safe `wake_service_sync(service, docker_client, timeout_sec)` with per-container `threading.Lock` so concurrent browser asset requests don't race `start()`/`unpause()`, plus TCP readiness check (`socket.create_connection`).
- TDD: Write tests verifying per-container independent sleep (active container stays up while idle one sleeps), shared DB `mariadb`/`redis` sleep/wake dependency ordering, and global server idle sleep until next request.

### Task 2: Ultralight Async TCP & HTTP Wake-Proxy (`app.py` + `docker-compose.yml`)
- Implement `WakeProxyManager` using `asyncio.start_server` inside FastAPI `lifespan` binding configurable ports (`WAKE_PROXY_PORTS`, e.g., `nextcloud:8081->nextcloud:80`, `navidrome:4533->navidrome:4533`, `maloja:42010->maloja:42010`, `samba:445->samba:445`) with graceful `OSError` handling if disabled/in-use.
- Add `touch_server_request()` middleware skipping `X-Background-Poll: 1` headers so open idle tabs don't prevent sleep.
- Add HTTP route `/svc/{service}/{path:path}` forwarding/waking over HTTP as well.
- Update `docker-compose.yml` so `admin-dashboard` owns `8081`, `4533`, `42010`, `445` host ports while `nextcloud`, `navidrome`, `maloja`, `samba` use `expose:`.
- TDD: End-to-end local socket test binding ephemeral TCP backend + ephemeral wake-proxy port, putting mocked container to sleep, connecting a raw client socket to the proxy, asserting container wakes AND request/response bytes round-trip transparently!

### Task 3: Dashboard UI & Live Per-Container Idle View (`dashboard.html`) + Full Verification
- Tag background `setInterval` fetches with `X-Background-Poll: 1`.
- Enhance `#s-power` Auto Sleep card to configure `Per-Container Idle (min)` + `Entire Server Idle (min)` + `Wake Scope` AND display live per-container idle timers + sleeping badges cleanly.
- Update `tests/test_optimization_updates.py` UI & integration tests, run full `pytest`, `node --check`, `py_compile`, `docker compose config --quiet`, leak scan, and clean caches.
