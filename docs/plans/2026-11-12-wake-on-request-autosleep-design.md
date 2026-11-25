# Per-Container & Server-Wide Wake-on-Request Auto-Sleep Design

**Date:** 2026-11-12
**Status:** Approved (`A1` Async TCP/HTTP Wake-Proxy + `A2` Full-Stack Eco-Sleep)

## Architecture Overview

To achieve true **Scale-to-Zero / Wake-on-Next-Request** with **zero extra containers** on 2-core Celeron / 8GB RAM hardware, the existing `admin-dashboard` process hosts an ultralight `asyncio` TCP/HTTP Wake-Proxy inside its single FastAPI event loop:

1. **Always-Awake Control Plane & Wake Listeners (`~45MB` total):**
   - `pihole` stays awake for `<5ms` DNS.
   - `admin-dashboard` stays awake on `:5001` AND binds lightweight `asyncio.start_server` forwarders on the service ports (`8081` → `nextcloud:80`, `4533` → `navidrome:4533`, `42010` → `maloja:42010`, `445` → `samba:445`) plus HTTP route `/svc/{service}/{path:path}`.
   - In `docker-compose.yml`, `nextcloud`, `navidrome`, `maloja`, and `samba` use `expose:` inside the `homelab` Docker network while `admin-dashboard` publishes `8081`, `4533`, `42010`, and `445:445` (configurable via env/UI).

2. **Two-Level Idle Detection & Sleep:**
   - **Per-Container Idle Sleep (`container_idle_minutes`, default `15`):**
     Each service has an independent `last_request_ts[service]` updated on every proxied connection/request or significant (`> 4 KB`) container network transfer. When a single container has zero requests for `container_idle_minutes`, ONLY that container is put to sleep (`stop` or `pause`), along with internal dependencies (`mariadb`, `redis`) when no awake dependent service (`nextcloud`) needs them.
   - **Entire Homelab Server Idle Sleep (`server_idle_minutes`, default `30`):**
     Tracks global `server_last_request_ts` across all services and explicit user dashboard actions (automatic background UI `setInterval` polls carry `X-Background-Poll: 1` so an idle open browser tab does NOT block sleep). When the entire homelab sees zero requests for `server_idle_minutes` (and no active download/update/backup), all remaining sleep targets enter Full-Stack Eco-Sleep and host memory is compacted.

3. **Transparent Wake-on-Next-Request:**
   - Any incoming TCP SYN or HTTP request to a sleeping service (`:8081`, `:4533`, `:42010`, `:445`, or `/svc/{service}`) is held open by `asyncio`, triggers single-flight wake for that service + dependencies (`mariadb` → `redis` → `nextcloud`), polls internal TCP readiness, and splices the byte stream seamlessly without dropping the client's first request.
   - Configurable policy: wake requested service + dependencies only (default, minimum RAM) OR wake entire stack when waking from server-wide sleep.
