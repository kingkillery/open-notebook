import os

# ROOT DATA FOLDER
DATA_FOLDER = "./data"

# LANGGRAPH CHECKPOINT FILE
sqlite_folder = f"{DATA_FOLDER}/sqlite-db"
os.makedirs(sqlite_folder, exist_ok=True)
LANGGRAPH_CHECKPOINT_FILE = f"{sqlite_folder}/checkpoints.sqlite"

# UPLOADS FOLDER
UPLOADS_FOLDER = f"{DATA_FOLDER}/uploads"
os.makedirs(UPLOADS_FOLDER, exist_ok=True)

# TIKTOKEN CACHE FOLDER
# Reads TIKTOKEN_CACHE_DIR from the environment so Docker can redirect the cache
# to a path outside /data/ (which is typically volume-mounted and would hide the
# pre-baked encoding baked into the image at build time).
TIKTOKEN_CACHE_DIR = os.environ.get("TIKTOKEN_CACHE_DIR", "").strip() or f"{DATA_FOLDER}/tiktoken-cache"
os.makedirs(TIKTOKEN_CACHE_DIR, exist_ok=True)

# COMMAND (JOB) HISTORY CLEANUP
# surreal-commands records one row per background job (embeddings, podcasts,
# NotebookLM studio jobs, ...) in the `command` table and never prunes them, so
# the table grows without bound. These settings bound its growth by periodically
# deleting old, finished (completed/failed/error) job records. Set
# COMMAND_HISTORY_CLEANUP_ENABLED=false to disable.
COMMAND_HISTORY_CLEANUP_ENABLED = os.environ.get(
    "COMMAND_HISTORY_CLEANUP_ENABLED", "true"
).strip().lower() not in ("false", "0", "no", "off")
COMMAND_HISTORY_RETENTION_DAYS = int(
    os.environ.get("COMMAND_HISTORY_RETENTION_DAYS", "7")
)
COMMAND_HISTORY_CLEANUP_INTERVAL_HOURS = float(
    os.environ.get("COMMAND_HISTORY_CLEANUP_INTERVAL_HOURS", "12")
)
