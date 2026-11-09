---
status: proposed
date: 2026-11-09
decision-makers: Sven Kroll
---

# 0008 Sicherheit

## Kontext und Problemstellung

Der Server ist öffentlich erreichbar, besitzt einen kostenpflichtig nutzbaren
Gemini-Key und ruft fremde URLs ab. Ohne Zugangsschutz, SSRF-Abwehr und klaren
Umgang mit untrusted Webinhalt wären Kosten, interne Netze und Agenten gefährdet.

## Betrachtete Optionen

1. Nur Netzwerkisolation durch Ingress verwenden.
2. Statisches Bearer-Token, URL-Validierung und Prompt-Injection-Grenzen.
3. OAuth und vollständige Nutzerverwaltung im ersten Release.

## Entscheidung

Gewählt wird **Option 2**. HTTP verlangt vor jedem MCP-Aufruf ein statisches
Bearer-Token aus der Deployer-Konfiguration; Health-Endpunkte bleiben für
Kubernetes ohne Token erreichbar. stdio erhält keine HTTP-Authentisierung.
OAuth und Rotation sind nicht Teil des ersten Releases.

`search`-Quellenauflösung und `analyze_url` teilen dieselbe URL-Policy: nur
HTTP(S), keine Zugangsdaten, nur Ports 80/443, höchstens fünf Redirects,
erneute DNS-Prüfung je Verbindungsziel und Sperre von Loopback-, privaten,
Link-Local-, Multicast- und reservierten IPv4/IPv6-Netzen. Limits betragen 5 s
Verbindung, 15 s Lesen, 30 s gesamt und 5 MiB Inhalt.

Webinhalte sind nicht vertrauenswürdig. Englische Tool-Beschreibungen und
Gemini-Instruktionen sagen ausdrücklich, dass sie keine Anweisungen aus Webtext
befolgen dürfen. Injection-Tests dürfen keine fremde Handlungsanweisung,
Prioritätsänderung oder unbelegte Behauptung in die Antwort durchlassen.

## Konsequenzen

- Gut: Ein verlorener öffentlicher URL-Link genügt nicht für Gemini-Nutzung.
- Gut: SSRF- und Ressourcenrisiko sind begrenzt und einheitlich getestet.
- Schlecht: Der Deployer trägt die Verantwortung für Geheimnisablage und Rotation.
- Schlecht: Strenge Port- und Netzregeln schließen manche legitime URLs aus.

## Offen

Traefik- und lokales Caddy-Setup müssen lange Read-Timeouts für requestbezogene
SSE-Antworten erlauben. Der transparente HAProxy ist kein Teil des Containers.

## Weitere Informationen

- [MCP Streamable HTTP](https://github.com/modelcontextprotocol/modelcontextprotocol/blob/main/docs/specification/2026-07-28/basic/transports/index.mdx)
- ADR 0007: Fehlerbehandlung und Logging
