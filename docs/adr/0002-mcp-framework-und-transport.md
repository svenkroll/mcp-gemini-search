---
status: proposed
date: 2026-11-09
decision-makers: Sven Kroll
---

# 0002 MCP-Framework und Transport

## Kontext und Problemstellung

Der Server soll lokal als stdio-Prozess und remote hinter Kubernetes laufen.
Er muss aktuelle und ältere MCP-Clients bedienen können, ohne Tool-Logik an ein
Framework zu koppeln. OpenCode und OpenHands sind die verbindlichen Testclients.

## Betrachtete Optionen

1. Offizielles MCP Python SDK unmittelbar verwenden.
2. FastMCP 4 auf dem offiziellen SDK verwenden.
3. Eigenes JSON-RPC- und Transport-Handling schreiben.

## Entscheidung

Gewählt wird **Option 2**, FastMCP **4.1.6** exakt gepinnt, keine
Vorabversionen. FastMCP 4 basiert auf dem MCP Python SDK v2 und verhandelt
moderne und ältere Protokollrevisionen. Tool-Logik und Gemini-Adapter importieren
FastMCP nicht; `server.py` enthält ausschließlich dünne MCP-Hüllen.

Der Server startet über `mcp.run()`: stdio ist der Standard für lokale Clients,
`mcp.run(transport="http")` bedient Streamable HTTP. Der HTTP-Endpunkt ist
`/mcp`, zustandslos und für die MCP-Revision 2026-07-28 ausgelegt; die
Versionsverhandlung erhält die Kompatibilität mit älteren Clients. Health läuft
unter `/health/live` und `/health/ready`.

## Konsequenzen

- Gut: stdio und HTTP teilen Tool-Verträge und Testfälle.
- Gut: Zustandsloses HTTP funktioniert hinter Load Balancern ohne Session-Affinität.
- Gut: Ein späterer Wechsel zum SDK bleibt auf die Serverhüllen begrenzt.
- Schlecht: FastMCP entwickelt sich schnell und wird strikt gepinnt.
- Schlecht: Kompatibilität von OpenHands wird zusätzlich im E2E-Test bewiesen.

## Offen

Die genaue `google-genai`-Version wird beim ersten Lockfile festgelegt. Der
E2E-Test dokumentiert die tatsächlich verhandelten Protokollrevisionen beider
Ziel-Clients.

## Weitere Informationen

- [FastMCP Running Servers](https://github.com/PrefectHQ/fastmcp/blob/main/docs/deployment/running-server.mdx)
- [MCP Streamable HTTP 2026-07-28](https://github.com/modelcontextprotocol/modelcontextprotocol/blob/main/docs/specification/2026-07-28/basic/transports/index.mdx)
