"""The parse engine.

Runs every recognizer over every section, then accounts for what is left. The
accounting is the point: a line no recognizer consumed is reported as unparsed
and its text is still carried in ``notes``, so a caller can always see what the
parser did not understand rather than having to trust that nothing was missed.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from .audit import assert_fully_cited
from .extract import LayoutDoc, layout_from_path
from .model import (
    Cited,
    Coverage,
    ParsedSchedule,
    SourceDocument,
    UnparsedSection,
)
from .profiles import DEFAULT, DocumentProfile, resolve
from .recognizers import (
    applicability,
    billing_periods,
    condition_list,
    credit,
    cross_reference,
    dated_charge,
    header,
    proration,
    rate_table,
    sheet_rates,
    transition_table,
)
from .recognizers.base import Citer, Emission
from .segment import Section, segment
from .sources import SourceEntry

PARSER_VERSION = "0.1.0"

#: Lines a recognizer left behind are sampled into the unparsed report, capped
#: so a wholly unrecognised document does not produce an unbounded output.
UNPARSED_SAMPLE = 4


def _reason(consumed: int, total: int) -> str:
    if not consumed:
        return "no recognizer claimed this section"
    return f"{total - consumed} of {total} lines in a recognized section matched no rule"


def _run_recognizers(
    sections: list[Section],
    citer: Citer,
    effective: Cited[str] | None,
    profile: DocumentProfile,
    effective_by_page: dict[int, Cited[str]],
) -> Emission:
    headings = {section.section_id: section.heading for section in sections if section.level == 1}
    combined = Emission()
    # Each shape decides independently whether it claims a section; a shape
    # that does not is simply skipped, so this is a flat, data driven list
    # rather than a chain of branches that grows harder to read with every
    # new recognizer.
    shapes: list[tuple[Callable[[Section], bool], Callable[[Section], Emission]]] = [
        (rate_table.claims, lambda s: rate_table.parse(s, citer)),
        (
            lambda s: sheet_rates.claims(s, profile),
            lambda s: sheet_rates.parse(s, citer, profile, effective_by_page),
        ),
        (transition_table.claims, lambda s: transition_table.parse(s, citer, profile)),
        (dated_charge.claims, lambda s: dated_charge.parse(s, citer)),
        (credit.claims, lambda s: credit.parse(s, citer, effective)),
        (billing_periods.claims, lambda s: billing_periods.parse(s, citer)),
        (cross_reference.claims, lambda s: cross_reference.parse(s, citer)),
        (lambda s: applicability.claims(s, headings), lambda s: applicability.parse(s, citer)),
        (lambda s: proration.claims(s, citer.doc), lambda s: proration.parse(s, citer)),
        (condition_list.claims, lambda s: condition_list.parse(s, citer)),
    ]
    for section in sections:
        for claims, parse in shapes:
            if claims(section):
                combined.extend(parse(section))
    return combined


def parse_document(
    doc: LayoutDoc,
    *,
    source: SourceDocument | None = None,
    profile: DocumentProfile = DEFAULT,
) -> ParsedSchedule:
    """Parse a layout document into a fully cited schedule."""
    citer = Citer(doc)
    segmented = segment(doc, profile)

    identity, front_consumed = header.parse_identity(doc, citer, profile)
    emission = _run_recognizers(
        segmented.sections,
        citer,
        identity.effective,
        profile,
        header.sheet_effective_dates(doc, citer),
    )
    emission.consumed |= front_consumed

    # Segmentation itself understands a heading: it is what produced the
    # section id every citation in that section points at. Counting it as
    # unrecognised would make the coverage figure measure the outline rather
    # than the body, which is the part a reader actually needs accounted for.
    # A heading set inline gets no such credit: the same line carries the body
    # of the part, and crediting it would count text nobody has read.
    for section in segmented.sections:
        if section.level > 0 and section.content_lines and not section.heading_inline:
            emission.take(section.content_lines[0])

    unparsed: list[UnparsedSection] = []
    recognized_lines = 0
    sections_recognized = 0

    for section in segmented.sections:
        content = section.content_lines
        if not content:
            continue
        claimed = [line for line in content if (line.page, line.index) in emission.consumed]
        missed = [line for line in content if (line.page, line.index) not in emission.consumed]
        recognized_lines += len(claimed)
        if not missed:
            sections_recognized += 1
            continue

        unparsed.append(
            UnparsedSection(
                section=section.section_id,
                heading=section.heading,
                page=missed[0].page,
                sheet=doc.sheet_for(missed[0].page),
                first_line=missed[0].index,
                last_page=missed[-1].page,
                last_sheet=doc.sheet_for(missed[-1].page),
                last_line=missed[-1].index,
                line_count=len(missed),
                reason=_reason(len(claimed), len(content)),
                sample=[line.text for line in missed[:UNPARSED_SAMPLE]],
            )
        )
        # Nothing is dropped: unrecognised prose is still carried verbatim.
        for line in missed:
            emission.notes.append(citer.text(line, section.section_id, line.text))

    coverage = Coverage(
        content_lines=segmented.content_line_count(),
        recognized_lines=recognized_lines,
        unrecognized_lines=segmented.content_line_count() - recognized_lines,
        boilerplate_lines=len(segmented.furniture),
        sections_total=len([s for s in segmented.sections if s.content_lines]),
        sections_recognized=sections_recognized,
        sections_unrecognized=len(unparsed),
    )

    resolved_source = source or SourceDocument(
        document_id=doc.document_id,
        sha256=doc.sha256,
        page_count=doc.page_count,
        byte_size=doc.byte_size,
        filename=doc.filename,
        synthetic=doc.synthetic,
    )

    parsed = ParsedSchedule(
        source=resolved_source,
        identity=identity,
        applicability=tuple(emission.applicability),
        charges=tuple(emission.charges),
        tou_windows=tuple(emission.tou_windows),
        holidays=tuple(emission.holidays),
        cross_references=tuple(emission.cross_references),
        proration=tuple(emission.proration),
        conditions=tuple(emission.conditions),
        notes=tuple(emission.notes),
        unparsed=tuple(unparsed),
        coverage=coverage,
        parser_version=PARSER_VERSION,
    )

    # Fail before anything is written rather than after it is relied on.
    assert_fully_cited(parsed.to_json())
    return parsed


def parse_path(
    path: Path,
    *,
    document_id: str | None = None,
    source: SourceDocument | None = None,
    profile: DocumentProfile = DEFAULT,
) -> ParsedSchedule:
    """Parse a PDF or monospace text fixture from disk."""
    doc = layout_from_path(path, document_id=document_id, profile=profile)
    return parse_document(doc, source=source, profile=profile)


def parse_manifest_document(entry: SourceEntry, path: Path) -> ParsedSchedule:
    """Parse a document registered in the source manifest.

    The publisher, URL and retrieval date recorded in the output come from the
    manifest, so a parse of a registered document says where the bytes came
    from rather than only what they contained. This is the single entry point
    used by both the command line and the golden-output tests, so the two
    cannot drift apart.
    """
    profile = resolve(entry.profile)
    doc = layout_from_path(path, document_id=entry.id, profile=profile)
    source = SourceDocument(
        document_id=entry.id,
        sha256=doc.sha256,
        page_count=doc.page_count,
        byte_size=doc.byte_size,
        filename=path.name,
        publisher=entry.publisher,
        retrieved_from=entry.url,
        retrieved_at=entry.retrieved_at,
        synthetic=False,
    )
    return parse_document(doc, source=source, profile=profile)
