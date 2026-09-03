# Romantika Marshrutov v2 — Architecture Contract

Status: binding contract for the rewrite (2026-09-03). Implementers follow this document;
deviations are proposed in the stage report, not silently applied.

## 1. Goal

One Telegram bot (`@romantika_marshrutov_bot`, same token as before) plus several Telegram
Mini Apps served by our own backend, with all participant data and photos stored on our VPS,
verified backups, an admin UI for season content, and a PDF season journal.

Product semantics (what a season, week, report, stamp, freeze, level, achievement mean) are
defined in `docs/DOMAIN.md` and are the same as in `legacy/` unless DOMAIN.md says otherwise.
Legacy code is reference only; never import it.

## 2. Non‑negotiables

- Python 3.12, `uv`, `ruff`, `mypy --strict`-ish (see pyproject), `pytest`. No other build
  systems, no Node build step (npm is unreachable from the RU datacenter; front-end is plain
  HTML/CSS/JS served by FastAPI).
- All identifiers, comments, commit messages and developer docs in English. User-facing
  texts (bot messages, Mini App UI, PDF) are Russian and live in `romantika/texts/*.py` or
  templates — never inline inside handlers.
- Postgres 16 is the only database. SQLAlchemy 2.0 (async, `asyncpg`), Alembic migrations.
  No raw positional `INSERT ... VALUES` without column lists anywhere.
- Media files are immutable. Nothing in the codebase deletes a media file or a report row;
  "removal" is `hidden_at`/`deleted_at` timestamps. Backups verify that.
- Time: store UTC `timestamptz` in DB; business calendar is `Europe/Moscow` (`zoneinfo`,
  `tzdata` is installed in the image). Never `datetime.now()` without tz.
- Every external call (Telegram API, filesystem, DB) is behind a service function; handlers
  and routes contain no business logic.
- Telegram message length: any outgoing text goes through `romantika.bot.send.split_text`
  (4096-char safe splitting). Errors from Telegram are logged with context, never swallowed.
- Secrets only from environment (`.env` in deployment, never committed). `ADMIN_IDS` is a
  comma-separated list.

## 3. Repository layout

```
romantika/                 package (installed, `romantika` on sys.path)
  config.py                Settings (pydantic-settings): BOT_TOKEN, ADMIN_IDS, DATABASE_URL,
                           MEDIA_DIR, PUBLIC_BASE_URL, ADMIN_CHAT_ID (optional), LOG_LEVEL
  logging.py               structured logging setup (stdlib logging, JSON in prod)
  db/
    base.py                Declarative Base, naming conventions
    models.py              all ORM models (section 4)
    session.py             engine + async_sessionmaker factory `make_session_factory(url)`
    migrations/            alembic (env.py async, versions/)
  domain/                  PURE functions, no IO, fully unit-tested
    calendar.py            moscow_now(), moscow_today(), week_for(date, weeks), julian_day()
    rules.py               report_level(), levels, season_breakdown(), streaks, core
    tzolkin.py             tzolkin_day(date) -> TzolkinDay (data from data/tzolkin.json)
    types.py               dataclasses/enums used by domain (WeekState, Breakdown, ...)
  services/                use-cases; take an AsyncSession (+ optional gateways), return DTOs
    content.py             seasons/weeks/achievement types read + admin edits (audit log)
    people.py              upsert user, membership in season, dialog state
    reports.py             accept report (+media metadata), cancel, fix level
    media.py               MediaStore: download from Telegram to MEDIA_DIR, sha256, dedupe
    stamps.py              award/upgrade stamp, admin override
    freezes.py             grant (auto/manual), totals
    achievements.py        award/list
    words.py, facts.py, wishes.py
    passport.py            passport view model (breakdown + texts)
    journal.py             journal view model (for bot text, Mini App and PDF)
    summary.py             weekly summary, core, draft post, reminder recipients
    jobs.py                enqueue/claim/finish jobs
    seed.py                import season JSON (data/seasons/*.json) into DB
  texts/                   Russian strings/templates for the bot (greeting, help, buttons ...)
  bot/                     aiogram 3: `create_dispatcher(settings, session_factory, media_store)`
    routers/               user.py, reports.py, admin.py, callbacks.py
    keyboards.py, send.py (split_text, safe_send), middlewares.py (db session, user upsert)
    main.py                polling entrypoint `python -m romantika.bot`
  web/                     FastAPI: `create_app(settings, session_factory, media_store)`
    auth.py                Telegram initData validation (HMAC-SHA256), `CurrentUser` dependency
    routes/                public.py (/, /calendar), api.py (/api/...), admin_api.py, media.py
    templates/             Jinja2: public season page, calendar, miniapp shells
    static/                css/js for Mini Apps (vanilla, no build)
    main.py                `python -m romantika.web` (uvicorn)
  worker/                  `python -m romantika.worker`: job loop + schedulers (reminders,
                           backups verification alerts)
  pdf/                     journal HTML template + WeasyPrint renderer `render_journal_pdf()`
  migration/               legacy_import.py: legacy SQLite + file_id download -> Postgres/media
data/
  tzolkin.json             single source of truth: {"correlation": 584283,
                           "signs": [20 × {name (simple spelling «Ик»), name_academic («Ик'»),
                           latin, emoji, symbol, meaning, destiny, short, day_advice}],
                           "tones": [13 × {number, name, text}]} — merged from legacy bot
                           (ЗНАКИ_ЦОЛЬКИНА: symbol/day_advice) and Mini App (SIGNS/TONES)
  seasons/mexico-2026.json season content seed (legacy сезон.json, same keys)
docker/                    Dockerfile (one image, 3 commands), compose.yml, compose.vps.yml
scripts/                   backup.sh, restore-verify.sh, mac-pull-backups.sh, deploy.sh, ...
tests/
  acceptance/              READ-ONLY for implementers (written by the orchestrator per stage)
  unit/  integration/      written by implementers
  conftest.py              Postgres fixture: TEST_DATABASE_URL env or testcontainers-postgres
docs/                      ARCHITECTURE.md (this), DOMAIN.md, RUNBOOK.md, GUIDE-RU.md
legacy/                    old code, reference only
```

