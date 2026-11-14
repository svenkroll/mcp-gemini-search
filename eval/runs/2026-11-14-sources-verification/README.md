# Verification of the `-sources` variants, 2026-11-14

Manual step of issue #36 (pull request #39): every `-sources` variant was run
once against the live Gemini Developer API with
`.issue-drafts/search_summary.py`, model `gemini-3.8-flash`. One file per
variant, `<case id>.txt`, holds the summary of that run.

The script asks for `max_sources=10`; the server default is 5. Where an
allowed host only appears after position 5, this is noted below.

## Result

All 26 variants ran a Google Search (`grounding` is never `NONE`), and all 26
returned at least one host within the chosen `allowed_sources`. `draft: true`
was removed from all 26 case files.

Hosts in bold lie within `allowed_sources`.

| Variant | Grounding | Returned hosts | Chosen `allowed_sources` | Source quality |
| --- | --- | --- | --- | --- |
| `search-current-001-sources` | google_search=2 | **www.python.org**, **devguide.python.org** | `python.org` | pass |
| `search-current-002-sources` | google_search=2 | **www.debian.org**, **wiki.debian.org** | `debian.org` | pass |
| `search-current-003-sources` | google_search=2 | **releases.ubuntu.com**, **ubuntu.com** | `ubuntu.com`, `canonical.com` | pass |
| `search-current-004-sources` | google_search=2 | **www.oracle.com** | `oracle.com`, `openjdk.org`, `jdk.java.net` | pass |
| `search-current-005-sources` | google_search=2 | **www.unicode.org**, **blog.unicode.org** | `unicode.org` | pass |
| `search-current-006-sources` | google_search=2 | hidekazu-konishi.com, cognision.eu, safeguard.sh, **nodejs.org**, github.com, www.flowverify.co | `nodejs.org` | pass |
| `search-english-001-sources` | google_search=2 | **www.rfc-editor.org**, emailauth.io | `rfc-editor.org`, `ietf.org` | pass |
| `search-english-002-sources` | google_search=2 | **www.rfc-editor.org**, **datatracker.ietf.org** | `rfc-editor.org`, `ietf.org` | pass |
| `search-english-003-sources` | google_search=2 | **www.cisa.gov**, www.cybersecuritydatabase.org | `cisa.gov` | pass |
| `search-english-004-sources` | google_search=1 | **www.first.org**, casrai.org | `first.org` | pass |
| `search-german-001-sources` | google_search=3 | docs.oracle.com, manual.mikrotik.com, **www.rfc-editor.org**, www.arc-it.net, ipv6now.com.au | `rfc-editor.org`, `ietf.org` | pass |
| `search-german-002-sources` | google_search=1 | **www.rfc-editor.org**, en.wikipedia.org | `rfc-editor.org`, `ietf.org` | pass |
| `search-german-003-sources` | google_search=2 | dnscale.eu, tex2e.github.io, www.infoblox.com, **www.rfc-editor.org** | `rfc-editor.org`, `ietf.org` | pass |
| `search-german-004-sources` | google_search=2 | **e-rechnung-bund.de**, www.ihk.de, **ec.europa.eu** | `bundesfinanzministerium.de`, `gesetze-im-internet.de`, `xeinkauf.de`, `e-rechnung-bund.de`, `ec.europa.eu` | pass |
| `search-stable-001-sources` | google_search=2 | **www.rfc-editor.org**, **datatracker.ietf.org** | `rfc-editor.org`, `ietf.org` | pass |
| `search-stable-002-sources` | google_search=2 | **physics.nist.gov**, en.wikipedia.org, **www.bipm.org** | `bipm.org`, `nist.gov` | pass |
| `search-stable-003-sources` | google_search=2 | **www.ecb.europa.eu**, **eur-lex.europa.eu** | `ecb.europa.eu`, `eur-lex.europa.eu`, `european-union.europa.eu` | pass |
| `search-stable-004-sources` | google_search=1 | **cyprus.representation.ec.europa.eu**, www.brightlms.eu | `ec.europa.eu`, `european-union.europa.eu` | pass |
| `search-stable-005-sources` | google_search=2 | **home.cern**, www.timeline-explorer.com, ifs.uoregon.edu, **www.w3.org**, apice.unibo.it, **info.cern.ch** | `home.cern`, `cern.ch`, `w3.org` | pass |
| `search-stable-006-sources` | google_search=2 | en.wikipedia.org, **physics.nist.gov**, farmonaut.com, www.preciousmetalprices.com | `iupac.org`, `nist.gov`, `pubchem.ncbi.nlm.nih.gov` | pass |
| `search-techdocs-001-sources` | google_search=8 | **docs.python.org** | `docs.python.org` | pass |
| `search-techdocs-002-sources` | google_search=2 | **kubernetes.io** | `kubernetes.io` | pass |
| `search-techdocs-003-sources` | google_search=2 | **www.postgresql.org** | `postgresql.org` | pass |
| `search-techdocs-004-sources` | google_search=1 | **peps.python.org**, flaviocopes.com | `peps.python.org` | pass |
| `search-techdocs-005-sources` | google_search=6 | **git-scm.com** | `git-scm.com` | pass |
| `search-techdocs-006-sources` | google_search=1 | **developer.mozilla.org** | `developer.mozilla.org` | pass |

