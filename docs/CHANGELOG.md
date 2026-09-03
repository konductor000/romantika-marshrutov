# Changelog

## v2.0.0 — 2026-09-04 (rewrite)

For participants: same bot, same buttons and texts; voice and audio now count as a minimum
report; messages outside a week are saved and passed to Mila; the «Это был максимум/минимум»
button works; the journal is also a Mini App with photos and a PDF.

For Mila: admin Mini App (weeks, participants, stamps, freezes, achievements, wishes, facts,
audit log); backups every night with a weekly restore check and a Telegram alert.

Under the hood: Python 3.12, aiogram 3, FastAPI, Postgres 16, one Docker image, media stored
on the server, legacy SQLite import.
