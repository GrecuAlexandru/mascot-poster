from __future__ import annotations

from pathlib import Path
from typing import Optional, Protocol

from pydantic import BaseModel


class StorageObject(BaseModel):
    key: str
    url: str
    size: int
    provider: str


class StorageProvider(Protocol):
    @property
    def name(self) -> str: ...

    async def upload(
        self,
        local_path: Path,
        key: str,
    ) -> StorageObject: ...

    async def download(
        self,
        key: str,
        local_path: Path,
    ) -> Path: ...

    def get_url(self, key: str) -> str: ...
