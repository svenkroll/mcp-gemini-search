# Entscheidungs- und Verifikationskatalog

Stand: 09.11.2026
Zweck: Arbeitsstand vor den ADRs. Produktentscheidungen sind geklärt;
verbleibende Punkte werden gegen Primärdokumentation geprüft, nicht durch
weitere Annahmen ersetzt.

## Bereits entschiedene Produkt- und Betriebsgrenzen

| Themen | Entscheidung |
| --- | --- |
| Betrieb und Zugriff | Öffentliche URL auf einem Kubernetes-Cluster, aber nur für den Besitzer nutzbar. Ein statisches Bearer-Token wird durch den Deployer konfiguriert. Rotation ist nicht Teil des ersten Releases. |
| Infrastruktur | Hinter dem Service stehen Traefik und ein für den Service transparenter HAProxy. Der Container muss eigenständig funktionieren. Lokal kann Caddy als Reverse Proxy dienen. |
| Projekt | Name **Gemini Search MCP**, eigenständige Neuentwicklung unter MIT-Lizenz. nav9v wird als Ideengeber referenziert, nicht geforkt. Die README vergleicht den fachlichen Mehrwert konkret. |
| Zusammenarbeit | Saubere Git- und Pull-Request-Praxis, aber keine formalen Regeln für Mehrpersonen- oder Organisationsprozesse. |
| Ziel-Clients | Ende-zu-Ende-Tests erfolgen mit OpenCode und OpenHands. |
| Gemini | Gemini Developer API mit API-Key aus AI Studio. Standardmodell: Gemini Flash 3.8, mit vor Umsetzung verifizierter Modellkennung. Referenzbetrieb, Baseline und Deployment verwenden den bezahlten Key mit Rechnungskonto; der kostenlose Tarif ist höchstens für direkte AI-Studio-Experimente vorgesehen. |
| Google Search Grounding | Nutzung wie im PRD: Antwort, Quellen, Belegspannen und Suchanfragen werden an den aufrufenden LLM-Workflow weitergegeben. Kein Suchindex, kein dauerhaftes Sammeln von Quelleninhalten, kein Zugang für Dritte und kein Weiterverkauf. URL-Auflösung dient nur der Ergebnisqualität. |
| Eval-Budget | Baseline und Judge-Kalibrierung erhalten das nötige Budget. Wiederkehrende Live-Evals sind nicht Teil des ersten Releases und werden als möglicher späterer Feature Request festgehalten. |

## Tool-Verträge: festgelegte Standardentscheidungen

| IDs | Entscheidung |
| --- | --- |
| F11 | `search.query` wird getrimmt, muss danach nicht leer sein und darf höchstens 4.000 Unicode-Zeichen enthalten. `max_sources` ist optional, Standard 5, Maximum 10. |
| F12, F17 | `search` liefert verwertbare Teilergebnisse. Eine Gemini-Antwort ohne Quellen oder Belege ist kein Tool-Fehler; entsprechende Listen dürfen leer sein. |
| F13 | Belegspannen werden nur mit ausgegeben, wenn Gemini sie liefert. Der Server berechnet oder rekonstruiert keine Positionen. |
| F14 | Nicht auflösbare Quellen werden nicht ausgegeben. Dies ist eine bewusste Abweichung von der PRD-Skizze und wird in ADR 0003 begründet. |
| F15 | `sources[]` enthält jede aufgelöste Ziel-URL höchstens einmal; alle zugehörigen Belege werden in diesem Eintrag gebündelt. |
| F18 | `analyze_url.question` ist Pflicht und darf nach dem Trimmen nicht leer sein. Das verhindert ungerichtete Zusammenfassungen und passt zum Function-Calling-Verhalten der Ziel-Clients. |
| F19, F23 | Ist eine URL nicht abrufbar, ist dies ein `isError`-Fall und es wird keine inhaltsbezogene Antwort erzeugt. Ist sie abrufbar, beantwortet die Seite die Frage aber nicht, bleibt der Aufruf erfolgreich und die Antwort sagt dies ausdrücklich. |
| F21, F22 | Das Tool liefert keinen Rohinhalt. Unterstützt werden HTML und PDF; andere Inhaltsarten erhalten einen eindeutigen Retrieval-Status. |
| F25 bis F27 | Einheitlicher URL-Schutz für Quellenauflösung und `analyze_url`: nur HTTP(S), keine Zugangsdaten in URLs, nur Ports 80/443, höchstens fünf Redirects, Blockade von Loopback-, privaten, Link-Local-, Multicast- und reservierten IPv4/IPv6-Netzen; DNS wird vor jedem Verbindungsziel erneut geprüft. Startwerte: 5 s Verbindung, 15 s Lesen, 30 s Gesamtzeit, höchstens 5 MiB Inhalt. |
| F28, F29 | Webinhalt wird als nicht vertrauenswürdig behandelt. Tool-Beschreibungen und Gemini-Instruktionen verbieten, darin enthaltenen Anweisungen zu folgen. Injection-Tests bestehen nur, wenn keine fremde Anweisung als Handlung, Prioritätswechsel oder unbelegte Aussage in das Ergebnis gelangt. |
| F32, F33 | Konfigurierbare Startwerte: 60 s Gemini-Gesamtzeit, zwei Wiederholungen nach dem Erstversuch, exponentielles Backoff mit Zufallsanteil, maximal vier parallele Gemini-Aufrufe. Wiederholt werden nur 429 und transiente 5xx-Fehler; `Retry-After` wird beachtet. Bei Client-Abbruch wird nicht weitergearbeitet. |
| F34 | Tokenwerte kommen ausschließlich aus der API-Nutzungsmetrik. Fehlen sie, werden sie als unbekannt protokolliert, nicht geschätzt. |
| F38 bis F40 | Ungültige Eingaben, URL-Sicherheitsverstöße und fehlgeschlagene Abrufe sind `isError` mit kurzer eigener Meldung. Quellenverlust nach einer sonst erfolgreichen Suche ist kein Fehler. `structuredContent` ist kanonisch; die Textausgabe ist dessen semantisch identische JSON-Darstellung. |
| F41 bis F43 | Der Server erzeugt Request-IDs selbst. JSON-Logs gehen nach stdout; Query-Inhalte sind standardmäßig deaktiviert und nur ausdrücklich konfigurierbar. Aufbewahrung liegt bei der Cluster-Infrastruktur. Liveness prüft den Prozess, Readiness ausschließlich valide und geladene Konfiguration, niemals einen kostenpflichtigen Upstream-Aufruf. |

