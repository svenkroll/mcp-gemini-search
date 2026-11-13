# URL verification 2026-11-13

Live verification of every `analyze_url` case in `eval/cases/` against Gemini
URL Context, as required by ADR 0005 ("Test resources"). Each URL was checked
twice with the exact question of its case through the real `analyze_url` path
(`GeminiProvider` + `run_analyze_url`). `expected` was verified against the
document text itself (downloaded HTML, PDF via `pdftotext`), not against the
model answer.

## Record format

`check.jsonl` holds the complete checker output of this session, accepted and
rejected candidates, in the order of invocation:

- `{"record": "invocation", "seq", "utc", "repeat", "question", "urls"}`
  precedes the attempt lines of one checker invocation. The checker does not
  print the question, so this line was added by the wrapper script.
- attempt lines are printed by the checker unchanged: `url`, `attempt`,
  `outcome` (`ok` or the error code), `reported_url`, `retrievals`
  (`[url, status]` as reported by Gemini), `tokens`, `answer` (truncated to
  600 characters).
- `{"record": "crash"}` marks invocations 002 to 004: the checker read
  `result.url`, but `run_analyze_url` returns the URL as `result.output.url`,
  so it raised on the first successful retrieval and printed nothing. From
  invocation 005 on the unmodified checker ran behind a shim that exposes
  that attribute; 005 to 007 repeat 002 to 004 completely.

Invocations 001 and 005 to 007 are probes with the checker's default question
("What is the title of this document?"). Invocations 008 to 022 use case
questions.

## Final cases

All final cases: no redirect on a direct request (HTTP 200, or 404 for the
failure paths), both attempts on the same question.

| id | url | host | attempt 1 | attempt 2 | seq | where `expected` is stated |
| --- | --- | --- | --- | --- | --- | --- |
| analyze-url-html-001 | `https://toml.io/en/v1.0.0` | toml.io | ok | ok | 008 | section "Integer", last paragraph |
| analyze-url-html-002 | `https://spec.commonmark.org/0.31.2/` | spec.commonmark.org | ok | ok | 019 | section 2.2 "Tabs", first paragraph |
| analyze-url-html-003 | `https://www.conventionalcommits.org/en/v1.0.0/` | www.conventionalcommits.org | ok | ok | 010 | section "Specification", item 16 |
| analyze-url-html-004 | `https://keepachangelog.com/en/1.1.0/` | keepachangelog.com | ok | ok | 011 | nowhere (`honest_unknown`): the page text contains none of "encoding", "UTF", "charset", "Unicode", "ASCII" |
| analyze-url-pdf-001 | `https://arxiv.org/pdf/1412.6980v9` | arxiv.org | ok | ok | 012 | section 7.1, caption of Algorithm 2 (AdaMax) |
| analyze-url-pdf-002 | `https://arxiv.org/pdf/1706.03762v7` | arxiv.org | ok | ok | 013 | section 5.3 "Optimizer", after equation (3) |
| analyze-url-pdf-003 | `https://nvlpubs.nist.gov/nistpubs/FIPS/NIST.FIPS.197-upd1.pdf` | nvlpubs.nist.gov | ok | ok | 014 | announcement, item 9 "Implementation Schedule" |
| analyze-url-pdf-004 | `https://nvlpubs.nist.gov/nistpubs/fips/nist.fips.186-5.pdf` | nvlpubs.nist.gov | ok | ok | 021 | announcement, item 12 "Implementation Schedule" |
| analyze-url-failure-001 | `https://toml.invalid/en/v1.0.0` | toml.invalid | url_unreachable | url_unreachable | 016 | n/a: reserved `.invalid` domain |
| analyze-url-failure-002 | `https://toml.io/en/v9.9.9` | toml.io | url_unreachable | url_unreachable | 017 | n/a: non-existent HTML path (HTTP 404) on the host of html-001 |
| analyze-url-failure-003 | `https://nvlpubs.nist.gov/nistpubs/FIPS/NIST.FIPS.999.pdf` | nvlpubs.nist.gov | url_unreachable | url_unreachable | 018 | n/a: non-existent PDF path (HTTP 404) on the host of pdf-003 and pdf-004 |

In every accepted `ok` attempt `reported_url` equals the requested URL and
the answer states `expected`. The eight html/pdf cases use six hosts, at most
two cases per host.

