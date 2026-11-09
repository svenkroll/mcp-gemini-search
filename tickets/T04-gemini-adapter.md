# T04 Asynchroner Gemini-Adapter

| | |
| --- | --- |
| Abhängig von | T01, T02, T03 |
| Blockiert | T05, T06 |
| Bereich | gemini-client, config, tests |

## Ziel

Einen austauschbaren, vollständig asynchronen Gemini-Adapter mit
konfigurierbaren Betriebsgrenzen und Fake für Offline-Tests bereitstellen.

## Kontext

Lesen: `AGENTS.md`, ADR 0002, 0005, 0006, 0007 und 0009. Das Modell ist
`gemini-3.8-flash`; Deployment und Evals verwenden einen API-Key eines
Projekts mit aktiver Abrechnung.

## Vorgaben

- `google-genai` ausschließlich über `client.aio` verwenden.
- Kleine, frameworkfreie Schnittstelle für `search` und `analyze_url` mit
  normalisierten Ergebnis-, Nutzungs- und Fehlerobjekten definieren.
- Settings über pydantic-settings: API-Key, Modell, Timeouts, Parallelität,
  Retry-Parameter und optionales Query-Logging.
- Standardwerte aus ADR 0006 umsetzen: 60 s, maximal vier parallele Aufrufe,
  zwei Wiederholungen nur für 429/transiente 5xx, Backoff mit Jitter und
  `Retry-After`.
- Grounding- und URL-Context-Metadaten vollständig im Adapter zugänglich
  machen, ohne SDK-Typen nach außen zu geben.
- Fake-Adapter und geprüfte, zulässige Fixtures bereitstellen.

## Nicht im Umfang

MCP-Registrierung, Tool-Validierung, URL-Sicherheitslogik, Container oder
Live-Eval-Ausführung.

## Akzeptanzkriterien

- [ ] Fehlender API-Key verhindert den Start mit eindeutiger lokaler Meldung.
- [ ] Adaptermodule importieren weder FastMCP noch Servermodule.
- [ ] Tests decken Erfolg, 429, 5xx, nicht retrybare Fehler, Timeout,
  Parallelitätsgrenze, Abbruch und fehlende Nutzungsmetrik ab.
- [ ] Tests verwenden keinen echten API-Key und kein Netzwerk.
- [ ] Aufzeichnungen zeigen, dass keine Secrets oder Query-Inhalte ungewollt
  geloggt werden.
- [ ] `make check` ist grün und ein unabhängiger Review ist ohne offenen Befund.
