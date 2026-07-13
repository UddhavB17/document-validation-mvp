"""Export checklist response JSON schema for frontend type generation."""

from __future__ import annotations

import json
from pathlib import Path

from database.models import ChecklistVerificationResponse


def main() -> None:
    target = Path("frontend/generated/checklist.schema.json")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(ChecklistVerificationResponse.model_json_schema(), indent=2),
        encoding="utf-8",
    )
    print(f"Wrote {target}")


if __name__ == "__main__":
    main()
