"""9router availability watchdog.

Open Notebook routes its LLM calls through a local 9router gateway
(``http://127.0.0.1:20128``). 9router is an external process, so this module
lets the API keep it alive: it periodically health-checks the gateway and, if
it's down, (re)starts it with a configurable command.

Everything here is best-effort and opt-in (see ``COMMAND_*``/``NINEROUTER_*``
settings in ``config.py``). In containerised deployments where the host's
9router can't be spawned, the start step simply logs a warning and the loop
keeps checking — it never crashes the API.
"""

from __future__ import annotations

import asyncio
import shlex
import subprocess
import sys
import time

import httpx
from loguru import logger


async def is_up(url: str, timeout: float = 3.0) -> bool:
    """Return True if 9router answers at ``url`` at all.

    Any HTTP response counts as "up" — 9router returns 401/404 on bare probes
    because it requires an API key, but that still proves the server is alive.
    Only a connection/timeout error means it's down.
    """
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            await client.get(url)
        return True
    except Exception:
        return False


def start_9router(start_cmd: str) -> bool:
    """Spawn 9router detached so it outlives this process. Best-effort."""
    if not start_cmd:
        return False
    try:
        kwargs: dict = {
            "stdout": subprocess.DEVNULL,
            "stderr": subprocess.DEVNULL,
            "stdin": subprocess.DEVNULL,
        }
        if sys.platform == "win32":
            # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP | CREATE_NO_WINDOW
            kwargs["creationflags"] = 0x00000008 | 0x00000200 | 0x08000000
            # shell=True lets the .cmd shim on PATH resolve.
            subprocess.Popen(start_cmd, shell=True, **kwargs)
        else:
            kwargs["start_new_session"] = True
            subprocess.Popen(shlex.split(start_cmd), **kwargs)
        logger.info(f"9router watchdog: launched '{start_cmd}'")
        return True
    except Exception as e:
        logger.warning(f"9router watchdog: failed to start ('{start_cmd}'): {e}")
        return False


async def run_9router_watchdog(
    url: str, start_cmd: str, interval_seconds: float
) -> None:
    """Health-check 9router on an interval; (re)start it when down.

    Launch as a long-lived ``asyncio.Task``; cancel to stop. A single failed
    pass is logged and swallowed so the loop keeps running.
    """
    health_url = url.rstrip("/")
    interval = max(15.0, interval_seconds)
    # Grace period after a start attempt before checking again, so we don't
    # spawn repeatedly while the server is still booting.
    boot_grace = 20.0

    while True:
        try:
            if not await is_up(health_url):
                logger.warning(f"9router watchdog: {health_url} is down — starting it.")
                if start_9router(start_cmd):
                    await asyncio.sleep(boot_grace)
                    if await is_up(health_url):
                        logger.success("9router watchdog: 9router is back up.")
                    else:
                        logger.warning(
                            "9router watchdog: still down after start attempt; "
                            "will retry next cycle."
                        )
        except Exception as e:
            logger.warning(f"9router watchdog pass failed: {e}")
        await asyncio.sleep(interval)


# Stamp used only to make accidental double-imports obvious in logs.
_LOADED_AT = time.time()
