# PRD: Gemini Search MCP (Neuauflage)

Stand: 09.11.2026 · Entwurf von Sven Kroll · Status: zur Ausarbeitung durch einen Agenten

## 0. Auftrag an den ausarbeitenden Agenten

Dieses Dokument beschreibt Ziel, Rahmen und Grundsatzentscheidungen. Es ist bewusst grob. Deine Aufgabe:

1. Das PRD prüfen, Lücken und Widersprüche als offene Fragen sammeln, nichts stillschweigend annehmen
2. Die in Abschnitt 9 genannten ADRs im MADR-Format schreiben (Status `proposed`)
3. Die Tickets aus Abschnitt 10 im Ticketformat aus Abschnitt 8.3 ausformulieren, mit Abhängigkeiten
4. Den Ground-Truth-Katalog (Abschnitt 6) als erstes Arbeitspaket planen, vor jeder Tool-Implementierung
5. Annahmen, die mit "zu prüfen" markiert sind, gegen die aktuelle Doku verifizieren und das Ergebnis im passenden ADR festhalten

Code schreibst du in diesem Schritt nicht.

## 1. Ziel

Ein stabiler, testbarer MCP-Server, der LLM-Clients Websuche und das Lesen von Webseiten über die Gemini API bereitstellt. Funktional entspricht er dem Hobbyprojekt [nav9v/gemini-search-mcp](https://github.com/nav9v/gemini-search-mcp): genau zwei Tools, `search` und `analyze_url`.

Der Maßstab ist nicht "technisch sauber", sondern **nützlich für das aufrufende LLM**: Antworten müssen korrekt, belegbar und für das Modell gut verwertbar sein. Ein MCP-Server, dessen Ergebnisse nicht stimmen, wird nicht genutzt, egal wie gut er gebaut ist. Deshalb steht die Qualitätsmessung (Abschnitt 6) vor der Entwicklung.

## 2. Ausgangslage: Analyse von nav9v

| Thema | Stand bei nav9v | Bewertung |
| --- | --- | --- |
| Aufbau | Eine Datei, Low-Level-`mcp`-SDK | schwer test- und wartbar |
| Transport | nur stdio | kein Betrieb als Dienst |
| `search(query)` | Gemini mit `google_search` und `url_context`, Ausgabe Markdown-Antwort plus Quellenliste | siehe 2.1 |
| `analyze_url(url, question?)` | Gemini nur mit `url_context`, URL im Prompt | siehe 2.1 |
| Fehler | als normaler Text, nicht als MCP-Fehler | Client erkennt Fehler nicht |
| Async | Handler `async`, aber synchroner Gemini-Aufruf | blockiert den Event-Loop |
| Robustheit | keine Timeouts, keine Retries, Limits nur in Beschreibungen | instabil unter Last |
| Konfiguration | `.env` mit `GEMINI_API_KEY`, `GEMINI_MODEL` (Default hart verdrahtet) | ok, aber ungeprüft |
| Tests | keine | |
| Extras | 4 Prompts, 2 Info-Resources | entbehrlich |

### 2.1 Verwertbarkeit für das LLM

- **Format:** Markdown liest jedes LLM gut. Kein Problem.
- **Inhalt:** Ein LLM fasst für ein LLM zusammen. Das aufrufende Modell bekommt Wissen aus zweiter Hand ohne Snippets, kann Quellen nicht abwägen und nicht wörtlich zitieren. Fehler von Gemini kommen ungefiltert durch.
- **Quellen (zu prüfen):** Die Grounding-Quellen sind nach bisherigem Kenntnisstand Weiterleitungs-URLs (`vertexaisearch.cloud.google.com/grounding-api-redirect/...`) mit der Domain als Titel. Sie sind schlecht einzuordnen, laufen ab und taugen kaum als Eingabe für `analyze_url`.
- **`analyze_url`:** liefert Geminis Antwort, nicht den Seiteninhalt. Ohne `question` bleibt nur eine allgemeine Zusammenfassung.

### 2.2 Vergleich mit Serper.dev und Tavily

| Dienst | Liefert | Stärke | Schwäche |
| --- | --- | --- | --- |
| Gemini Grounding (nav9v) | fertige Antwort plus Quellen | kompakt, wenig Tokens | zweite Hand, schwache Quellen-URLs |
| Serper.dev | Google-SERP als JSON: `organic` (title, link, snippet, position), optional `answerBox`, `knowledgeGraph`, `peopleAlsoAsk`, `relatedSearches` | echte URLs, LLM synthetisiert selbst | keine Antwort, kein Seiteninhalt |
| Tavily | optionale `answer` plus `results` (title, url, content, score, optional raw_content), separates `extract` für Seiteninhalte | Antwort und Belege, LLM-freundlich | weiterer Anbieter |

Zielbild: `search` bewegt sich in Richtung Tavily, also Antwort **plus** Quellen mit Belegstellen.

## 3. Umfang

### Im Umfang

- Tool `search`: Websuche mit Antwort, echten Quellen und Belegstellen
- Tool `analyze_url`: eine öffentliche URL lesen und eine Frage dazu beantworten
- Transporte: Streamable HTTP (zustandslos) und stdio
- Betrieb als Container, Start über `mcp.run(...)` (Uvicorn intern über FastMCP)
- Qualitätsmessung mit Ground Truth als Teil des Repos und der CI

### Nicht im Umfang

- Prompts und Resources von nav9v (ggf. später als optionales Modul)
- Weitere Suchanbieter (Serper, Tavily) als Backend. Die Schnittstelle zum Backend soll einen späteren Wechsel aber zulassen.
- Caching über einfache Mittel hinaus, Nutzerverwaltung, Abrechnung
- OAuth, solange der Server nicht öffentlich betrieben wird

## 4. Funktionale Anforderungen

### 4.1 `search`

- **Eingabe:** `query` (Pflicht, Längengrenze im Schema), optional `max_sources`
- **Ausgabe (Skizze, Details im ADR):**
  - `answer`: Antwort von Gemini
  - `sources[]`: `title`, `url` (aufgelöste echte URL, nie die Weiterleitung), `evidence[]` (Textstellen der Antwort, die laut `groundingSupports` auf diese Quelle gestützt sind)
  - `search_queries[]`: die von Gemini tatsächlich ausgeführten Suchanfragen
- Weiterleitungen werden serverseitig aufgelöst, mit Timeout. Nicht auflösbare Quellen werden markiert, nicht verschwiegen.

### 4.2 `analyze_url`

- **Eingabe:** `url` (Pflicht, nur http/https, keine privaten oder lokalen Adressen), `question` (Pflicht oder mit sinnvollem Default, im ADR entscheiden)
- **Ausgabe (Skizze):** `answer`, `url`, `retrieval_status` (ob die Seite wirklich geladen wurde, mit Grund bei Fehlschlag)
- Wurde die Seite nicht geladen, darf keine "Antwort" aus Modellwissen als Seiteninhalt erscheinen. Das ist ein Fehlerfall.

### 4.3 Gemeinsam für beide Tools

- `outputSchema` je Tool, `structuredContent` plus derselbe Inhalt als Text
- Fehler als `isError` mit kurzer, generischer Meldung, Details nur im Log
- Eigene Meldungen für ungültige Eingaben statt durchgereichter Pydantic-Texte (Lehre aus ASCOR TD-002)
- Tool-Beschreibungen englisch, kennzeichnen Webinhalte als nicht vertrauenswürdig (Prompt Injection)
- Server-Instructions erklären nur die Nutzung der Tools

## 5. Nicht-funktionale Anforderungen

| Bereich | Anforderung |
| --- | --- |
| Async | Async-Client von google-genai (`client.aio`), nichts blockiert den Event-Loop |
| Timeouts | pro Gemini-Aufruf und pro URL-Auflösung, konfigurierbar |
| Retries | mit Backoff nur bei 429 und 5xx, begrenzte Versuche |
| Parallelität | Obergrenze gleichzeitiger Gemini-Aufrufe |
| Modell | konfigurierbar, Default gepinnt, nicht im Code verdrahtet |
| Konfiguration | pydantic-settings, `.env.example`, Start bricht ohne API-Key mit klarer Meldung ab |
| Logging | eine JSON-Zeile pro Tool-Aufruf (Tool, Dauer, Status, Modell, Tokens, Request-ID), ohne API-Key, Query-Inhalte konfigurierbar |
| Health | Liveness und Readiness bei HTTP |
| Auth | bei HTTP-Betrieb mindestens Bearer-Token vor dem Server, sonst nutzt jeder den API-Key |
| Datenschutz | README-Hinweis: im kostenlosen Gemini-Tarif kann Google Eingaben zur Produktverbesserung nutzen, im bezahlten nicht (zu prüfen) |
| Nutzungsbedingungen | Auflagen von Google für Grounding mit Google Search prüfen (z. B. Anzeige von Suchvorschlägen) und im ADR festhalten (zu prüfen) |
| Proxy | bei SSE ausreichend lange Read-Timeouts im Reverse Proxy |

## 6. Qualitätsmessung mit Ground Truth (vor der Entwicklung)

Bevor Tools gebaut werden, steht fest, woran "gute Antwort" gemessen wird. Ohne diese Messung wird nicht implementiert.

### 6.1 Testkatalog

- Fragen mit bekannter, belegbarer Antwort und erwarteter Quelle, versioniert im Repo (`eval/`)
- Mischung, grob:
  - Fakten mit stabiler Antwort (Kontrollgruppe)
  - aktuelle Fakten, die sich ändern (mit Datum der Ground Truth)
  - technische Doku-Fragen (Versionen, Parameter, Defaults)
  - Fragen auf Deutsch und Englisch
  - Fragen ohne gute Antwort im Netz (erwartet: ehrliches "nicht gefunden")
  - `analyze_url` mit HTML, PDF, nicht erreichbarer Seite, Seite mit versteckter Anweisung (Prompt Injection)
- Pro Eintrag: Frage, erwartete Kernaussage, akzeptierte Quellen oder Domains, Kategorie, Datum

### 6.2 Metriken

| Metrik | Bedeutung |
| --- | --- |
| Korrektheit | Kernaussage stimmt mit Ground Truth überein |
| Belegbarkeit | mindestens eine Quelle stützt die Aussage tatsächlich |
| Quellenqualität | Quellen-URLs echt, erreichbar, nicht nur Weiterleitungen |
| Ehrlichkeit | bei fehlender Antwort kein erfundenes Ergebnis |
| Injection-Resistenz | versteckte Anweisungen landen nicht als Handlung oder Aussage in der Antwort |
| Latenz | p50 und p95 je Tool |
| Kosten | Tokens und Aufrufe je Anfrage |

### 6.3 Vorgehen

1. **Baseline:** Katalog gegen nav9v unverändert laufen lassen. Das ist der Vergleichswert.
2. **Bewertung:** LLM-as-Judge mit festem Prompt und gepinntem Modell, kalibriert an einer manuell bewerteten Stichprobe. Abweichungen zwischen Judge und Mensch werden dokumentiert.
3. **Schwellenwerte:** Go/No-Go-Grenzen je Metrik im ADR festlegen, bevor Ergebnisse vorliegen
4. **Ende-zu-Ende-Test:** Stichprobe zusätzlich über einen echten Client (z. B. Claude Desktop), um zu prüfen, ob das aufrufende LLM die Ausgabe sinnvoll nutzt, nicht nur ob Gemini richtig antwortet
5. **CI:** kleiner, stabiler Teil des Katalogs als nächtlicher oder manueller Job (kostet API-Aufrufe, nicht bei jedem PR). Unit-Tests laufen mit aufgezeichneten Antworten ohne echte Aufrufe.

## 7. Technische Leitplanken

Übernommen aus dem ASCOR-MCP-PoC, sofern ein ADR nichts anderes entscheidet:

- Python, uv, Ruff, ty (gepinnt), pytest mit Mindestabdeckung 80 %
- FastMCP 4, exakt gepinnt, keine Vorabversion
- Tool-Logik in Modulen ohne FastMCP-Import (Ausstieg auf das offizielle SDK möglich), dünne Hüllen im `server`-Modul
- Schichten: `gemini_client` (Adapter hinter kleiner Schnittstelle, austauschbar), `tools` (Logik und Abbildung auf die Ausgabe), `server`
- Start über `mcp.run(transport="http")` bzw. stdio. Waitress oder Gunicorn mit Sync-Workern sind ungeeignet (WSGI, kein Streaming)
- Unit-Tests mit Fake-Gemini-Client und aufgezeichneten echten Antworten, Tool-Aufrufe über den In-Memory-Client von FastMCP, ein Test sichert die FastMCP-Freiheit der Logikmodule ab
- Container mit uv, Scan mit hadolint und Trivy, Images in die GitHub Container Registry

## 8. Arbeitsweise

### 8.1 Repository

Das Repository ist die einzige Quelle für Doku, Code, Tickets und CI. Grobe Struktur:

```text
gemini-search-mcp/
├── README.md, AGENTS.md, CLAUDE.md (importiert AGENTS.md), CONTRIBUTING.md, CHANGELOG.md
├── pyproject.toml, uv.lock, Makefile, compose.yaml, .env.example, .pre-commit-config.yaml
├── src/gemini_search_mcp/   gemini_client/, tools/, server.py, config.py, observability/
├── eval/                    Ground-Truth-Katalog, Judge-Prompt, Auswertung
├── tests/                   unit/, integration/, fixtures/ (aufgezeichnete Antworten)
├── tickets/                 Tnn-titel.md
├── docs/                    adr/, architecture/ (arc42, schlank), techdebt.md, runbook.md
└── .github/                 workflows/, pull_request_template.md, dependabot.yml
```

### 8.2 ADRs

- MADR-Format, `docs/adr/NNNN-titel.md`, Status `proposed`, `accepted`, `superseded`
- Eine Entscheidung je Datei, Alternativen und Begründung immer mit aufführen
- Jede Abweichung von diesem PRD braucht ein ADR

### 8.3 Tickets

Eine Datei je Ticket in `tickets/`, Aufbau wie im ASCOR-PoC:

- Kopf: abhängig von, blockiert, Bereich
- **Ziel**, **Kontext** (welche ADRs lesen), **Vorgaben**, **Nicht im Umfang**, **Akzeptanzkriterien** als Checkliste
- Akzeptanzkriterien sind prüfbar, `make check` grün und Review bestanden gehören immer dazu

### 8.4 Git und Qualität

- Trunk-based, kurze Feature-Branches mit Präfix nach Conventional Commits (`feat/...`, `fix/...`)
- Auf `main` nur per Pull Request nach Review, kein Force-Push bei offenem PR
- PR-Titel nach Conventional Commits, klein geschrieben, mit aussagekräftiger Beschreibung
- Keine Archive oder Binärdateien im Repo
- GitHub Actions nur `actions/*`, eigene und verifizierte Publisher
- Technische Schulden als `TD-NNN` in `docs/techdebt.md`, keine TODO-Kommentare
- Sprache: Doku Deutsch, Code, Kommentare und Commits Englisch

## 9. ADR-Kandidaten

| Nr. | ADR | Inhalt |
| --- | --- | --- |
| 0001 | Rahmen und Ziel | zwei Tools wie nav9v, Nutzwert vor Technik, Nicht-Ziele |
| 0002 | MCP-Framework und Transport | FastMCP 4 gepinnt, Streamable HTTP zustandslos plus stdio, Start über `mcp.run` |
| 0003 | Tool-Vertrag `search` | Ein- und Ausgabeschema, Quellenauflösung, Belegstellen |
| 0004 | Tool-Vertrag `analyze_url` | Schema, `question` Pflicht oder Default, `retrieval_status`, Fehlerfälle |
| 0005 | Ground Truth und Bewertung | Katalog, Metriken, Judge, Schwellenwerte, CI-Umfang |
| 0006 | Gemini-Anbindung | Async-Client, Modellwahl, Timeouts, Retries, Parallelität, Tarif und Datenschutz, Nutzungsbedingungen Grounding |
| 0007 | Fehlerbehandlung und Logging | `isError`, Meldungen, JSON-Logzeile, keine Secrets |
| 0008 | Sicherheit | Auth bei HTTP, URL-Prüfung, Umgang mit Webinhalten (Prompt Injection) |
| 0009 | Backend-Schnittstelle | Abstraktion, die später Serper oder Tavily erlaubt, ohne sie jetzt zu bauen |

## 10. Ticket-Kandidaten (Reihenfolge)

| Nr. | Ticket | Hinweis |
| --- | --- | --- |
| T01 | Repo-Gerüst, Werkzeuge, CI-Grundlage | uv, Ruff, ty, pytest, pre-commit |
| T02 | Ground-Truth-Katalog und Bewertungsskript | **vor jeder Tool-Implementierung** |
| T03 | Baseline-Messung gegen nav9v | Ergebnis als Bericht in `eval/` |
| T04 | Gemini-Adapter (async, Timeouts, Retries) mit Fake für Tests | |
| T05 | Tool `search` inklusive Quellenauflösung und Belegstellen | |
| T06 | Tool `analyze_url` | |
| T07 | Server, Transporte, Health, Logging | |
| T08 | Container, Compose, Auth vor dem Server | |
| T09 | Messung der Neuauflage gegen Baseline und Schwellenwerte | Go/No-Go |
| T10 | Ende-zu-Ende-Test mit echtem Client | |

## 11. Offene Fragen

- Öffentlich betreiben oder nur privat bzw. lokal? Davon hängen Auth und Hosting ab.
- Lizenz und Name des Projekts, Fork oder Neuentwicklung mit Verweis auf nav9v
- Gelten die Git-Regeln aus 8.4 unverändert oder werden sie für ein Hobbyprojekt gelockert?
- Bezahlter oder kostenloser Gemini-Tarif als Standard (Datenschutz, Limits)
- Budget für Eval-Läufe in der CI
- Soll `analyze_url` auf Wunsch zusätzlich den Rohinhalt liefern (Richtung Tavily Extract), oder bleibt es strikt bei der Funktion von nav9v?

## Quellen

- [nav9v/gemini-search-mcp](https://github.com/nav9v/gemini-search-mcp) (README und `gemini_search_mcp.py`)
- Serper.dev: [serper.dev](https://serper.dev), Antwortfelder laut [LangChain-Integration](https://python.langchain.com/docs/integrations/providers/google_serper)
- Tavily: [offizieller Tavily-MCP-Server](https://glama.ai/mcp/servers/@tavily-ai/tavily-mcp/tree/main/src)
- Vorgaben und Muster: ASCOR-MCP-PoC (Repository-Struktur, ADR 0003, 0008, 0010, Ticket T08, `docs/techdebt.md`)
