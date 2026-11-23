"""Durable storage for the few settings an admin changes from the web console (theme, demo open access).

Why: Azure Container Apps scales to zero and its disk is wiped on every restart, so these can't live in a
file inside the container. Each setting is one small JSON document, saved by name:

  AZURE_STORAGE_ACCOUNT_URL set  -> a blob in Azure Blob Storage (managed identity, no keys)
  not set (local dev, tests)     -> data/runtime/<name>

Readers fall back to their own default if the store is unreachable, so a storage hiccup never takes a page down.
"""
from __future__ import annotations

import json
import os

from solstice import runtime_store

BLOB_CONTAINER = os.getenv("SOLSTICE_SETTINGS_CONTAINER", "solstice-settings")


class FileBackend:
    name = "file"

    def __init__(self, doc: str):
        self.doc = doc

    def read(self) -> dict | None:
        p = runtime_store._dir() / self.doc
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None

    def write(self, data: dict) -> None:
        (runtime_store._dir() / self.doc).write_text(json.dumps(data), encoding="utf-8")


class BlobBackend:
    name = "azure-blob"

    def __init__(self, account_url: str, doc: str, container_client=None):
        self.doc = doc
        self._account_url = account_url
        self._container = container_client   # injectable for tests

    def _blob(self):
        if self._container is None:
            # Imported here so local development and tests don't need the Azure packages.
            from azure.identity import DefaultAzureCredential
            from azure.storage.blob import ContainerClient
            # AZURE_CLIENT_ID (set in the container app) selects the user-assigned managed identity.
            self._container = ContainerClient(self._account_url, BLOB_CONTAINER,
                                              credential=DefaultAzureCredential())
        return self._container.get_blob_client(self.doc)

    def read(self) -> dict | None:
        try:
            return json.loads(self._blob().download_blob().readall())
        except Exception as e:   # a missing blob is normal on first run; anything else is for the caller to log
            if type(e).__name__ == "ResourceNotFoundError":
                return None
            raise

    def write(self, data: dict) -> None:
        self._blob().upload_blob(json.dumps(data), overwrite=True)


def make(doc: str):
    """The backend for one settings document, chosen by environment."""
    url = os.getenv("AZURE_STORAGE_ACCOUNT_URL")
    return BlobBackend(url, doc) if url else FileBackend(doc)