## 4. Data model (Postgres, SQLAlchemy models in `romantika/db/models.py`)

Naming: snake_case tables, `id` PKs, `created_at timestamptz default now()` everywhere,
`bigint` for Telegram ids. Enums are Python `enum.StrEnum` stored as `text` with a CHECK.

| Table | Columns (besides id/created_at) | Notes |
|---|---|---|
| `users` | `id bigint PK` (telegram id), `username`, `first_name`, `last_name`, `is_admin bool`, `joined_at timestamptz`, `blocked_at timestamptz null` | joined_at = first contact, never updated |
| `seasons` | `slug unique`, `title`, `title_accusative` (e.g. «Мексику»), `hashtag`, `starts_on date`, `ends_on date`, `status` (`draft/active/archived`), `daily_kind null` (`tzolkin`), `daily_title`, `daily_note`, `base_freezes int=2`, `max_freezes int=5`, `level_tourist int=1`, `level_traveler int=4`, `level_resident int=9`, `journal_promise_on date null` | exactly one `active` at a time (partial unique index) |
| `weeks` | `season_id FK`, `number int`, `title`, `starts_on`, `ends_on`, `intro`, `task_min`, `task_max`, `word`, `word_ru`, `word_meaning` | unique(season_id, number); weeks may not overlap inside a season |
| `achievement_types` | `season_id FK`, `code`, `emoji`, `name`, `description`, `sort int` | unique(season_id, code) |
| `season_members` | `season_id`, `user_id`, `joined_at` | PK(season_id,user_id); created on first contact during season |
| `intents` | `season_id`, `user_id`, `week_id`, `choice` (`take/try/skip`), `updated_at` | unique(user_id, week_id) |
| `reports` | `season_id`, `user_id`, `week_id`, `kind` (`text/photo/video/video_note/document/voice/audio/other`), `text`, `level` (`min/max`), `tg_chat_id`, `tg_message_id`, `deleted_at null` | full history, never physically deleted |
| `media` | `id uuid`, `report_id FK`, `tg_file_id`, `tg_file_unique_id`, `mime`, `size int`, `width null`, `height null`, `sha256`, `path` (relative to MEDIA_DIR), `downloaded_at null`, `hidden_at null` | `path` = `<season_slug>/<user_id>/<uuid>.<ext>` |
| `stamps` | `season_id`, `user_id`, `week_id`, `level` (`min/max`), `week_title_snapshot`, `awarded_at`, `source` (`report/admin`) | unique(user_id, week_id) |
| `freezes` | `season_id`, `user_id`, `reason` (`word/max/comment/meetup/friend/manual`), `granted_by null`, `note null` | bonus freezes only; base freezes are a season constant |
| `achievements` | `season_id`, `user_id`, `code`, `label`, `awarded_by`, `awarded_at` | unique(season_id, user_id, code) |
| `words` | `season_id`, `user_id`, `week_id null`, `word`, `meaning` | meaning parsed from "word — meaning" (first ` — `, ` - `, `:`) |
| `facts` | `season_id`, `week_id null`, `text`, `author_id null`, `deleted_at null` | author null = admin |
| `wishes` | `season_id`, `user_id`, `text`, `updated_at` | unique(season_id,user_id) |
| `admin_links` | `admin_chat_id`, `admin_message_id`, `user_id`, `report_id null`, `week_id null` | reply-routing; PK(admin_chat_id, admin_message_id) |
| `dialog_states` | `user_id PK`, `state`, `payload jsonb`, `updated_at` | TTL 6h enforced in `people.get_dialog_state` |
| `settings` | `key PK`, `value text` | e.g. `reminders_enabled` |
| `reminder_log` | `key PK` (`YYYY-MM-DD:<slug>`), `sent_at`, `recipients int` | dedupe |
| `audit_log` | `actor_id`, `action`, `entity`, `entity_id`, `before jsonb`, `after jsonb` | every admin content edit |
| `jobs` | `kind`, `payload jsonb`, `status` (`queued/running/done/failed`), `attempts`, `run_after`, `started_at`, `finished_at`, `error` | claimed with `FOR UPDATE SKIP LOCKED` |

