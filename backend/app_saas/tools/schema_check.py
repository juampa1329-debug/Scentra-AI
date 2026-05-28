from __future__ import annotations

import json
import sys
from pathlib import Path

from app_saas.db import get_engine
from app_saas.shared.schema_readiness import schema_readiness_report


def main() -> None:
    migrations_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else None
    engine = get_engine()
    with engine.begin() as conn:
        report = schema_readiness_report(conn, migrations_dir=migrations_dir)

    print(json.dumps(report, ensure_ascii=True, indent=2, sort_keys=True))
    if not report.get("ok"):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
