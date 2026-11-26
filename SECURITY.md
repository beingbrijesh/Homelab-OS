# Security Policy & Vulnerability Disclosure

Security and defense-in-depth are foundational principles of **Homelab OS**. This document outlines our supported versions, vulnerability reporting process, and baseline threat mitigation architecture.

---

## 🛡️ 1. Supported Versions

Security updates, hotfixes, and patch releases are provided for the following versions:

| Version | Supported | Status |
| :--- | :---: | :--- |
| **2.x (Current)** | ✅ Yes | Actively maintained; receives security advisories and patches. |
| **1.x** | ❌ No | Deprecated; users are advised to upgrade to v2.x immediately. |

---

## 🔒 2. Reporting a Vulnerability

We appreciate the efforts of security researchers and community members who practice responsible disclosure.

If you identify a security vulnerability in Homelab OS:

1. **Do NOT report security vulnerabilities via public GitHub issues.**
2. Use **GitHub Security Advisories**: Navigate to the [Homelab-OS Security Advisories](https://github.com/beingbrijesh/Homelab-OS/security/advisories) tab and click **New Draft Advisory**.
3. Alternatively, report the issue directly via encrypted email to:
   * **Maintainer Contact:** `brijeshy9653@gmail.com`
   * **Subject:** `[SECURITY] Homelab OS Vulnerability Disclosure`

### What to Include in Your Report

To help us triage and patch the issue promptly, please include:
* Description of the vulnerability and its potential impact.
* Exact version or commit SHA affected.
* Step-by-step reproduction instructions or a minimal Proof of Concept (PoC).
* Any suggested remediations or workarounds.

---

## ⏱️ 3. Response Timelines

* **Acknowledgment:** Within **48 hours** of receiving your report.
* **Triage & Assessment:** Within **5 business days**, confirming severity and scope.
* **Fix & Release:** Critical vulnerabilities are prioritized for release within **14 business days**.
* **Public Disclosure:** Coordinated disclosure will occur following the release of the patched version.

---

## 🏰 4. Security Architecture & Threat Mitigation

Homelab OS incorporates several layers of defense:

1. **Password Hashing:**
   - All administrator and user passwords in the control plane are hashed using **`scrypt`** ($N=16384, r=8, p=1$) with a unique 16-byte cryptographically secure salt.
   - Legacy SHA-256 hashes from older installations are transparently upgraded upon valid login.

2. **Automated Brute-Force Protection (Fail2ban):**
   - 3 consecutive failed login attempts from an IP address trigger an automated **30-minute block** stored in the database.
   - Administrators can manage, view, or release blocked IPs from the **Security** tab in the dashboard.

3. **Cloudflare Zero Trust Middleware:**
   - When enabled via `CLOUDFLARE_ZERO_TRUST_ENABLED=true`, the dashboard enforces cryptographic validation of the `Cf-Access-Authenticated-User-Email` header, cross-referencing against authorized accounts in `ALLOWED_ZERO_TRUST_EMAILS`.
   - Private LAN (`192.168.0.0/16`, `10.0.0.0/8`) and Tailscale (`100.64.0.0/10`) ranges are permitted direct access.

4. **Secrets Management:**
   - Real passwords and cryptographic keys are strictly confined to the host `.env` file, which is ignored in version control (`.gitignore`).
   - Only `.env.example` with sanitized placeholders is tracked in the repository.

5. **Container Privilege Isolation:**
   - Media storage mounts for Navidrome and Maloja are mounted **read-only** (`:ro`) to prevent accidental or malicious destruction of audio files.
