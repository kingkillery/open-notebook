"""Retention cleanup for the surreal-commands ``command`` (job history) table.

The job queue records one row per background job and never prunes them, so the
table grows without bound. This module deletes *finished* job records older than
a retention window, and provides a periodic background loop the API can run.

Safety rules:
- Only terminal jobs (``completed`` / ``failed`` / ``error``) are ever deleted;
  in-flight jobs (``new`` / ``running``) are never touched, so a job a caller is
  still polling cannot be removed out from under it.
- Only rows with a non-NULL ``created`` are deleted. Rows created before
  migration 15 (which added the DB-level ``created`` default) have NULL
  ``created`` and are intentionally left alone — they are a finite legacy set,
  not a source of unbounded growth.
"""

from datetime import datetime, timedelta, timezone

from loguru import logger

from open_notebook.database.repository import repo_query

# Terminal job statuses that are safe to delete once aged out.
TERMINAL_STATUSES = ["completed", "failed", "error"]


async def cleanup_command_history(
    retention_days: int = 7, dry_run: bool = False
) -> int:
    """Delete finished command/job records older than ``retention_days``.

    Args:
        retention_days: Age threshold; finished jobs older than this are removed.
            Values <= 0 are treated as 0 (delete all *finished* timestamped jobs).
        dry_run: If True, count what would be deleted without deleting.

    Returns:
        The number of records deleted (or that would be deleted in dry-run mode).
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=max(0, retention_days))
    where = (
        "status IN $statuses AND created != NONE AND created < $cutoff"
    )
    params = {"statuses": TERMINAL_STATUSES, "cutoff": cutoff}

    count_rows = await repo_query(
        f"SELECT count() FROM command WHERE {where} GROUP ALL", params
    )
    to_delete = count_rows[0]["count"] if count_rows else 0

    if to_delete and not dry_run:
        await repo_query(f"DELETE command WHERE {where}", params)
        logger.info(
            f"Command history cleanup: deleted {to_delete} finished job record(s) "
            f"older than {retention_days}d."
        )
    elif dry_run:
        logger.info(
            f"Command history cleanup (dry run): {to_delete} record(s) older "
            f"than {retention_days}d would be deleted."
        )
    else:
        logger.debug("Command history cleanup: nothing to delete.")

    return to_delete


async def run_command_history_cleanup_loop(
    retention_days: int, interval_hours: float
) -> None:
    """Run :func:`cleanup_command_history` immediately, then every interval.

    Designed to be launched as a long-lived ``asyncio.Task``; cancel the task to
    stop it. Errors in a single pass are logged and swallowed so the loop keeps
    running.
    """
    import asyncio

    interval_seconds = max(60.0, interval_hours * 3600.0)
    while True:
        try:
            await cleanup_command_history(retention_days)
        except Exception as e:  # never let a transient DB error kill the loop
            logger.warning(f"Command history cleanup pass failed: {e}")
        await asyncio.sleep(interval_seconds)
