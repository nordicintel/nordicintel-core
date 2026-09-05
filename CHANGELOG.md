# Changelog

## 0.1.0

- Add strict shared models for providers, harvesting, metadata, explicit selections, and live data.
- Add asynchronous adapter protocols and an injected HTTP client with bounded safe retries.
- Add the initial core-owned PostgreSQL schema and standalone migration command.
- Add typed Psycopg repositories for providers, metadata, schedules, and harvest lifecycle control.

This is the first published contract. Until 1.0, breaking model or protocol changes increment the
minor version and are called out here.
