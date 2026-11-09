# T06 Tool `analyze_url`

| | |
| --- | --- |
| Abhängig von | T04 |
| Blockiert | T07, T09 |
| Bereich | tools, url-security, tests |

## Ziel

Die fachliche `analyze_url`-Logik implementieren, die nur nach bestätigtem
Abruf einer öffentlichen HTML- oder PDF-URL eine inhaltsbezogene Antwort gibt.

## Kontext

Lesen: `AGENTS.md`, ADR 0004 bis 0008 und T04. Die Frage ist Pflicht; ein
fehlender Abruf darf nie als Modellwissen über die URL erscheinen.

## Vorgaben

- URL und Frage validieren; die Frage ist getrimmt, nicht leer und höchstens
  4.000 Zeichen lang.
- Die komplette URL-Policy aus ADR 0008 vor jedem Zugriff und Redirect anwenden.
- Gemini URL Context über den Adapter nutzen und `url_context_result` auf
  bestätigten Abruf, unterstützten Inhalt und Sicherheitsstatus abbilden.
- Bei Erfolg Antwort, abgerufene URL und `retrieval_status: "retrieved"`
  liefern; kein Rohinhalt.
- Bei Abruffehler, Unsafe-Status oder nicht unterstütztem Inhalt einen
  normalisierten Tool-Fehler liefern, ohne Gemini-Antwort als Seiteninhalt.

## Nicht im Umfang

Allgemeiner Downloadservice, Portfreigaben über ADR 0008 hinaus, Raw-Content-
Ausgabe, Browser-Automatisierung oder FastMCP-Registrierung.

## Akzeptanzkriterien

- [ ] Tests decken HTML, PDF, nicht erreichbare URL, Unsafe-Status,
  nicht unterstützten Inhalt, SSRF-Muster und leere Frage ab.
- [ ] Bei jedem fehlgeschlagenen Abruf fehlt eine inhaltsbezogene Antwort.
- [ ] Bei beantwortbarer und nicht beantwortbarer Frage ist der Unterschied
  für Clients eindeutig.
- [ ] Modul bleibt ohne FastMCP importierbar.
- [ ] `make check` ist grün und ein unabhängiger Review ist ohne offenen Befund.
