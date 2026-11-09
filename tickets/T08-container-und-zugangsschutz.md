# T08 Container, lokaler Proxy und HTTP-Zugangsschutz

| | |
| --- | --- |
| Abhängig von | T07 |
| Blockiert | T09, T10 |
| Bereich | container, deployment, security |

## Ziel

Einen eigenständig startbaren, für Kubernetes geeigneten Container samt
lokaler Caddy-Umgebung und statischem HTTP-Zugangsschutz liefern.

## Kontext

Lesen: `AGENTS.md`, ADR 0002, 0006, 0007 und 0008 sowie T07. Produktion nutzt
Traefik vor dem Container; HAProxy ist für dieses Repository transparent.

## Vorgaben

- Multi-Architektur-Image für `linux/amd64` und `linux/arm64`, gebaut mit `uv`.
- Container läuft ohne lokale Entwicklungsdateien, schreibt nur nach stdout und
  akzeptiert Konfiguration ausschließlich über Umgebung.
- HTTP-MCP verlangt ein konfiguriertes Bearer-Token; Health-Endpunkte bleiben
  ohne Token nutzbar. Fehlendes Token verhindert sicheren Start.
- `compose.yaml` und lokales Caddy-Setup dokumentieren Entwicklung und lange
  Read-Timeouts für Streamable-HTTP-Antworten.
- Hadolint und Trivy prüfen Dockerartefakte; kritische und hohe behebbare
  Befunde blockieren die Veröffentlichung.
- GHCR-Publishing wird vorbereitet, aber nur durch einen klaren Release- oder
  manuellen Workflow ausgelöst.

## Nicht im Umfang

Traefik-, HAProxy- oder Kubernetes-Manifeste der persönlichen Infrastruktur,
OAuth, Tokenrotation, Monitoring-Stack oder automatische Produktionseinführung.

## Akzeptanzkriterien

- [ ] Container startet mit gültiger Beispielkonfiguration und beantwortet
  Health-Probes.
- [ ] MCP-Aufruf ohne oder mit falschem Bearer-Token wird abgewiesen; Health
  bleibt erreichbar.
- [ ] Lokaler Caddy-Proxy leitet Streamable HTTP erfolgreich weiter.
- [ ] Image baut und läuft auf beiden Zielarchitekturen nachweisbar.
- [ ] Hadolint und Trivy laufen in lokaler Prüfung und CI.
- [ ] README und Runbook beschreiben Geheimnisübergabe, lokale Ausführung und
  relevante Proxy-Timeouts.
- [ ] `make check` ist grün und ein unabhängiger Review ist ohne offenen Befund.
