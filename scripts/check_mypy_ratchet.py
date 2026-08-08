"""Impide aumentar la deuda mypy sin exigir corregir todo el legado de una vez."""

import argparse
import json
import os
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path

BASELINE = Path(__file__).resolve().parent.parent / "mypy-baseline.json"
ERROR = re.compile(r"^(?P<path>[^:]+\.py):\d+: error: (?P<message>.+?)\s+\[(?P<code>[^]]+)]$")


def collect() -> Counter[str]:
    env = {
        **os.environ,
        "DATABASE_URL": os.getenv(
            "DATABASE_URL", "postgresql+asyncpg://user:pass@localhost:5432/test"
        ),
        "DATABASE_URL_SYNC": os.getenv(
            "DATABASE_URL_SYNC", "postgresql://user:pass@localhost:5432/test"
        ),
    }
    result = subprocess.run(
        [sys.executable, "-m", "mypy", "src", "--no-pretty", "--no-error-summary"],
        cwd=BASELINE.parent,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )
    errors: Counter[str] = Counter()
    for line in result.stdout.splitlines():
        match = ERROR.match(line)
        if match:
            fingerprint = "|".join(
                (match.group("path"), match.group("code"), match.group("message"))
            )
            errors[fingerprint] += 1
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--update", action="store_true")
    args = parser.parse_args()
    current = collect()

    if args.update:
        BASELINE.write_text(
            json.dumps(dict(sorted(current.items())), indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        print(f"Baseline mypy actualizado: {sum(current.values())} errores legados")
        return 0

    baseline = Counter(json.loads(BASELINE.read_text(encoding="utf-8")))
    new_errors = current - baseline
    if new_errors:
        print("La rama introduce errores mypy nuevos:")
        for fingerprint, count in sorted(new_errors.items()):
            print(f"  {count}x {fingerprint}")
        return 1
    print(
        f"Ratchet mypy OK: {sum(current.values())} errores actuales, "
        f"maximo heredado {sum(baseline.values())}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
