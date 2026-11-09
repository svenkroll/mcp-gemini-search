# Technische Schulden

Bewusste spätere Arbeiten als `TD-NNN` mit Kennung und Begründung. Keine
TODO-Kommentare im Code.

| Kennung | Beschreibung | Begründung | Ziel |
| --- | --- | --- | --- |
| TD-001 | CI prüft die Workflow-Datei nicht mit einem Action-Schema (z. B. actionlint). | T01 verlangt zunächst lauffähige Prüfungen; YAML-Syntax, Publisher-Präfix `actions/` und 40-stellige SHA-Pins werden durch Regressionstests abgesichert, aber nicht die vollständige Workflow-Semantik. | Nach T01 |
| TD-002 | `tests/fixtures/` und `eval/` enthalten noch keine Inhalte. | Fixtures und Ground-Truth-Katalog entstehen mit T02. | T02 |
| TD-003 | pre-commit-Hooks werden in CI nicht zusätzlich ausgeführt. | CI deckt Formatierung, Linting, Typen und Tests bereits über Make-Ziele ab. | Bei Bedarf |