## 5. Domain rules (pure; `romantika/domain/rules.py`)

```python
def report_level(kind: ReportKind) -> StampLevel        # photo/video/video_note/document -> MAX, else MIN
def merge_level(existing: StampLevel | None, new: StampLevel) -> StampLevel   # MAX never downgrades
def season_breakdown(*, weeks: Sequence[WeekInfo], stamps: Mapping[int, StampLevel],
                     bonus_freezes: int, base_freezes: int, max_freezes: int,
                     joined_on: date, today: date) -> Breakdown
def level_for(stamps_count: int, freezes_left: int, cfg: LevelConfig) -> Level | None
def core_members(breakdowns: Mapping[int, Breakdown], min_streak: int = 2) -> list[int]
```

Types live in `romantika/domain/types.py`: `ReportKind`, `StampLevel` (`min`/`max`),
`WeekState`, `Level` (`tourist`/`traveler`/`resident`), `LevelConfig(tourist, traveler,
resident)`, `WeekInfo(number, title, starts_on, ends_on)`, `Breakdown(states: dict[int,
WeekState] keyed by week number, stamps, freezes_used, freezes_left, freezes_total,
best_streak, current_streak)`. All are `StrEnum`/frozen dataclasses.

`Breakdown` has per-week `WeekState` in {`locked`, `stamped`, `current`, `before_join`,
`frozen`, `missed`}. A `frozen`/`current`/`before_join` week keeps the streak unchanged,
`stamped` adds one, `missed` resets `current_streak` to 0. `core_members` returns user ids
with `stamps ≥ 1` and `best_streak ≥ min_streak`, sorted by `best_streak` desc then id asc.
Rules are exactly DOMAIN.md §3–§5 (ported from legacy `разбор_сезона`, `всего_заморозок`,
`УРОВНИ`, `ядро`). Russian names of levels live in `romantika/texts`.

`romantika/domain/tzolkin.py`: `tzolkin_day(d: date) -> TzolkinDay(number 1..13, sign: Sign,
kin 1..260)` with GMT correlation 584283 and the exact legacy formulas
(`number = ((x+3) % 13) + 1`, `sign_index = (x+19) % 20`, `x = jdn - 584283`).

## 6. Services (async; signature convention)

Every service function takes `session: AsyncSession` first, plain values next, and returns
DTOs (dataclasses in the same module) — never ORM instances across the boundary. Services
do not commit; the caller (middleware/route/job) commits. Side effects to Telegram happen in
gateways passed in (`TelegramGateway` protocol in `romantika/services/gateways.py`) so services
are testable without network.

Key flows:

- `reports.accept(session, *, user, message: IncomingMessage, now) -> AcceptResult` —
  finds active week (else stores an `other`-kind report with `week_id=None`, and result says
  `out_of_week=True`), creates report, media rows (not yet downloaded), awards/merges stamp
  via `stamps`, grants auto-freeze `max` on first MAX; returns texts to send + admin copy.
