from __future__ import annotations

from typing import Any

import requests

class FutaminaClient:
    def __init__(self, base_url: str, api_key: str, *, timeout: float = 30.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout
        self._headers = {"X-Api-Key": api_key}

    def get_leagues(self) -> dict[str, Any]:
        url = f"{self.base_url}/leagues"
        response = requests.get(url, headers=self._headers, timeout=self.timeout)
        response.raise_for_status()
        return response.json()

    def get_results_by_league(self, slug: str) -> dict[str, Any]:
        url = f"{self.base_url}/leagues/{slug}/results"
        response = requests.get(url, headers=self._headers, timeout=self.timeout)
        response.raise_for_status()
        return response.json()

    def get_upcoming(self, slug: str) -> dict[str, Any]:
        url = f"{self.base_url}/leagues/{slug}/upcoming"
        response = requests.get(url, headers=self._headers, timeout=self.timeout)
        response.raise_for_status()
        data = response.json()
        matches = [
            {key: item[key] for key in ("id", "startsAt", "home", "away") if key in item}
            for item in data.get("matches", [])
        ]
        return {"league": data.get("league", {}), "matches": matches}
