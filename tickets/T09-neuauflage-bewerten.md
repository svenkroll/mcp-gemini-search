# T09 Neuauflage gegen Baseline bewerten

| | |
| --- | --- |
| Abhängig von | T08 |
| Blockiert | T10 |
| Bereich | eval, quality, release-gate |

## Ziel

Gemini Search MCP gegen denselben Ground-Truth-Katalog und die nav9v-Baseline
bewerten und daraus eine dokumentierte Go/No-Go-Entscheidung ableiten.

## Kontext

Lesen: `AGENTS.md`, ADR 0003 bis 0006 und T02, T03, T05, T06, T08. Die in
ADR 0005 gesetzten Schwellenwerte werden vor dem Lauf nicht verändert.

## Vorgaben

- Modell, Commit, Konfiguration, Tarif, Datum, Rate-Limits und Katalogversion
  im Bericht festhalten.
- Vergleichbare Zeitlimits und Katalogeingaben wie in T03 verwenden.
- Judge mit der dokumentierten manuellen Kalibrierung anwenden.
- Korrektheit, Belegbarkeit, Quellenqualität, Ehrlichkeit, Injection-Resistenz,
  Latenz und Tokens berichten; jede Überschreitung transparent machen.
- Live-Aufrufe manuell starten; keine wiederkehrende Live-CI anlegen.

## Nicht im Umfang

Nachträgliches Optimieren der Grenzwerte, Verschönern des Katalogs nach
Ergebnis, automatisch wiederkehrende Evals oder neue Produktfunktionen.

## Akzeptanzkriterien

- [ ] Der Bericht ist mit T03 direkt vergleichbar und führt jede Metrik aus.
- [ ] Judge-Kalibrierung mit mindestens zwölf Fällen ist dokumentiert.
- [ ] Jeder nicht bestandene Grenzwert enthält einen konkreten Befund und führt
  zu No-Go, nicht zu einer stillen Ausnahme.
- [ ] Der Bericht benennt klar Go oder No-Go und begründet es anhand der Daten.
- [ ] `make check` ist grün und ein unabhängiger Review ist ohne offenen Befund.
