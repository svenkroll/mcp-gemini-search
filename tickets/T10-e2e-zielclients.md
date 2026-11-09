# T10 Ende-zu-Ende-Test mit Ziel-Clients

| | |
| --- | --- |
| Abhängig von | T08, T09 |
| Blockiert | nichts |
| Bereich | e2e, compatibility, documentation |

## Ziel

Mit OpenCode und OpenHands nachweisen, dass beide Ziel-Clients den MCP-Server
über den vorgesehenen Transport nützlich, sicher und verständlich verwenden.

## Kontext

Lesen: `AGENTS.md`, ADR 0002 bis 0008 sowie T08 und T09. Dieser Test prüft
den Nutzen im Agentenworkflow, nicht nur die direkte Gemini-Antwort.

## Vorgaben

- Für beide Clients die dokumentierte Remote-HTTP-Konfiguration mit Bearer-Token
  testen; stdio bei Bedarf als lokaler Ergänzungstest dokumentieren.
- Je Client mindestens `search`, erfolgreiches `analyze_url`, Abruffehler,
  ungültige Eingabe und Prompt-Injection-Testfall ausführen.
- Prüfen, dass strukturierte Ergebnisse, Quellen und Fehler für den Agenten
  verwertbar erscheinen und keine Server-Instructions als Fremdanweisung wirken.
- Tatsächlich ausgehandelte MCP-Protokollrevision, Client-Version, Konfiguration
  ohne Geheimnisse und Ergebnisnotizen im Bericht festhalten.

## Nicht im Umfang

Automatisierung gegen Fremdkonten, Test anderer Clients, Funktionsausbau wegen
eines einzelnen Clients oder Änderungen an Qualitätsgrenzen.

## Akzeptanzkriterien

- [ ] OpenCode verbindet sich mit dem geschützten HTTP-Endpunkt und ruft beide
  Tools erfolgreich auf.
- [ ] OpenHands verbindet sich mit dem geschützten HTTP-Endpunkt und ruft beide
  Tools erfolgreich auf.
- [ ] Beide Clients erkennen mindestens einen Tool-Fehler statt ihn als Antwort
  zu behandeln.
- [ ] Der Bericht zeigt, wie Quellen und strukturierte Inhalte im Agentenfluss
  genutzt wurden.
- [ ] Keine API-Keys oder Bearer-Tokens erscheinen in Konfiguration, Bericht
  oder Screenshots.
- [ ] `make check` ist grün und ein unabhängiger Review ist ohne offenen Befund.
