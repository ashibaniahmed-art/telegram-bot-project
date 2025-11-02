This repository is a small Telegram bot for managing service requests and coupon codes.

Key facts the AI agent should know (quick):

- Main entry: `bot.py` (root). This file contains most runtime logic: DB init/migrations, command handlers (async), and message routing.
- DB: an SQLite file `data.db` lives alongside `bot.py`. Schema is created/updated in `init_db()` inside `bot.py`.
- Coupons: `coupons` table stores codes (unique). Coupon tooling lives in `generate_coupons.py` (creates coupons and writes a `coupons_<amount>_<timestamp>.txt`). Use `check_coupon.py` and `check_db_coupons.py` to inspect/search the DB.
- Environment: secrets and runtime flags are loaded via `python-dotenv` (call to `load_dotenv()` in `bot.py`). Required env vars: `BOT_TOKEN`, `DATA_ENC_KEY`. Optional: `ADMIN_USER_ID` (for admin panel access).
- Dependencies: pinned in `requirements.txt` (notably `python-telegram-bot==20.0`, `python-dotenv`, `requests`).

Project structure & where to change things:

- `bot.py` — primary location for behavior. Handlers (e.g. `redeem_cmd`, `start`, `handle_buttons`) are defined inline and use `sqlite3` directly. New simple handlers may be added here or imported from `src/handlers/`.
- `src/handlers/` — intended place for modular handlers; currently `__init__.py` is empty. If moving logic out of `bot.py`, keep the same async handler signatures: async fn(update: Update, context: ContextTypes.DEFAULT_TYPE).
- `src/utils/` — utilities (currently empty). Use this for small helpers to avoid duplicating DB or formatting logic.
- `generate_coupons.py` — CLI to create coupon records and dump them to a text file.
- `create_db.py` — minimal DB bootstrap (can be run once if `data.db` is missing).

Important runtime patterns and conventions (do not change without checking):

- Strings and keyboard labels are Arabic; text matching often uses lowercased Arabic tokens and small token sets like `SERVICE_KEYS`, `CONTACT_KEYS`, `ABOUT_KEYS` in `bot.py` — preserve these when adding menu text or new shortcuts.
- In-memory state: `user_states` is a process-global dict used for multi-step interactions. Handlers set `user_states[user_id] = {...}` and then subsequent messages read/update it. Keep state keys consistent (e.g. `role`, `step`, `name`, `phone`, `location`).
- DB access: code uses raw `sqlite3` connections per operation (blocking). Handlers are async but call blocking DB functions — follow existing pattern (open connection, execute, commit, close) when editing DB code.
- DB migrations: `init_db()` includes a safe helper `add_column_if_not_exists(conn, table, column_def)` used to add missing columns. When adding new columns, mimic this pattern instead of recreating tables.
- Coupon uniqueness: coupons are `UNIQUE` in the `coupons` table; insertion may raise on duplicates. `generate_coupons.py` handles duplicates by skipping and continuing.

Developer workflows and commands (what works locally):

- Create venv + install deps (Windows cmd):
  venv\Scripts\activate
  python -m pip install -r requirements.txt
- Run the bot (after adding `.env` with BOT_TOKEN and DATA_ENC_KEY):
  python bot.py
- DB utilities:
  - Create DB schema: `python create_db.py` (creates `data.db` with basic tables)
  - Generate coupons: `python generate_coupons.py --amount 60 --count 100` (writes `coupons_60_<ts>.txt` and inserts into DB)
  - Inspect coupons: `python check_db_coupons.py` or `python check_db_coupons.py <code1> <code2>`

Testing, debugging, and logs:

- Logging: `logging` is configured in `bot.py` (INFO). For debugging change level at top of `bot.py`.
- Admin panel: controlled by `ADMIN_USER_ID` env var; the admin handler `send_admin_panel` fetches subscribers and worker lists.
- Windows specifics: `bot.py` conditionally sets WindowsSelectorEventLoopPolicy for older Python versions — be careful when changing asyncio behavior.

Examples to reference when making changes:

- Add an async handler: follow the `redeem_cmd` function signature and registration style inside `bot.py`.
- DB migration example: use `add_column_if_not_exists(conn, "workers", "appearance_count INTEGER DEFAULT 0")` as done in `init_db()`.

Files to read first when editing behavior:

- `bot.py` — core logic and handlers
- `generate_coupons.py`, `create_db.py`, `check_coupon.py`, `check_db_coupons.py` — scripts that operate on `data.db`
- `requirements.txt` — dependency versions

When in doubt:

- Preserve the Arabic UI text and keyboard shapes unless asked to change UX.
- Preserve DB schema and migration pattern; changing table/column names requires migration and careful updates to all queries.

If you need clarifications (e.g., where tokens come from, expected DB upgrade path, or intended handler split), ask the repo owner for the preferred location to host new handlers (root `bot.py` vs `src/handlers/`).

---
Last scanned files used to build this doc: `bot.py`, `generate_coupons.py`, `create_db.py`, `check_coupon.py`, `check_db_coupons.py`, `requirements.txt`, `README.md`.

Please review and tell me if you'd like different emphasis (tests, CI, or handler refactor examples).
