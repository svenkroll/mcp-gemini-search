# T07 MCP-Server, Health und Observability

| | |
| --- | --- |
| Abhängig von | T05, T06 |
| Blockiert | T08, T09 |
| Bereich | server, observability, integration-tests |

## Ziel

Die fachlichen Tools als FastMCP-Server über stdio und zustandsloses Streamable
HTTP bereitstellen, einschließlich Schema, Health und sicherem Logging.

## Kontext

Lesen: `AGENTS.md`, ADR 0002, 0003, 0004, 0007 und 0008 sowie T05 und T06.
Die Serverhüllen bleiben dünn; Tool-Logik wird nicht dupliziert.

## Vorgaben

- FastMCP 4.1.6 exakt verwenden; `mcp.run()` für stdio und `transport="http"`.
- Englische Tool-Beschreibungen mit Hinweis auf nicht vertrauenswürdige
  Webinhalte; Server-Instructions erklären nur die Tool-Nutzung.
- Je Tool ein vollständiges `outputSchema`; `structuredContent` ist kanonisch,
  Textinhalt semantisch identisches JSON.
- Tool-Fehler als `isError`, ohne Pydantic- oder Exception-Text nach außen.
- `/health/live` und `/health/ready` implementieren; Readiness ruft Gemini nie
  auf.
- Pro Tool-Aufruf eine JSON-Logzeile gemäß ADR 0007 auf stdout schreiben.
- FastMCP-In-Memory-Client für Vertrags- und Serverhüllentests nutzen.

## Nicht im Umfang

Container, Bearer-Middleware, Kubernetes-Ingress, Release-Publishing oder
Live-Eval.

## Akzeptanzkriterien

- [ ] Beide Tools erscheinen mit richtiger Eingabe- und Ausgabeschema im
  In-Memory-Client.
- [ ] Stdio und HTTP liefern für identische Fake-Ergebnisse denselben Vertrag.
- [ ] Liveness und Readiness unterscheiden Prozess- und Konfigurationszustand.
- [ ] Logs enthalten Pflichtfelder, aber keine Secrets oder deaktivierten Queries.
- [ ] Ein Test sichert, dass Tool- und Adaptermodule FastMCP-frei bleiben.
- [ ] `make check` ist grün und ein unabhängiger Review ist ohne offenen Befund.
