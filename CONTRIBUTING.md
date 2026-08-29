# Contributing

Thanks for looking at this. The project has one rule that outranks every other
consideration, including convenience, coverage numbers and code style.

## The rule

**Never invent a rate, a rate structure, a time window, or a citation.**

Every value the parser emits must be traceable to a specific published
document, page, section and line. If a change would make the parser emit a
number that no publisher printed, the change is wrong even if the tests pass
and even if the number looks right.

Practical consequences for a pull request:

- If a recognizer cannot read something with certainty, it must emit nothing
  and let the line surface as unparsed. A guess is never better than a gap.
- Do not widen a regex or a tolerance to raise the coverage figure. Coverage is
  a report on what the parser understood, not a target to hit.
- Do not add a fallback that fills in a missing unit, date or time.
- New refusals need a test that proves the refusal, not just one that proves
  the happy path.

## Before you open a pull request

```bash
make verify
```

`make verify` installs the locked dependency set, lints, type checks, and runs
the tests against the coverage floor. It must exit 0.

## Working on a recognizer

- Recognizers live in `src/ca_tariff_parse/recognizers/`. Each one claims a
  section shape and reports exactly which lines it consumed. Lines it does not
  consume become `unparsed` entries automatically, so a partial understanding
  is visible rather than silent.
- Test fixtures must be clearly synthetic. Put `SYNTHETIC` in the filename and
  in the document text, and use values no utility would publish. Do not paste a
  real tariff into a fixture.
- The real published PDFs are not committed. Run `make fetch` to download them
  and `make verify-source` to confirm the digests still match.

## Changing parsed output

`tests/golden/` holds the committed output of parsing the real schedules. If a
change alters it:

```bash
make fetch
make golden
```

Then **read every changed price** in the diff before committing. A golden
update is the moment a parser bug becomes a published wrong number, so it gets
reviewed line by line rather than accepted wholesale.

## Adding or changing a document profile

`src/ca_tariff_parse/profiles.py` holds the per-document profiles, and a
manifest entry names one with a `profile` key. A profile may only carry
something a document genuinely cannot state about itself. Before adding a
field, write the paragraph that says why the page does not answer the question,
and if you cannot write it, the answer belongs in a recognizer reading the
document instead.

In particular a profile holds no coordinate. A position in a profile is the
mistake ADR 0004 removed from the recognizers, put back one layer up. See ADR
0006 for what that cost when it was tried.

Every field needs a refusing default, so that a document naming no profile is
refused rather than guessed at, and a test that proves the refusal.

## Adding a source document

Add an entry to `sources/sources.toml` with the publisher, URL, retrieval date,
page count, byte size and SHA-256, plus a `profile` if the publisher needs one.
Fetch politely: check `robots.txt`, take what you need, and cache it. Do not
crawl a publisher's site.

Listing a document is a statement about where it came from. It is not a claim
of permission or endorsement, and nothing in this project may imply
affiliation with a utility.

## Reporting a problem

A wrong or uncited value is the most serious kind of bug here. Please include
the document, the page and section, what was emitted, and what the document
actually says. For anything with a security dimension see `SECURITY.md`.

The issue forms ask for exactly that, and there is a second one for a shape
the parser does not read yet, which asks what on the page settles the reading.
Opening a pull request loads the checklist above as a template.
