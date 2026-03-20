"""KalshiClient: authenticated HTTP client with retry logic."""
import time
from typing import Any

import requests

from src.config import settings
from src.monitoring.logger import get_logger

log = get_logger(__name__)

_RETRY_CODES = {429, 500, 502, 503, 504}
_MAX_RETRIES = 5
_BACKOFF_BASE = 1.5  # seconds


class KalshiAPIError(Exception):
  def __init__(self, status_code: int, message: str) -> None:
    super().__init__(f"HTTP {status_code}: {message}")
    self.status_code = status_code


class KalshiClient:
  def __init__(self, api_key: str | None = None, base_url: str | None = None) -> None:
    self._api_key = api_key or settings.kalshi_api_key
    self._base_url = base_url or settings.kalshi_base_url
    self._session = requests.Session()
    self._session.headers.update({
      "Authorization": f"Bearer {self._api_key}",
      "Content-Type": "application/json",
      "Accept": "application/json",
    })

  def _request(
    self,
    method: str,
    path: str,
    *,
    params: dict[str, Any] | None = None,
    json: dict[str, Any] | None = None,
  ) -> Any:
    url = f"{self._base_url}{path}"
    for attempt in range(_MAX_RETRIES):
      resp = self._session.request(method, url, params=params, json=json, timeout=10)
      if resp.status_code in _RETRY_CODES and attempt < _MAX_RETRIES - 1:
        wait = _BACKOFF_BASE ** attempt
        log.warning("kalshi_retry", status=resp.status_code, attempt=attempt, wait=wait)
        time.sleep(wait)
        continue
      if not resp.ok:
        raise KalshiAPIError(resp.status_code, resp.text)
      return resp.json()
    raise KalshiAPIError(0, "Max retries exceeded")

  def get(self, path: str, params: dict[str, Any] | None = None) -> Any:
    return self._request("GET", path, params=params)

  def post(self, path: str, json: dict[str, Any]) -> Any:
    return self._request("POST", path, json=json)

  def delete(self, path: str) -> Any:
    return self._request("DELETE", path)
