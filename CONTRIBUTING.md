# Contributing to Homelab OS

We welcome community contributions! Please adhere to the following guidelines to ensure stability, hardware efficiency, and zero regressions.

---

## 🎯 Guiding Principles

1. **Low-Spec Hardware Priority:** Any feature added must run comfortably on a dual-core Intel Celeron with 8GB RAM without increasing idle container memory above 2.5GB.
2. **Zero-AI Footprint:** Homelab OS is strictly designed for deterministic self-hosting services (cloud, files, DNS, media). Do not bundle LLMs or AI daemons into default compose configurations.
3. **API Contract Compatibility:** The frontend `dashboard.html` interface depends on frozen API response schemas. Any modification to endpoint responses must pass `tests/test_api_contracts.py`.

---

## 🛠️ Development Setup

1. Fork and clone the repository.
2. Install test dependencies:
   ```bash
   pip3 install fastapi uvicorn starlette pydantic pytest httpx psutil
   ```
3. Run the test suite:
   ```bash
   python3 -m pytest tests/test_api_contracts.py -v
   ```
4. Start the development server:
   ```bash
   cd admin-dashboard
   python3 -m uvicorn app:app --port 5001 --reload
   ```

---

## 📝 Pull Request Checklist

- [ ] All `pytest` tests pass with zero errors and zero warnings.
- [ ] No hardcoded passwords, IP addresses, or secrets committed.
- [ ] Documentation updated in `README.md` and `ARCHITECTURE.md` if behavior changes.
