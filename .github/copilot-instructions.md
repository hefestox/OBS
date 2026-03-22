# GitHub Copilot Instructions for OBS Pro Bot

This is a Python/Streamlit trading bot for cryptocurrency operations on exchanges supported by `ccxt`. Follow these guidelines to ensure code consistency and stability.

## 🏗 Project Architecture

- **Entry point**: `dashboard.py` — serves both the Streamlit web UI (`streamlit run dashboard.py`) and the bot loop (`python dashboard.py --bot`).
- **Session/cookie management**: `CookieManager.py` — wraps `extra-streamlit-components` with a cloud-safe fallback.
- **Persistence**: SQLite via the standard `sqlite3` module. Database file is configurable via the `DB_PATH` environment variable (default: `mvp_funds.db`).
- **No separate modules directory**: all application logic lives in `dashboard.py` for now; extract to modules only when the file becomes unmanageable.

## 🛡 Critical Patterns & Conventions

### 1. Configuration constants
All tunable parameters are declared once at the top of `dashboard.py` in the `★ CONFIG` section:
- Trading pairs: `ALL_SYMBOLS`, `BOT_SYMBOLS`
- Risk parameters: `TAKE_PROFIT`, `STOP_LOSS`, `BANCA_FRAC_POR_PAR`
- Indicator settings: `RSI_PERIOD`, `EMA_FAST`, `EMA_SLOW`, `EMA_TREND`
- Timing: `BOT_LOOP_INTERVAL`, `COOLDOWN_AFTER_SL`, `MIN_HOLD_SECONDS`

Never hard-code these values elsewhere; always reference the constant.

### 2. Database access
- All SQLite writes must acquire `_DB_LOCK` (a `threading.Lock`) before executing.
- Never run raw SQL from outside a dedicated helper function.
- Environment variable `DB_PATH` overrides the default path; always read it via `os.environ.get("DB_PATH", DB_PATH)`.

### 3. Exchange integration
- Uses `ccxt` for all exchange communication.
- The exchange object is **cached** to avoid `MemoryError` on frequent re-instantiation (introduced in v5.0.0).
- Wrap every exchange call in a `try/except` and log failures; never let an exception crash the bot loop.

### 4. Session & authentication
- Session state is managed via `st.session_state` (`user` key).
- `CookieManager.py` provides `do_login` / `do_logout`; import and use these helpers instead of writing directly to `st.session_state`.
- Secrets (`SESSION_SECRET`, `DEFAULT_ADMIN_PASS`) must be injected via environment variables — never committed to the repository.

### 5. Logging
- Use the rotating file handler (`logging.handlers.RotatingFileHandler`, 5 MB max) configured in `dashboard.py`.
- Log file path is configurable via `BOT_LOG_PATH` environment variable.
- Use `logging.getLogger(__name__)` in any new module.

## 🛠 Development Workflow

### Running the project locally
```bash
# Web UI
streamlit run dashboard.py --server.address=0.0.0.0 --server.port=8501

# Bot loop only
python dashboard.py --bot
```

### Docker (local dev)
Services are defined in `docker-compose.yml`:
- `web` — Streamlit UI on port 8501
- `bot` — headless bot loop

```bash
cp .env.example .env   # fill in required secrets
docker compose up -d
docker compose logs -f bot
```

### Docker Swarm (production)
Use `docker-stack.yml`. Deploy via Portainer or:
```bash
docker stack deploy -c docker-stack.yml obs
```
The image is published to `ghcr.io/hefestox/obs`.

### Testing
- Write tests with `pytest` (plain Python, no framework-specific runner needed).
- Place test files in a `tests/` directory at the root.
- Every bug fix must ship with a regression test.
- CI (`main.yml`) runs `python -m py_compile` on all modules; keep syntax valid at all times.

## 📦 Key Dependencies
- `streamlit`: Web UI framework.
- `ccxt`: Cryptocurrency exchange integration.
- `pandas`: OHLCV data manipulation and indicator calculation.
- `requests`: HTTP calls (webhooks, external APIs).
- `extra-streamlit-components`: Cookie-based session persistence (optional, cloud-safe fallback in `CookieManager.py`).
- `psycopg2-binary`: Available but not used by default (reserved for future PostgreSQL migration).
- `streamlit-autorefresh`: Auto-refresh component for live dashboard updates.
