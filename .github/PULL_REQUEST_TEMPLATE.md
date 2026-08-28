## What this reads, or refuses

<!-- One or two sentences. If it refuses something, say what and why the page
     does not settle it. -->

## Checklist

- [ ] `make verify` passes locally
- [ ] If `tests/golden/` changed, every changed price was read, not just diffed
- [ ] A new refusal has a test proving the refusal, not only the happy path
- [ ] No regex or tolerance was widened to raise a coverage figure
- [ ] New fixtures are clearly synthetic: `SYNTHETIC` in the filename and in
      the text, and values no utility would publish
- [ ] No real tariff document was pasted into a fixture or committed

## Coverage

<!-- If a coverage figure moved, paste the before and after from
     `make coverage-real`, and say which shape accounts for the difference. -->
