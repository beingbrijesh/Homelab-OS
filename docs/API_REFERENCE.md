# Homelab OS: REST API Contract Reference

The Homelab OS Control Plane exposes a high-performance, asynchronous REST API powered by FastAPI.

* **Base URL:** `http://<HOST_IP>:5001`
* **Interactive OpenAPI (Swagger) UI:** `http://<HOST_IP>:5001/docs`
* **Alternative ReDoc UI:** `http://<HOST_IP>:5001/redoc`

---

## 🔒 1. Authentication & Session Management

Authentication is managed via signed Starlette session cookies. Both form-encoded and raw JSON payloads are accepted.

### 1.1 Login

* **Endpoint:** `POST /login`
* **Request Format:** `application/json` or `application/x-www-form-urlencoded`
* **Request Body:**
  ```json
  {
    "username": "admin",
    "password": "your-secure-password"
  }
  ```
* **Responses:**
  - `200 OK` (JSON Client): `{"ok": true, "username": "admin"}` with `Set-Cookie: session=...; HttpOnly; SameSite=lax`
  - `303 See Other` (Form Submission): Redirects to `/dashboard`.
  - `401 Unauthorized`: `{"error": "Invalid username or password"}`

> [!NOTE]
> **Dual-Hash Transparent Password Migration:** If an existing account uses legacy SHA-256 password hashing, upon successful authentication the system automatically upgrades the hash to `scrypt` with a cryptographically secure 16-byte salt without requiring a password reset.

### 1.2 Current Session Profile

* **Endpoint:** `GET /api/auth/me`
* **Headers:** `Cookie: session=...`
* **Response `200 OK`:**
  ```json
  {
    "authenticated": true,
    "username": "admin"
  }
  ```

### 1.3 Logout

* **Endpoint:** `POST /logout`
* **Response `200 OK`:** Clears session cookie and returns `{"ok": true}`.

---

## 🖥️ 2. Container & Resource Telemetry

### 2.1 List All Containers

* **Endpoint:** `GET /api/containers`
* **Response `200 OK`:**
  ```json
  [
    {
      "name": "nextcloud",
      "status": "running",
      "health": "healthy",
      "image": "nextcloud:33-apache",
      "memory_mb": 218.4,
      "memory_limit_mb": 512.0,
      "cpu_pct": 0.8,
      "uptime": "2 days"
    }
  ]
  ```

### 2.2 Container Lifecycle Control

* **Endpoint:** `POST /api/containers/{name}/{action}`
* **Path Parameters:**
  - `name`: Target container (e.g. `pihole`, `navidrome`, `samba`).
  - `action`: `start`, `stop`, or `restart`.
* **Response `200 OK`:**
  ```json
  {
    "ok": true,
    "message": "Container nextcloud restarted successfully"
  }
  ```

### 2.3 Real-Time Hardware Metrics

* **Endpoint:** `GET /api/resources/metrics`
* **Response `200 OK`:**
  ```json
  {
    "cpu": {
      "usage_pct": 4.2,
      "cores": 4,
      "temperatures_c": [42.0, 44.5]
    },
    "memory": {
      "total_mb": 8192,
      "used_mb": 2240,
      "free_mb": 1100,
      "cached_mb": 4852,
      "usage_pct": 27.3
    },
    "disk": {
      "total_gb": 480.0,
      "used_gb": 128.4,
      "free_gb": 351.6,
      "usage_pct": 26.7
    },
    "network": {
      "active_interface": "wlp2s0",
      "rx_bytes_sec": 14200,
      "tx_bytes_sec": 38100,
      "available_interfaces": ["wlp2s0", "enp4s0", "tailscale0"]
    },
    "eco_sleep": {
      "active": false,
      "idle_minutes": 12,
      "containers_sleeping": 0
    }
  }
  ```

---

## 🔔 3. System Events & Log Harvesting

The system log harvester deduplicates repetitive lines and bursts across all containers within a 10-minute sliding window.

### 3.1 Fetch System Events

* **Endpoint:** `GET /api/system-events`
* **Query Parameters:**
  - `unresolved` (integer, optional): `1` to fetch only unresolved events.
* **Response `200 OK`:**
  ```json
  [
    {
      "id": 42,
      "event_type": "high_cpu",
      "severity": "warning",
      "message": "CPU temperature exceeded 75°C (current: 78.2°C)",
      "occurrence_count": 3,
      "resolved": 0,
      "first_seen": "2026-11-26T08:00:00Z",
      "last_seen": "2026-11-26T08:14:22Z"
    }
  ]
  ```

### 3.2 Resolve an Event

* **Endpoint:** `POST /api/system-events/{eid}/resolve`
* **Response `200 OK`:** `{"ok": true, "resolved_id": 42}`

### 3.3 Resolve All Events

* **Endpoint:** `POST /api/system-events/resolve-all`
* **Response `200 OK`:** `{"ok": true, "resolved_count": 5}`

---

## 🔄 4. Zero-Downtime Updates & Snapshots

### 4.1 Check Registry Versions

* **Endpoint:** `GET /api/updates/check`
* **Response `200 OK`:**
  ```json
  {
    "updates_available": true,
    "services": [
      {
        "name": "nextcloud",
        "current_image": "nextcloud:33-apache",
        "update_available": true,
        "latest_digest": "sha256:abc1234..."
      }
    ]
  }
  ```

### 4.2 Trigger Service Update

* **Endpoint:** `POST /api/updates/trigger`
* **Request Body:**
  ```json
  {
    "target": "nextcloud"
  }
  ```
  *(Pass `"target": "all"` to perform a staged sequential update across the full stack).*
* **Response `200 OK`:** `{"ok": true, "job_id": 105, "status": "queued"}`

### 4.3 Cancel In-Progress Update

* **Endpoint:** `POST /api/updates/{jid}/cancel`
* **Response `200 OK`:** `{"ok": true, "status": "cancelled"}`

### 4.4 Trigger Instant Atomic Backup

* **Endpoint:** `POST /api/backups/create`
* **Response `200 OK`:**
  ```json
  {
    "ok": true,
    "snapshot_path": "/storage/snapshots/20261126_130000",
    "status": "Backup completed successfully"
  }
  ```

---

## 🎧 5. Media & Audio Download Engine

### 5.1 Enqueue Audio Download

* **Endpoint:** `POST /api/music/download`
* **Request Body:**
  ```json
  {
    "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
    "format": "flac",
    "quality": "best_lossless"
  }
  ```
  *Allowed Formats:* `flac`, `opus`, `mp3`, `m4a`, `wav`.
* **Response `200 OK`:**
  ```json
  {
    "ok": true,
    "job_id": 78,
    "format": "flac",
    "title": "Resolving metadata..."
  }
  ```

### 5.2 Cancel Audio Download

* **Endpoint:** `POST /api/music/queue/{jid}/cancel`
* **Behavior:** Terminates active `yt-dlp` or `ffmpeg` child processes cross-platform via `psutil` and marks job state as `cancelled`.
* **Response `200 OK`:** `{"ok": true}`
