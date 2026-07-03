"""Small pymongo wrapper: upsert records and look them up by identifier."""

from __future__ import annotations

from pymongo import MongoClient


class MongoStore:
    def __init__(self, uri: str, database: str):
        # serverSelectionTimeoutMS keeps a bad connection from hanging for the
        # default 30 seconds; the ping fails fast so we learn at startup.
        self.client = MongoClient(uri, serverSelectionTimeoutMS=5000)
        self.db = self.client[database]
        self.client.admin.command("ping")

    def ensure_identifier_index(self, collection: str) -> None:
        # A unique index on identifier is what enforces "no duplicate records":
        # two upserts for the same identifier can never become two documents.
        self.db[collection].create_index("identifier", unique=True)

    def find_by_identifier(self, collection: str, identifier: str) -> dict | None:
        return self.db[collection].find_one({"identifier": identifier})

    def find(self, collection: str, query: dict):
        # Return a cursor for a query, so the caller can stream large result sets.
        return self.db[collection].find(query)

    def upsert(self, collection: str, identifier: str, document: dict) -> None:
        # Update the matching document, or insert it if none exists. Keyed on
        # identifier, so a second run overwrites in place instead of adding a row.
        self.db[collection].update_one(
            {"identifier": identifier},
            {"$set": document},
            upsert=True,
        )

    def close(self) -> None:
        self.client.close()
