# Aero-Astra — Development Makefile
# Usage:
#   make setup       First-time setup: install deps + train model
#   make train       Retrain the SENTINEL XGBoost model
#   make run         Start the backend API server
#   make dev         Start the frontend dev server
#   make check       Validate model file is not an LFS stub

.PHONY: setup train run dev check

PYTHON   = python
SENTINEL = backend/sentinel
MODELS   = backend/models

# ─────────────────────────────────────────────────────────────────────────────
# First-time setup
# ─────────────────────────────────────────────────────────────────────────────
setup: _install_deps train
	@echo ""
	@echo "✅  Setup complete. Run 'make run' to start the backend."

_install_deps:
	@echo "→ Installing Python dependencies..."
	pip install -r backend/requirements.txt

# ─────────────────────────────────────────────────────────────────────────────
# Model training
# ─────────────────────────────────────────────────────────────────────────────
train: check_data
	@echo "→ Training SENTINEL XGBoost model..."
	cd $(SENTINEL) && $(PYTHON) train.py
	@echo "✅  Model saved to $(MODELS)/sentinel_production.pkl"

check_data:
	@test -f backend/data/raw/opssat/dataset.csv || \
		(echo "❌  Missing: backend/data/raw/opssat/dataset.csv" && \
		 echo "    This file is excluded from git (large dataset)." && \
		 echo "    Download from: https://zenodo.org/record/5167082" && exit 1)

# ─────────────────────────────────────────────────────────────────────────────
# Runtime
# ─────────────────────────────────────────────────────────────────────────────
run: check
	@echo "→ Starting backend API on http://localhost:8000 ..."
	cd backend && $(PYTHON) api.py

dev:
	@echo "→ Starting frontend dev server on http://localhost:5173 ..."
	npm run dev

# ─────────────────────────────────────────────────────────────────────────────
# Model health check (detects Git LFS pointer stubs)
# ─────────────────────────────────────────────────────────────────────────────
check:
	@$(PYTHON) -c "\
from pathlib import Path; \
p = Path('backend/models/sentinel_production.pkl'); \
ok = p.exists() and p.stat().st_size > 512 and not p.read_bytes()[:36].decode('utf-8','ignore').startswith('version https://git-lfs'); \
print('✅  Model OK') if ok else (print('❌  Model missing or corrupt. Run: make train') or exit(1))"