- `media.MediaStore.download(session, media_id, telegram)` — getFile + stream to
  `MEDIA_DIR/<path>.part` then atomic rename; sets sha256/size/downloaded_at; idempotent.
  Called inline by the bot right after `accept`; failure enqueues job `media_download`.
- `reports.fix_level(session, user, week_number, level)` — via `stamps.merge`, refuses to
  downgrade MAX (returns explanation), refuses when no report exists for the week.
- `stamps.admin_set(session, actor, user_id, week_number, level | None)` — override with audit.
- `passport.build(session, user, season, today)`, `journal.build(...)`, `summary.week(...)`,
  `summary.draft_post(...)`, `summary.reminder_recipients(...)`.
- `content.*` — admin CRUD for seasons/weeks/achievement types/facts with audit log;
  `content.active_season(session, today)`; `content.week_for(session, season, today)`.
- `seed.import_season(session, path)` — idempotent upsert by slug/number.

### 6.1 Service API (binding; mirrors `tests/acceptance/test_stage2_services.py`)

Time is always explicit: `now: datetime` (aware, UTC) or `today: date` (Moscow calendar day).
`romantika/services/gateways.py` defines the `TelegramGateway` protocol
(`get_file(file_id) -> TelegramFile(file_path, file_size)`, `download_file(file_path,
destination: Path)`, later stages add `send_message(chat_id, text)` and
`send_document(chat_id, path, caption)`); the bot provides an adapter over aiogram, tests use fakes.

| Module | Functions (all `async`, first arg `session`) |
|---|---|
| `people` | `upsert_user(session, tg: TelegramUser, *, now) -> UserDTO` (keeps first `joined_at`); `ensure_member(session, season_id, user_id, *, now) -> datetime` (returns existing `joined_at`); `set_dialog_state(session, user_id, state, payload=None, *, now)`, `get_dialog_state(session, user_id, *, now) -> DialogStateDTO | None` (TTL 6 h), `clear_dialog_state(session, user_id)`; `set_intent(session, *, season_id, user_id, week_id, choice: IntentChoice, now)` |
| `content` | `active_season(session, *, today) -> SeasonDTO | None`; `activate_season(session, season_id, *, actor_id)`; `weeks(session, season_id) -> list[WeekDTO]`; `current_week(session, season_id, *, today) -> WeekDTO | None`; `update_week(session, *, actor_id, week_id, changes: dict[str, str]) -> WeekDTO` (only title/intro/task_min/task_max/word/word_ru/word_meaning; audit row); `get_setting/set_setting(session, key, value)` |
| `reports` | `IncomingFile`, `IncomingMessage` dataclasses; `accept(session, *, season_id, user_id, message, now) -> AcceptResult(report_id, week_number, out_of_week, level, stamp_level, freeze_granted, media_ids)`; `fix_level(session, *, season_id, user_id, week_number, level, now) -> FixResult(ok, stamp_level, reason)`; `cancel(session, *, user_id, report_id, now) -> CancelResult(ok, stamp_level)` |
| `stamps` | `admin_set(session, *, actor_id, season_id, user_id, week_number, level: StampLevel | None, now) -> StampLevel | None` (audit row) |
| `freezes` | `grant(session, *, season_id, user_id, reason: FreezeReason, granted_by, now, note=None) -> bool`; `bonus_count(session, season_id, user_id) -> int` |
| `media` | `MediaStore(root: Path)`: `.root`, `download(session, media_id, telegram, *, now) -> MediaDTO(path, sha256, size)`; path `<season_slug>/<user_id>/<uuid>.<ext>`, `.part` + atomic rename, idempotent |
| `achievements` | `award(session, *, season_id, user_id, code_or_text, awarded_by, now) -> AwardResult(created, code, label)`; `labels(session, *, season_id, user_id) -> list[str]` |
| `words` | `add(session, *, season_id, user_id, week_id, raw, now) -> WordResult(word, meaning, freeze_granted)`; `season_dictionary(session, season_id, *, today) -> DictionaryView(week_words, user_words)` |
| `facts` | `add(session, *, season_id, week_id, text, author_id, now) -> int`; `list_active(session, season_id) -> list[FactDTO]`; `remove(session, *, fact_id, actor_id, now) -> bool` |
| `wishes` | `set_wish(session, *, season_id, user_id, text, now)`; `get_wish(session, season_id, user_id) -> str | None` |
| `passport` | `build(session, *, season_id, user_id, today) -> PassportView(breakdown, stamps_max, level, achievements, ...)` |
| `journal` | `build(session, *, season_id, user_id, today) -> JournalView(user, season, weeks: [JournalWeek(number, title, level, quote)], media: [JournalMedia(media_id, path)], achievements, words, facts, wish)` |
| `summary` | `week(session, *, season_id, week_number, today) -> WeekSummary(members_total, reports_total, took, submitted: dict[int, StampLevel], took_not_submitted, core_best, core_current)`; `reminder_recipients(session, *, season_id, week_number) -> list[int]`; `draft_post(...)` |
| `jobs` | `enqueue(session, kind, payload, *, now, run_after=None) -> int`; `claim(session, *, now) -> JobDTO | None` (`FOR UPDATE SKIP LOCKED`, respects `run_after`); `finish(session, job_id, *, error, now)` (error → requeue with exponential backoff, `failed` after 5 attempts) |