## Changes to the proposed `allowed_sources`

| Variant | Proposed in the pull request | Chosen | Reason |
| --- | --- | --- | --- |
| `search-current-004-sources` | `oracle.com`, `openjdk.org`, `java.net` | `oracle.com`, `openjdk.org`, `jdk.java.net` | only `jdk.java.net` is the publisher's download site |
| `search-german-004-sources` | `bundesfinanzministerium.de`, `gesetze-im-internet.de`, `xeinkauf.de` | added `e-rechnung-bund.de`, `ec.europa.eu` | none of the proposed hosts came back in three runs; these two official hosts did |
| `search-stable-003-sources` | `europa.eu` | `ecb.europa.eu`, `eur-lex.europa.eu`, `european-union.europa.eu` | narrowed to the institutions that publish the fact |
| `search-stable-004-sources` | `europa.eu` | `ec.europa.eu`, `european-union.europa.eu` | narrowed to the institutions that publish the fact |
| `search-stable-006-sources` | `iupac.org`, `nist.gov`, `nih.gov` | `iupac.org`, `nist.gov`, `pubchem.ncbi.nlm.nih.gov` | `nih.gov` would accept any PubMed/PMC article |
| `search-techdocs-001-sources` | `python.org` | `docs.python.org` | the question names the documentation |
| `search-techdocs-004-sources` | `python.org` | `peps.python.org` | the question names PEP 8 |
| `search-techdocs-006-sources` | `mozilla.org` | `developer.mozilla.org` | the question names MDN Web Docs |

The other 18 variants keep the proposed list.

## Changed question: `search-techdocs-001`

The original question ("According to the Python 3.14 documentation of
built-in functions, what does len() return?") returned `docs.python.org` in
only one of three runs with the sources suffix; the other two returned copies
and third-party pages only (`old-techdocs-001-len/`).

Three replacement questions were probed three times each
(`probes-techdocs-001/`); all nine runs returned `docs.python.org`. The
`json.dumps()` question was chosen. Because a variant must share query and
`expected` with its base, the base case `search-techdocs-001.yaml` was changed
as well. `search-techdocs-001-sources.txt` is the first probe run of the new
question. The result of `search-techdocs-001` in
`eval/runs/2026-11-14-release1/` refers to the old question.

## Variants that pass narrowly

One run per variant is not a stability measurement. These variants passed
through a single allowed host among several third-party hosts and may fail in
a full run:

- `search-current-006-sources`: `nodejs.org` was one of six hosts, at
  position 4. The release schedule itself lives in `github.com/nodejs/release`,
  which cannot be allowed because the check works on domains only.
- `search-german-004-sources`: `e-rechnung-bund.de` came back in three of
  three runs (`search-german-004-sources.rerun2.txt`, `.rerun3.txt`), but in
  the third run only at position 10 of 10, beyond the server default of 5.
- `search-stable-006-sources`: `physics.nist.gov` was one of four hosts.
- `search-german-001-sources`, `search-german-003-sources`: `rfc-editor.org`
  was one of five and one of four hosts.