`analyze-url-html-004` keeps its former role as the `honest_unknown` URL case:
its question is deliberately not answerable from the document, and both
answers say so.

## Rejected candidates

| url | seq | outcomes | reason |
| --- | --- | --- | --- |
| `https://semver.org/spec/v2.0.0.html` | 001 | url_unreachable ×2 | Gemini retrieved `https://semver.org/` instead; requested URL `failed` |
| `https://www.w3.org/TR/2008/REC-xml-20081126/` | 001 | url_unreachable ×2 | Gemini retrieved the undated `https://www.w3.org/TR/xml/` instead |
| `https://www.w3.org/TR/2021/REC-webauthn-2-20210408/` | 006 | url_unreachable ×2 | Gemini retrieved the undated `https://www.w3.org/TR/webauthn-2/` instead |
| `https://en.wikipedia.org/w/index.php?title=Raft_(algorithm)&oldid=1180000000` | 005 | url_unreachable ×2 | retrieval `failed` |
| `https://262.ecma-international.org/14.0/` | 006 | url_unreachable ×2 | Gemini retrieved `.../14.0/index.html` instead |
| `https://proceedings.mlr.press/v37/ioffe15.pdf` | 007 | url_unreachable ×2 | Gemini retrieved a copy on `static.googleusercontent.com` instead |
| `https://www.usenix.org/system/files/conference/atc14/atc14-paper-ongaro.pdf` | 007 | url_unreachable ×2 | Gemini retrieved `files.usenix.org/...` instead |
| `https://www.jmlr.org/papers/volume15/srivastava14a/srivastava14a.pdf` | 007 | url_unreachable ×2 | Gemini retrieved a copy on `www.cs.toronto.edu` instead |
| `https://nvlpubs.nist.gov/nistpubs/FIPS/NIST.FIPS.180-4.pdf` | 015 | url_unreachable ×2 | Gemini retrieved the lower-case path `.../fips/nist.fips.180-4.pdf` instead |
| `https://nvlpubs.nist.gov/nistpubs/FIPS/NIST.FIPS.186-5.pdf` | 020 | url_unreachable ×2 | same lower-case rewrite; the lower-case URL itself passed (021) and is used |
| `https://nvlpubs.nist.gov/nistpubs/FIPS/NIST.FIPS.203.pdf` | 022 | url_unreachable ×2 | same lower-case rewrite |
| `https://spec.commonmark.org/0.31.2/` with the question "How many digits can an ordered list marker contain according to this specification?" | 009 | ok ×2 | answers do not state `expected`: the content Gemini received was truncated at section 4.6, the statement is in section 5.2. URL kept with a question on section 2.2 (019) |
| `https://arxiv.org/abs/1412.6980v9` | 005 | ok ×2 | retrievable, not used: at most two cases per host and arxiv.org serves both PDF cases |
| `https://yaml.org/spec/1.2.2/` | 005 | ok ×2 | retrievable, not used: very long document, truncation risk as seen in 009; only probed with the default question |
| `https://keepachangelog.com/en/1.1.0/`, `https://www.conventionalcommits.org/en/v1.0.0/`, `https://toml.io/en/v1.0.0`, `https://arxiv.org/pdf/1412.6980v9`, `https://nvlpubs.nist.gov/nistpubs/FIPS/NIST.FIPS.197-upd1.pdf` | 005 to 007 | ok ×2 | probe only (default question); accepted later with the case question |
| `https://www.gnu.org/licenses/gpl-3.0.html` | 006 | ok ×2 | retrievable, not used: no version or revision in a form the publisher guarantees for the page as a whole |
| `https://aclanthology.org/N19-1423.pdf` | 007 | ok ×2 | retrievable, not used: a revised paper can replace the file at this URL |

## Observations

- `nvlpubs.nist.gov` is case-sensitive on Gemini's side in an unpredictable
  way: for three of four mixed-case FIPS URLs Gemini reported the lower-case
  path, which the tool correctly rejects (ADR 0004). Only
  `NIST.FIPS.197-upd1.pdf` was retrieved under its mixed-case URL, in four of
  four attempts (007, 014).
- Long HTML documents are truncated by URL Context. A case on a long document
  must ask about content near the beginning.