## 7. Bot (aiogram 3)

- Long polling (`allowed_updates=["message","callback_query"]`), `drop_pending_updates=False`.
  `deleteWebhook` at start.
- Middlewares: DB session per update (commit on success), user upsert + season membership.
- Reply keyboard and inline flows replicate legacy (DOMAIN.md §7): Задание / Сегодня /
  Паспорт / Словарь / Что узнали / Ещё / Помощь / Написать Миле, admin panel «⚙️».
  Button detection by normalized word (emoji-insensitive) as in legacy.
- Inline `web_app` buttons open the Mini Apps: journal (`{PUBLIC_BASE_URL}/app/journal`),
  calendar (`/calendar`), admin (`/app/admin`).
- Report intake accepts text, photo (largest size), video, video_note, document, voice,
  audio. Voice/audio = MIN level report with kind `voice/audio`. Stickers/other: reply
  «не поняла» text, nothing stored.
- Media download happens inline after accept; on failure user still gets the stamp, and a
  `media_download` job is queued.
- Out-of-week messages are stored (report with `week_id=None`, kind as received) AND copied
  to admin; reply says it was passed to Mila (legacy lied — fixed).
- Admin: reply-routing via `admin_links`, `/results`, `/core`, `/remind`, `/badges`,
  `/badge`, `/reminders`, `/who`, `/wish`, `/fact`, `/fact-` (Russian aliases kept:
  `/ачивка`, `/пожелание`, `/факт`, `/факт-`, `/факты`, `/журнал`).
- Reminders are NOT in the bot process; see worker.

## 8. Web (FastAPI)

- `GET /healthz` → `{"status":"ok","db":true}`.
- Public: `GET /` season page (SSR from DB; future weeks not in HTML), `GET /calendar`
  (tzolkin Mini App; signs embedded from data/tzolkin.json).
- Mini Apps: `GET /app/journal`, `GET /app/admin` (HTML shells; JS calls `/api`).
- Auth: header `X-Telegram-Init-Data` validated per Telegram docs (HMAC-SHA256 with
  `WebAppData` key, `auth_date` ≤ 24h). Dev bypass only when `settings.dev_auth_user_id` is
  set and `settings.env == "dev"`.
- API (JSON, all under `/api`, Pydantic schemas in `romantika/web/schemas.py`):
  `GET /api/me`, `GET /api/journal` (passport + weeks + reports + media urls + achievements +
  words + wishes), `POST /api/journal/pdf` (enqueue) / `GET /api/journal/pdf/{job_id}`,
  `GET /media/{media_id}` (auth: owner or admin; `Cache-Control: private`),
  admin: `GET/PUT /api/admin/seasons/{id}`, `GET/PUT /api/admin/weeks/{id}`,
  `GET/POST/PATCH /api/admin/achievement-types`, `GET/POST/DELETE /api/admin/facts`,
  `GET /api/admin/participants`, `GET /api/admin/participants/{id}`,
  `PUT /api/admin/participants/{id}/stamps/{week}`, `POST .../freezes`, `POST .../achievements`,
  `PUT .../wish`, `GET /api/admin/summary?week=`, `GET /api/admin/audit`.
- Admin = `user.is_admin or user.id in settings.admin_ids`.
- Front-end: vanilla JS modules in `romantika/web/static/`, Telegram `telegram-web-app.js`
  from `https://telegram.org/js/telegram-web-app.js`; `tg.expand()`; works in a plain browser
  in dev with the dev bypass.

## 9. Worker

