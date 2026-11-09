# Tickets

Die Tickets sind die umsetzbare Arbeitsplanung für Gemini Search MCP. Sie
gelten zusammen mit [`AGENTS.md`](../AGENTS.md) und den jeweils genannten ADRs.
Jedes Ticket ist eigenständig lesbar, begrenzt seinen Umfang und enthält
prüfbare Akzeptanzkriterien.

| Nr. | Titel | Abhängig von | Stand |
| --- | --- | --- | --- |
| [T01](T01-repo-geruest-und-qualitaet.md) | Repo-Gerüst und Qualitätswerkzeuge | – | geplant |
| [T02](T02-ground-truth-und-eval.md) | Ground-Truth-Katalog und Eval-Werkzeug | T01 | geplant |
| [T03](T03-nav9v-baseline.md) | nav9v-Baseline messen | T02 | geplant |
| [T04](T04-gemini-adapter.md) | Asynchroner Gemini-Adapter | T01, T02, T03 | geplant |
| [T05](T05-search-tool.md) | Tool `search` | T04 | geplant |
| [T06](T06-analyze-url-tool.md) | Tool `analyze_url` | T04 | geplant |
| [T07](T07-mcp-server-und-observability.md) | MCP-Server, Health und Observability | T05, T06 | geplant |
| [T08](T08-container-und-zugangsschutz.md) | Container, lokaler Proxy und HTTP-Zugangsschutz | T07 | geplant |
| [T09](T09-neuauflage-bewerten.md) | Neuauflage gegen Baseline bewerten | T08 | geplant |
| [T10](T10-e2e-zielclients.md) | Ende-zu-Ende-Test mit Ziel-Clients | T08, T09 | geplant |

Die ADRs werden vor Beginn eines Umsetzungstickets vom Auftraggeber akzeptiert
oder angepasst. Nach einem abgeschlossenen Ticket wird diese Übersicht mit
Stand und Verweis auf den Nachweis aktualisiert.
