# Architecture

```text
Flask routes -> validation/services -> repositories -> MySQL (optional)
                     |-> importers (CSV/XLSX/PDF)
                     |-> backtesting engine (walk-forward)
                     |-> reports/exports (local only)
```

The application is intentionally offline-capable for tests and exploration. A public static portfolio can document the project, but it cannot run this Flask/MySQL backend.