`python -m romantika.worker` runs forever: (a) job loop — claims one job at a time
(`FOR UPDATE SKIP LOCKED`), kinds: `media_download`, `journal_pdf` (render + `sendDocument`
to the user + store path under `MEDIA_DIR/journals/`), `broadcast`; retries with backoff,
max 5 attempts; (b) schedulers ticking every 60 s in Moscow time: reminders (Thu ≥19:00,
Sun ≥12:00, deduped by `reminder_log`, catch-up within the same day), nightly
`backup_status_check` (reads `/backups/last-verify.json`, alerts admin if stale > 8 days or failed).

## 10. PDF

`romantika/pdf/journal.py`: `render_journal_html(view: JournalView) -> str` (Jinja) and
`render_journal_pdf(view) -> bytes` (WeasyPrint). Fonts: DejaVu (installed in image) with
Cyrillic. Photos referenced by absolute file paths under MEDIA_DIR (no network).

## 11. Ops

- One image `docker/Dockerfile` (python:3.12-slim + tzdata + WeasyPrint deps + fonts-dejavu,
  `uv sync --frozen --no-dev`, non-root user `app` uid 1000). Commands: `bot`, `web`, `worker`,
  `migrate` (alembic upgrade head), `backup`.
- `docker/compose.yml`: `db` (postgres:16-alpine, named volume `pgdata`), `migrate`
  (one-shot), `bot`, `web` (`127.0.0.1:8010:8010`), `worker`, `backup` (same image, runs
  `scripts/backup.sh` on a daily schedule via a tiny loop, plus weekly `restore-verify.sh`).
  Named volumes: `pgdata`, `media`, `backups`. Own network. `restart: unless-stopped`,
  json-file log rotation.
- `docker/compose.vps.yml`: `HTTP(S)_PROXY=http://host.docker.internal:10809` for bot/worker/web
  egress to Telegram, `NO_PROXY` for internal names, `extra_hosts`, `cpus`/`mem_limit`
  (db 0.5/512m, bot 0.5/256m, web 0.5/384m, worker 0.5/512m, backup 0.25/256m).
- `scripts/backup.sh`: `pg_dump -Fc` → `/backups/db/romantika-YYYY-MM-DD.dump`; media
  snapshot `rsync -a --link-dest` → `/backups/media/YYYY-MM-DD/`; retention 30 days; writes
  `/backups/manifest-YYYY-MM-DD.json` (row counts per table, media count, total bytes,
  sha256 of dump).
- `scripts/restore-verify.sh`: restores latest dump into a scratch database, compares row
  counts with manifest, verifies sha256 of 20 random media files against DB, writes
  `/backups/last-verify.json` `{ok, checked_at, dump, tables, media_checked, errors}`.
- `scripts/mac-pull-backups.sh` + `scripts/launchd/com.romantika.backup-pull.plist`: rsync
  `/backups` from the VPS to `~/Backups/romantika/` daily via `ssh vps247 docker run ... tar`.
- `scripts/deploy.sh`: rsync repo (no data) to `/opt/stacks/romantika`, build sequentially
  on the VPS, `up -d`, `docker compose ps`, smoke `curl 127.0.0.1:8010/healthz`.
- CI: `.github/workflows/ci.yml` — ruff, mypy, pytest with a `postgres:16` service
  (`TEST_DATABASE_URL`).

## 12. Testing contract

- `make check` = `uv run ruff check . && uv run ruff format --check . && uv run mypy romantika
  && uv run pytest -q`. This is the deterministic acceptance for every stage, plus
  stage-specific `tests/acceptance/stageN_*` files (read-only for implementers).
- Postgres for tests: `tests/conftest.py` provides `session_factory`/`db_session` fixtures using
  `TEST_DATABASE_URL` if set, otherwise `testcontainers[postgres]`. Each test runs in a
  transaction rolled back at the end, or on a freshly migrated schema per session.
- Bot handlers are tested through services plus router smoke tests; Telegram calls are
  captured by a fake `TelegramGateway`.
- Web is tested with `httpx.AsyncClient(app=...)` and a test helper `sign_init_data(user)`.

## 13. Legacy migration (`romantika/migration/legacy_import.py`)

`python -m romantika.migration.legacy_import --sqlite path --season mexico-2026 [--download]`
maps 12 legacy tables to the model (see DOMAIN.md §9 for the mapping), downloads every
`file_id` via the bot token into MEDIA_DIR, is idempotent (re-running updates nothing that
already matches), and prints a reconciliation table (legacy counts vs imported counts).