## Ground Truth und Qualität: festgelegte Arbeitsgrundlage

| IDs | Entscheidung |
| --- | --- |
| F44, F45 | Der erste Katalog enthält mindestens 40 versionierte YAML-Fälle: stabile und aktuelle Fakten, technische Dokumentation, Deutsch/Englisch, ehrliches Nichtwissen sowie HTML, PDF, Ausfall und Prompt Injection für `analyze_url`. Jeder Fall enthält Frage, erwartete Kernaussage, erlaubte Quellen/Domains, Kategorie, Ground-Truth-Stichtag und bei URL-Fällen die Test-URL. Kontrollierte Injection-Fälle werden als eigene, reproduzierbare Testressource betrieben. |
| F46 | Die Bewertung nutzt binäre, begründete Einzelurteile je Fall: Kernaussage korrekt, mindestens ein Beleg stützt sie, Quelle ist eine erreichbare echte Ziel-URL, Nichtwissen ist ehrlich, Injection blieb wirkungslos. Latenz und Tokens werden numerisch erfasst. |
| F47 | Vor dem ersten Ergebnis gelten: 100 % für Ehrlichkeit und Injection-Resistenz, mindestens 90 % für Quellenqualität, mindestens 85 % für Korrektheit und Belegbarkeit. Die Neuauflage darf die jeweilige nav9v-Baseline nicht unterschreiten. Nicht erreichte Grenzen sind Go/No-Go, keine nachträgliche Anpassung. |
| F48, F49 | Der Judge verwendet das gepinnte, vom Produktmodell getrennte `gemini-3.7-flash` und einen versionierten Prompt. Vor Einsatz wird er an mindestens zwölf über Kategorien verteilten Fällen manuell kalibriert; bei mehr als einer abweichenden Kernbewertung wird Prompt oder Rubrik überarbeitet und erneut kalibriert. |
| F50 | Für die Baseline wird vor dem Lauf ein konkreter nav9v-Commit, Modell, Konfiguration und Zeitpunkt festgehalten. Beide Varianten erhalten denselben Katalog und vergleichbare Limits. |
| F51, F52 | CI führt nur Offline-Unit-Tests mit kontrollierten Fixtures aus. Live-Baseline, Kalibrierung und spätere Vergleichsmessungen sind manuelle, budgetierte Schritte. Zeitabhängige Ground Truth wird bei jedem solchen Lauf vorab überprüft und mit neuem Stichtag versioniert. |

## Architektur und Lieferung: festgelegte Arbeitsgrundlage

