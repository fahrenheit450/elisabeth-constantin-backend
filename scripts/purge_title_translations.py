"""Purge stored English title translations from artworks.

Goal:
- Titles are French-only (source-of-truth).
- Remove any previously stored `translations.en.title` so the DB no longer carries stale EN titles.

Usage:
  MONGO_URI='mongodb+srv://...' MONGO_DB='yourdb' python3 scripts/purge_title_translations.py

Notes:
- Safe: does NOT touch the root `title` field.
- Only unsets `translations.en.title`.
"""

from __future__ import annotations

import os
from urllib.parse import urlparse

from pymongo import MongoClient
from pymongo.errors import ConfigurationError


def _get_db_name_from_uri(mongo_uri: str) -> str | None:
    try:
        parsed = urlparse(mongo_uri)
        path = (parsed.path or "").lstrip("/")
        if not path:
            return None
        # Atlas URIs can have /db?retryWrites=true
        return path.split("/")[0].split("?")[0] or None
    except Exception:
        return None


def main() -> int:
    mongo_uri = os.getenv("MONGO_URI") or os.getenv("MONGODB_URI")
    if not mongo_uri:
        raise SystemExit("Missing MONGO_URI (or MONGODB_URI)")

    db_name = os.getenv("MONGO_DB") or _get_db_name_from_uri(mongo_uri)
    if not db_name:
        raise SystemExit(
            "No default database in MONGO_URI. Provide MONGO_DB env var (e.g. 'prod')."
        )

    client = MongoClient(mongo_uri)

    try:
        db = client.get_database(db_name)
    except ConfigurationError:
        db = client[db_name]

    artworks = db.get_collection("artworks")

    result = artworks.update_many(
        {"translations.en.title": {"$exists": True}},
        {"$unset": {"translations.en.title": ""}},
    )

    print("Purge complete")
    print(f"- matched:  {result.matched_count}")
    print(f"- modified: {result.modified_count}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
