"""Database package."""

from database import (  # noqa: F401
    auth_schema,
    batch_rejections,  # fx-hygiene: batch_rejections registry (contracts §3)
    llm_calls,
    schema_registry,
    storage_schema,
    worker_heartbeat,
)
from services import (  # noqa: F401 - registers llm_calls (ws-g)
    llm_accounting as _llm_accounting_schema,
)