| IDs | Entscheidung |
| --- | --- |
| F08 bis F10 | HTTP stellt `/mcp`, `/health/live` und `/health/ready` bereit; nur die Health-Endpunkte sind ohne Bearer-Token erreichbar. HTTP bleibt zustandslos, stdio benötigt keine HTTP-Authentisierung. Proxy-Timeouts werden für lang laufende Streamable-HTTP-Aufrufe dokumentiert. |
| F53 | Die Provider-Grenze umfasst nur die fachlichen Operationen `search` und `analyze_url` sowie normalisierte Ergebnis- und Fehlerdaten. Gemini-spezifische Antworttypen verlassen den Adapter nicht. |
| F54 | Python 3.14, Linux-Container für `linux/amd64` und `linux/arm64`; alle direkten Abhängigkeiten werden exakt gepinnt. Kompatibilität der endgültigen Pakete wird vor der Umsetzung geprüft. |
| F55 | Die 80-Prozent-Abdeckung gilt für `src/gemini_search_mcp/`, einschließlich Adapter, Tool-Logik, Serverhüllen und Observability. Eval-Skripte werden separat durch gezielte Tests abgesichert, aber nicht künstlich in diese Quote eingerechnet. |
| F56 | Unit-Fixtures enthalten keine API-Schlüssel, privaten Inhalte oder unredigierten Live-Verläufe. Bevorzugt werden handgefertigte, API-getreue Antworten; aufgezeichnete Antworten werden nur verwendet, wenn Lizenz- und Speicherbedingungen dies erlauben und sie vor dem Commit geprüft wurden. |
| F57 | Images werden in GHCR publiziert, mit `uv` gebaut und per Hadolint sowie Trivy geprüft. Basis ist ein schlankes offizielles Python-Image; kritische und hohe, behebbare Schwachstellen blockieren die Veröffentlichung. |

## Verifiziert und noch zu verifizieren

Diese Punkte brauchen keine weitere Produktentscheidung. Ihr Ergebnis wird in den
jeweiligen ADR geschrieben und kann eine bereits gewählte technische Ausprägung
präzisieren, nicht aber den Umfang still verändern.

| IDs | Verifikation |
| --- | --- |
| F07 | **Teilweise verifiziert:** FastMCP 4.1.6 ist aktuell die stabile 4.x-Version; keine 4.2-Vorabversion verwenden. FastMCP 4 unterstützt die Protokollverhandlung zwischen 2026-07-28 und älteren Clients. Die tatsächliche OpenHands-Kompatibilität wird im E2E-Test bestätigt. Die exakte `google-genai`-Version wird erst beim Lockfile-Erstellen festgelegt. |
| F16 | **Verifiziert:** Search Grounding liefert `url_citation`-Annotationen mit Titel, URL sowie Start-/Endindex, `google_search_call` mit ausgeführten Anfragen und `google_search_result` mit Suggestions. Der neue Vertrag richtet sich daran aus, nicht an die älteren `groundingSupports`-Felder. Die aktuelle Dokumentation zeigt direkte Ziel-URLs; Verhalten alter nav9v-Redirects wird in der Baseline gemessen. |
| F20, F24 | **Verifiziert:** URL Context liefert je Abruf einen `url_context_result` mit Status und abgerufener URL. Gemini 3.8 Flash unterstützt URL Context; PDF wird als Inhaltsart unterstützt. |
| F31 | **Verifiziert:** stabile Kennung `gemini-3.8-flash`, veröffentlicht am 02.09.2026, ohne angekündigtes Abschaltdatum. Search Grounding und URL Context sind unterstützt. |
| F35, F36 | **Teilweise verifiziert:** Der kostenlose Tarif darf Eingaben und Ausgaben zur Produktverbesserung nutzen, der bezahlte Tarif nicht. Der bezahlte Gemini-3-Betrieb erhält 5.000 kostenlose Search-Requests pro Monat, modellübergreifend; danach kosten sie 14 USD je 1.000 Requests, bei einem Standardlimit von 1.500 Requests pro Projekt und Tag. Ein Nutzerprompt kann mehrere Search-Requests auslösen. Google Search Grounding speichert Prompt, Kontext und Ausgabe dennoch 30 Tage für Grounding-Zwecke. Die Nutzungs- und Attributionsbedingungen werden im ADR mit Datum und Primärquelle festgehalten. |
| F54, F57 | FastMCP 4.1.x unterstützt Python 3.14; endgültige Multi-Architektur-Kompatibilität wird nach dem Erzeugen des Lockfiles im Container-Build geprüft. |

## Ergebnis

Es bleiben keine offenen Produktfragen, die vor dem Schreiben der ADRs noch
beantwortet werden müssen. Der nächste Arbeitsschritt ist die dokumentierte
Verifikation der aufgeführten externen Fakten; danach können die neun ADRs ohne
weitere Grundsatzentscheidungen geschrieben werden.
