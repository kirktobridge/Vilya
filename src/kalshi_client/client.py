"""KalshiClient: authenticated HTTP client with retry logic."""
import base64
import time
from typing import Any

import requests

from src.config import settings
from src.monitoring.logger import get_logger

log = get_logger(__name__)

_RETRY_CODES = {429, 500, 502, 503, 504}
_MAX_RETRIES = 5
_BACKOFF_BASE = 1.5  # seconds


def _make_signature(private_key_path: str, timestamp_ms: int, method: str, path: str) -> str:
  """Generate RSA-PSS base64 signature for Kalshi API request auth."""
  from cryptography.hazmat.primitives import hashes, serialization
  from cryptography.hazmat.primitives.asymmetric import padding

  msg = f"{timestamp_ms}{method}{path}".encode()
  with open(private_key_path, "rb") as f:
    private_key = serialization.load_pem_private_key(f.read(), password=None)
  sig = private_key.sign(
    msg,
    padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=padding.PSS.DIGEST_LENGTH),
    hashes.SHA256(),
  )
  return base64.b64encode(sig).decode()


class KalshiAPIError(Exception):
  def __init__(self, status_code: int, message: str) -> None:
    super().__init__(f"HTTP {status_code}: {message}")
    self.status_code = status_code


class KalshiClient:
  def __init__(
    self,
    api_key: str | None = None,
    base_url: str | None = None,
    private_key_path: str | None = None,
  ) -> None:
    self._api_key = api_key or settings.kalshi_api_key
    self._base_url = base_url or settings.kalshi_base_url
    self._private_key_path = private_key_path or settings.kalshi_private_key_path
    self._session = requests.Session()
    self._session.headers.update({
      "Content-Type": "application/json",
      "Accept": "application/json",
    })
    # Use Bearer auth when no private key is configured (dev / paper mode)
    if not self._private_key_path:
      self._session.headers["Authorization"] = f"Bearer {self._api_key}"

  def _auth_headers(self, method: str, path: str) -> dict[str, str]:
    """Return RSA-PSS auth headers, or empty dict when using Bearer."""
    if not self._private_key_path:
      return {}
    ts = int(time.time() * 1000)
    # Strip query string — signature covers path only
    clean_path = path.split("?")[0]
    sig = _make_signature(self._private_key_path, ts, method.upper(), clean_path)
    return {
      "KALSHI-ACCESS-KEY": self._api_key,
      "KALSHI-ACCESS-TIMESTAMP": str(ts),
      "KALSHI-ACCESS-SIGNATURE": sig,
    }

  def _request(
    self,
    method: str,
    path: str,
    *,
    params: dict[str, Any] | None = None,
    json: dict[str, Any] | None = None,
  ) -> Any:
    url = f"{self._base_url}{path}"
    extra_headers = self._auth_headers(method, path)
    for attempt in range(_MAX_RETRIES):
      resp = self._session.request(
        method, url, params=params, json=json, headers=extra_headers, timeout=10
      )
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
