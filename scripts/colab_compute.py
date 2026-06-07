#!/usr/bin/env python3
"""Host-side client for the Colab compute tunnel.

Reads the per-session bearer token from Google Drive via the Drive API when
possible, then calls the Cloudflare tunnel at https://colab.pkking.computer.
never printed.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

DEFAULT_URL = "https://colab.pkking.computer"
DEFAULT_TIMEOUT_SECONDS = 30
DEFAULT_DRIVE_ACCOUNT = "knackos11@gmail.com"
DEFAULT_DRIVE_FILE_NAME = "colab-compute-token.txt"


class TokenLookupError(RuntimeError):
    """Raised when one token lookup source is unavailable."""


def default_token_paths() -> list[Path]:
    paths: list[Path] = []
    explicit = os.environ.get("COLAB_COMPUTE_TOKEN_FILE")
    if explicit:
        paths.append(Path(explicit).expanduser())

    home = Path.home()
    if platform.system() == "Windows":
        paths.extend(
            [
                home / "Google Drive" / "colab-compute-token.txt",
                home / "My Drive" / "colab-compute-token.txt",
            ]
        )
    else:
        paths.extend(
            [
                home / "Google Drive" / "colab-compute-token.txt",
                home / "GoogleDrive" / "colab-compute-token.txt",
                home / "My Drive" / "colab-compute-token.txt",
            ]
        )
    return paths


def gcloud_executable() -> str | None:
    return (
        shutil.which("gcloud")
        or shutil.which("gcloud.cmd")
        or shutil.which("gcloud.CMD")
    )


def drive_query_escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace("'", "\\'")


def gcloud_access_token(account: str) -> str:
    gcloud = gcloud_executable()
    if not gcloud:
        raise TokenLookupError("gcloud is not installed or not on PATH")

    try:
        return subprocess.check_output(
            [gcloud, "auth", "print-access-token", "--account", account],
            text=True,
            stderr=subprocess.STDOUT,
            timeout=30,
        ).strip()
    except subprocess.CalledProcessError as exc:
        detail = (exc.output or "").strip()
        raise TokenLookupError(f"gcloud could not mint a token for {account}: {detail}") from exc
    except subprocess.TimeoutExpired as exc:
        raise TokenLookupError(f"gcloud timed out minting a token for {account}") from exc


def drive_api_request(
    path: str,
    *,
    access_token: str,
    params: dict[str, str] | None = None,
    timeout: int = DEFAULT_TIMEOUT_SECONDS,
) -> tuple[str, str]:
    endpoint = "https://www.googleapis.com/drive/v3" + path
    if params:
        endpoint += "?" + urlencode(params)
    request = Request(
        endpoint,
        headers={
            "Accept": "application/json",
            "Authorization": f"Bearer {access_token}",
            "User-Agent": "colab-compute-host/1.0",
        },
        method="GET",
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            return (
                response.read().decode("utf-8", errors="replace"),
                response.headers.get("content-type", ""),
            )
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        if exc.code == 403 and "ACCESS_TOKEN_SCOPE_INSUFFICIENT" in detail:
            raise TokenLookupError(
                "gcloud credentials do not include Drive scope. Run once: "
                f"gcloud auth login {os.environ.get('COLAB_COMPUTE_DRIVE_ACCOUNT', DEFAULT_DRIVE_ACCOUNT)} "
                "--enable-gdrive-access --no-activate"
            ) from exc
        raise TokenLookupError(f"Drive API HTTP {exc.code}: {detail[:500]}") from exc
    except URLError as exc:
        raise TokenLookupError(f"Drive API unreachable: {exc.reason}") from exc


def resolve_drive_token(timeout: int = DEFAULT_TIMEOUT_SECONDS) -> tuple[str, str]:
    account = os.environ.get("COLAB_COMPUTE_DRIVE_ACCOUNT", DEFAULT_DRIVE_ACCOUNT).strip()
    file_name = os.environ.get(
        "COLAB_COMPUTE_DRIVE_FILE_NAME", DEFAULT_DRIVE_FILE_NAME
    ).strip()
    if not account:
        raise TokenLookupError("COLAB_COMPUTE_DRIVE_ACCOUNT is empty")
    if not file_name:
        raise TokenLookupError("COLAB_COMPUTE_DRIVE_FILE_NAME is empty")

    access_token = gcloud_access_token(account)
    query = f"name = '{drive_query_escape(file_name)}' and trashed = false"
    raw, content_type = drive_api_request(
        "/files",
        access_token=access_token,
        params={
            "q": query,
            "spaces": "drive",
            "fields": "files(id,name,size,modifiedTime)",
            "orderBy": "modifiedTime desc",
            "pageSize": "1",
            "supportsAllDrives": "true",
            "includeItemsFromAllDrives": "true",
        },
        timeout=timeout,
    )
    if "application/json" not in content_type:
        raise TokenLookupError("Drive API file lookup did not return JSON")
    files = json.loads(raw).get("files", [])
    if not files:
        raise TokenLookupError(f"Drive file not found for {account}: {file_name}")

    file = files[0]
    file_id = file["id"]
    token_raw, _ = drive_api_request(
        f"/files/{quote(file_id, safe='')}",
        access_token=access_token,
        params={"alt": "media", "supportsAllDrives": "true"},
        timeout=timeout,
    )
    token = token_raw.strip()
    if not token:
        raise TokenLookupError(f"Drive file is empty for {account}: {file_name}")
    return token, f"gdrive:{account}:{file_name}:{file.get('modifiedTime', 'unknown')}"


def resolve_token(timeout: int = DEFAULT_TIMEOUT_SECONDS) -> tuple[str, str]:
    env_token = os.environ.get("COLAB_COMPUTE_TOKEN", "").strip()
    if env_token:
        return env_token, "env:COLAB_COMPUTE_TOKEN"

    lookup_errors: list[str] = []
    try:
        return resolve_drive_token(timeout=timeout)
    except TokenLookupError as exc:
        lookup_errors.append(str(exc))

    checked: list[str] = []
    for path in default_token_paths():
        checked.append(str(path))
        try:
            token = path.read_text(encoding="utf-8").strip()
        except FileNotFoundError:
            continue
        if token:
            return token, str(path)

    joined = "\n  - ".join(checked)
    details = "\n".join(f"  - {error}" for error in lookup_errors)
    raise SystemExit(
        "No Colab compute token found. Set COLAB_COMPUTE_TOKEN, configure "
        "gcloud Drive access, set COLAB_COMPUTE_TOKEN_FILE, or wait for local "
        "Google Drive sync.\nDrive API errors:\n"
        f"{details}\nChecked local files:\n  - {joined}"
    )


def request_json(
    method: str,
    path: str,
    *,
    token: str | None,
    url: str,
    body: dict[str, Any] | None = None,
    timeout: int = DEFAULT_TIMEOUT_SECONDS,
) -> Any:
    endpoint = url.rstrip("/") + path
    data = None if body is None else json.dumps(body).encode("utf-8")
    headers = {"Accept": "application/json", "User-Agent": "colab-compute-host/1.0"}
    if body is not None:
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = f"Bearer {token}"

    req = Request(endpoint, data=data, headers=headers, method=method)
    try:
        with urlopen(req, timeout=timeout) as response:
            raw = response.read().decode("utf-8", errors="replace")
            content_type = response.headers.get("content-type", "")
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise SystemExit(f"HTTP {exc.code} from {path}: {detail}") from exc
    except URLError as exc:
        raise SystemExit(f"Could not reach {endpoint}: {exc.reason}") from exc

    if "application/json" in content_type:
        return json.loads(raw)
    return raw


def print_json(value: Any) -> None:
    print(json.dumps(value, indent=2, sort_keys=True))


def command_status(args: argparse.Namespace) -> None:
    token, source = resolve_token(timeout=args.timeout)
    health = request_json("GET", "/healthz", token=None, url=args.url, timeout=args.timeout)
    runtime = request_json("GET", "/runtime", token=token, url=args.url, timeout=args.timeout)
    print_json({"token_source": source, "healthz": health, "runtime": runtime})


def command_models(args: argparse.Namespace) -> None:
    token, _ = resolve_token(timeout=args.timeout)
    print_json(request_json("GET", "/v1/models", token=token, url=args.url, timeout=args.timeout))


def command_chat(args: argparse.Namespace) -> None:
    token, _ = resolve_token(timeout=args.timeout)
    payload = {
        "messages": [{"role": "user", "content": args.prompt}],
        "temperature": args.temperature,
        "max_tokens": args.max_tokens,
        "stream": False,
    }
    result = request_json(
        "POST",
        "/v1/chat/completions",
        token=token,
        url=args.url,
        body=payload,
        timeout=args.timeout,
    )
    try:
        print(result["choices"][0]["message"]["content"])
    except (KeyError, IndexError, TypeError):
        print_json(result)


def command_token_path(args: argparse.Namespace) -> None:
    token, source = resolve_token(timeout=args.timeout)
    print_json({"token_source": source, "token_length": len(token)})


def command_drive_token(args: argparse.Namespace) -> None:
    try:
        token, source = resolve_drive_token(timeout=args.timeout)
    except TokenLookupError as exc:
        raise SystemExit(str(exc)) from exc
    print_json({"token_source": source, "token_length": len(token)})


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Host-side Colab tunnel client")
    parser.add_argument(
        "--url",
        default=os.environ.get("COLAB_COMPUTE_URL", DEFAULT_URL),
        help=f"Colab tunnel URL, default: {DEFAULT_URL}",
    )
    parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT_SECONDS)
    subparsers = parser.add_subparsers(dest="command", required=True)

    status = subparsers.add_parser("status", help="Check /healthz and authenticated /runtime")
    status.set_defaults(func=command_status)

    models = subparsers.add_parser("models", help="List OpenAI-compatible models")
    models.set_defaults(func=command_models)

    chat = subparsers.add_parser("chat", help="Send one chat prompt")
    chat.add_argument("prompt")
    chat.add_argument("--temperature", type=float, default=0.2)
    chat.add_argument("--max-tokens", type=int, default=128)
    chat.set_defaults(func=command_chat)

    token_path = subparsers.add_parser("token-path", help="Show token source and length only")
    token_path.set_defaults(func=command_token_path)

    drive_token = subparsers.add_parser(
        "drive-token",
        help="Fetch token from Google Drive API only and show source/length",
    )
    drive_token.set_defaults(func=command_drive_token)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    args.func(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
