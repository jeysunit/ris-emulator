"""待ち受けのアドレスと認証・CSRF の確かめ（docs/spec/03_web_cli.md 3.3）.

決まり（理由は docs/decisions/0006-web-ui-loopback-by-default.md）：
- 既定は 127.0.0.1 だけで待ち受け、認証は付けない
- 127.0.0.1 以外で待ち受けるときは HTTP Basic を必須にし、パスワードのファイルが無ければ起動しない
- 書き込みの要求は、同じ origin で、起動のたびに作る token を返したときだけ受ける
"""

from __future__ import annotations

import base64
import binascii
import ipaddress
import os
import secrets
from collections.abc import Mapping
from pathlib import Path
from urllib.parse import SplitResult, urlsplit

from fastapi import HTTPException, Request

from app.core.exceptions import ConfigurationError

USERNAME = "ris"
PASSWORD_FILE_ENV = "RIS_WEB_PASSWORD_FILE"
CSRF_HEADER = "x-csrf-token"
CSRF_FIELD = "csrf_token"
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
HTTP_FORBIDDEN = 403
_LOCALHOST_NAME = "localhost"
_TOKEN_BYTES = 32
_HOST_FORBIDDEN_CHARS = frozenset("@/?#\\ ")


class WebStartupError(ConfigurationError):
    """画面を起動できない設定（127.0.0.1 以外でパスワードが無いなど）."""


def is_loopback(host: str) -> bool:
    """ループバックのアドレスか（127.0.0.0/8・::1・localhost）."""
    name = host.strip().strip("[]").lower()
    if name == _LOCALHOST_NAME:
        return True
    try:
        return ipaddress.ip_address(name).is_loopback
    except ValueError:
        return False


def host_header_is_loopback(host_header: str) -> bool:
    """`Host` ヘッダー（`名前:ポート`・`[::1]:ポート`）がループバックの名前か."""
    if not host_header or any(char in host_header for char in _HOST_FORBIDDEN_CHARS):
        return False
    parsed = _split_url(f"//{host_header}")
    if parsed is None:
        return False
    hostname = parsed.hostname
    return hostname is not None and is_loopback(hostname)


def _split_url(value: str) -> SplitResult | None:
    try:
        parsed = urlsplit(value)
        _ = parsed.port  # ポートが読めないと ValueError
    except ValueError:
        return None
    return parsed


def startup_password(bind_address: str, environ: Mapping[str, str] | None = None) -> str | None:
    """起動のときにパスワードを1回読む。ループバック以外でパスワードが無ければ止める."""
    env = os.environ if environ is None else environ
    raw_path = env.get(PASSWORD_FILE_ENV, "").strip()
    if not raw_path:
        if is_loopback(bind_address):
            return None
        raise WebStartupError(
            f"Listening outside localhost ({bind_address}) requires HTTP Basic: "
            f"set {PASSWORD_FILE_ENV} to a file that holds the password",
            {"bind_address": bind_address},
        )
    path = Path(raw_path).expanduser()
    try:
        password = path.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeDecodeError) as exc:
        raise WebStartupError(
            f"Cannot read the password file given by {PASSWORD_FILE_ENV}",
            {"path": str(path), "reason": exc.__class__.__name__},
        ) from exc
    if not password:
        raise WebStartupError(
            f"The password file given by {PASSWORD_FILE_ENV} is empty", {"path": str(path)}
        )
    return password


def basic_auth_ok(authorization: str | None, password: str) -> bool:
    """`Authorization: Basic ...` が利用者 `ris` とパスワードに合うか."""
    if not authorization:
        return False
    scheme, _, encoded = authorization.partition(" ")
    if scheme.lower() != "basic" or not encoded:
        return False
    try:
        decoded = base64.b64decode(encoded.strip(), validate=True).decode("utf-8")
    except (binascii.Error, UnicodeDecodeError):
        return False
    user, separator, given = decoded.partition(":")
    if not separator:
        return False
    user_ok = secrets.compare_digest(user.encode("utf-8"), USERNAME.encode("utf-8"))
    password_ok = secrets.compare_digest(given.encode("utf-8"), password.encode("utf-8"))
    return user_ok and password_ok


def new_csrf_token() -> str:
    return secrets.token_urlsafe(_TOKEN_BYTES)


def same_origin(request: Request) -> bool:
    """`Origin`（無ければ `Referer`）のホストとポートが、要求の `Host` と同じか."""
    host = request.headers.get("host", "")
    source = request.headers.get("origin") or request.headers.get("referer") or ""
    if not host or not source or source == "null":
        return False
    parsed = _split_url(source)
    if parsed is None:
        return False
    return parsed.scheme in ("http", "https") and parsed.netloc.lower() == host.lower()


async def csrf_guard(request: Request) -> None:
    """書き込みの要求（POST など）を、同じ origin と CSRF の token で確かめる."""
    if request.method in SAFE_METHODS:
        return
    if not same_origin(request):
        raise HTTPException(HTTP_FORBIDDEN, "Cross-origin request refused")
    token = request.headers.get(CSRF_HEADER)
    if not token:
        form = await request.form()
        value = form.get(CSRF_FIELD)
        token = value if isinstance(value, str) else None
    expected: str = request.app.state.csrf_token
    if not token or not secrets.compare_digest(token.encode("utf-8"), expected.encode("utf-8")):
        raise HTTPException(HTTP_FORBIDDEN, "CSRF token missing or invalid")
