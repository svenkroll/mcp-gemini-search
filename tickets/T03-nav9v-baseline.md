# T03 nav9v-Baseline messen

| | |
| --- | --- |
| Abhängig von | T02 |
| Blockiert | T04 bis T06, T09 |
| Bereich | eval, baseline |

## Ziel

Den festgelegten Ground-Truth-Katalog gegen nav9v ausführen und einen
unveränderlichen Vergleichsbericht im Repository festhalten.

## Kontext

Lesen: `AGENTS.md`, ADR 0003 bis 0006 sowie T02. Diese Messung definiert den
Vergleichswert, nicht die Zielarchitektur.

## Vorgaben

- Vor dem Lauf nav9v-Repository, Commit, Ausführungsdatum, Modell, API-Tarif,
  Konfiguration und Rate-Limits dokumentieren.
- Katalog unverändert nutzen; Auslassungen einzelner Fälle begründen und im
  Bericht sichtbar machen.
- Rohantworten nur speichern, wenn ADR 0006 und Google-Bedingungen es erlauben;
  andernfalls ausschließlich minimierte, zulässige Auswertung speichern.
- Alle Aufrufe sind manuell und budgetbewusst; keine Live-CI.
- Bericht enthält Metriken, Latenz, Tokenwerte soweit vorhanden, bekannte
  Einschränkungen und eine nachvollziehbare Kalibrierungsstichprobe.

## Nicht im Umfang

Änderung von nav9v, Änderung des Katalogs zur Verbesserung der Ergebnisse oder
Implementierung des neuen Servers.

## Akzeptanzkriterien

- [ ] Commit und vollständige Laufkonfiguration sind im Bericht fixiert.
- [ ] Jeder Katalogfall ist als bewertet, übersprungen oder fehlgeschlagen
  nachvollziehbar ausgewiesen.
- [ ] Der Bericht enthält alle ADR-0005-Metriken und die Judge-Kalibrierung.
- [ ] Baseline-Artefakte enthalten keine Schlüssel oder unzulässigen Rohdaten.
- [ ] `make check` ist grün und ein unabhängiger Review ist ohne offenen Befund.
