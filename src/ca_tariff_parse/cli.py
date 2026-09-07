"""Command line interface.

``parse``, ``coverage``, ``diff`` and ``baseline`` are entirely offline.
``fetch`` and ``watch`` are the two commands that touch the network, and each
exists so that downloading a source document is always a deliberate act
rather than a side effect of parsing one.
"""

from __future__ import annotations

import argparse
import datetime
import functools
import json
import sys
import tempfile
from pathlib import Path

from .calendar import CalendarError, render, summary
from .check import PROPERTY_IDS, CheckError, check, to_json, to_text, unmet
from .diff import DiffError, schedule_diff
from .export import ExportError, render_csv, render_jsonl, rows, table_names
from .export import columns as export_columns
from .history import HistoryError, parse_match, read_legs, timelines
from .history import to_jsonl as history_jsonl
from .history import to_text as history_text
from .loader import load as load_parse
from .model import DISCLAIMER, ParsedSchedule
from .parser import PARSER_VERSION, parse_manifest_document, parse_path
from .profiles import UnknownProfileError, names, resolve
from .reconcile import ReconcileError, read_record, reconcile, render_json, render_text
from .sources import (
    DEFAULT_MANIFEST,
    SourceError,
    download,
    fetch,
    find,
    load_manifest,
    local_state,
    verify,
)
from .watch import CHANGED, ERROR, manifest_with, watch, write_baseline

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_COVERAGE = 2
#: ``diff`` found differences. Its own code, the way ``diff(1)`` exits 1, so a
#: script can tell "changed" from "could not compare" without reading stderr.
EXIT_CHANGED = 3
#: ``check --require`` named a property that did not come back ``holds``. Its
#: own code, so a caller can tell "the property is false or undecidable" from
#: "the file could not be read".
EXIT_PROPERTY = 4
#: ``reconcile`` could not read the URDB record it was given at all. Shares
#: its number with :data:`EXIT_COVERAGE` because no single command emits both,
#: and named separately so a caller reads the meaning its own verb gives it.
EXIT_UNREADABLE = 2
#: ``history --match`` selected no record. Its own code, so a caller can tell
#: "nothing in this document is identified that way" from "the committed
#: reports could not be read", which is the difference between a typo in a
#: match term and a broken record.
EXIT_NO_MATCH = 5

DEFAULT_BASELINE_DIR = Path("data/parsed")
DEFAULT_CHANGES_DIR = Path("data/changes")


def _load(args: argparse.Namespace) -> ParsedSchedule:
    path = Path(args.document)
    if args.id:
        # The manifest entry names the profile, so a registered document is
        # always read with the one it was pinned against.
        entry = find(load_manifest(Path(args.manifest)), args.id)
        verify(entry, path)
        return parse_manifest_document(entry, path)
    return parse_path(path, profile=resolve(args.profile))


def _cmd_parse(args: argparse.Namespace) -> int:
    parsed = _load(args)
    payload = parsed.to_json()
    text = json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=False)
    if args.output:
        Path(args.output).write_text(text + "\n", encoding="utf-8")
    else:
        sys.stdout.write(text + "\n")

    ratio = parsed.coverage.line_ratio
    if args.min_coverage is not None and ratio < args.min_coverage:
        sys.stderr.write(
            f"coverage {ratio:.1%} is below the required {args.min_coverage:.1%}; "
            f"{parsed.coverage.unrecognized_lines} content line(s) unrecognized\n"
        )
        return EXIT_COVERAGE
    return EXIT_OK


#: The arrays of ``parse``'s report whose lengths the coverage report counts.
EMITTED_KEYS = (
    "charges",
    "tou_windows",
    "holidays",
    "cross_references",
    "proration",
    "conditions",
)


def _coverage_payload(parsed: ParsedSchedule) -> dict[str, object]:
    """The coverage report as JSON, selected from the full report.

    Every value here is lifted out of ``parse``'s own payload rather than
    recomputed, so this cannot come to disagree with the document it describes.
    The counts are the lengths of that payload's arrays, which is what the text
    report prints.
    """
    full = parsed.to_json()
    return {
        "schema": full["schema"],
        "parser_version": full["parser_version"],
        "disclaimer": full["disclaimer"],
        "source": full["source"],
        "coverage": full["coverage"],
        "emitted": {key: len(full[key]) for key in EMITTED_KEYS},  # type: ignore[arg-type]
        "unparsed": full["unparsed"],
    }


def _cmd_coverage(args: argparse.Namespace) -> int:
    parsed = _load(args)
    coverage = parsed.coverage
    if args.json:
        sys.stdout.write(
            json.dumps(_coverage_payload(parsed), indent=2, ensure_ascii=False, sort_keys=False)
            + "\n"
        )
        if args.min_coverage is not None and coverage.line_ratio < args.min_coverage:
            return EXIT_COVERAGE
        return EXIT_OK
    out = sys.stdout
    out.write(f"document        {parsed.source.document_id}\n")
    out.write(f"sha256          {parsed.source.sha256}\n")
    out.write(f"pages           {parsed.source.page_count}\n")
    if parsed.source.synthetic:
        out.write("SYNTHETIC       this document is a synthetic fixture, not a real tariff\n")
    out.write(
        f"content lines   {coverage.recognized_lines}/{coverage.content_lines} "
        f"recognized ({coverage.line_ratio:.1%})\n"
    )
    out.write(
        f"sections        {coverage.sections_recognized}/{coverage.sections_total} "
        f"fully recognized ({coverage.section_ratio:.1%})\n"
    )
    out.write(f"fully recognized {coverage.fully_recognized}\n")
    if not coverage.read_anything:
        # Zero content lines is a failed read, not a schedule that happens to
        # be empty, and the two lines above it are all zeroes either way. Say
        # which one it is rather than leaving a reader to infer it.
        out.write(
            "FAILED READ     no content lines were extracted from this document; "
            "nothing below was read from it\n"
        )
    out.write(
        f"emitted         {len(parsed.charges)} charge(s), "
        f"{len(parsed.tou_windows)} time-of-use window(s), "
        f"{len(parsed.holidays)} holiday(s), "
        f"{len(parsed.cross_references)} cross reference(s), "
        f"{len(parsed.proration)} proration rule(s), "
        f"{len(parsed.conditions)} condition(s)\n"
    )
    if parsed.unparsed:
        out.write("\nunparsed:\n")
        for item in parsed.unparsed:
            out.write(f"  {item.section:<10} {item.span} ({item.line_count}) {item.reason}\n")
            for sample in item.sample:
                out.write(f"      | {sample[:96]}\n")
    out.write(f"\n{DISCLAIMER}\n")

    if args.min_coverage is not None and coverage.line_ratio < args.min_coverage:
        return EXIT_COVERAGE
    return EXIT_OK


def _cmd_sources(args: argparse.Namespace) -> int:
    entries = load_manifest(Path(args.manifest))
    if not entries:
        sys.stdout.write("no documents registered\n")
        return EXIT_OK
    for entry in entries:
        # local_state() reports rather than raises: a truncated download, a
        # publisher revision saved under the old filename, a hand-edited file
        # or something that is not a regular file at all (a directory, a FIFO)
        # all read as "mismatched" here. verify-source still raises on them.
        state = local_state(entry, Path(args.dir))
        sys.stdout.write(
            f"{entry.id:<14} {entry.schedule:<8} {state:<12} {entry.publisher}\n"
            f"{'':<14} {entry.url}\n"
            f"{'':<14} sha256 {entry.sha256} retrieved {entry.retrieved_at}\n"
        )
    return EXIT_OK


def _cmd_fetch(args: argparse.Namespace) -> int:
    entries = load_manifest(Path(args.manifest))
    targets = [find(entries, args.id)] if args.id else entries
    for entry in targets:
        path = fetch(entry, Path(args.dir))
        sys.stdout.write(f"fetched {entry.id} to {path}\n")
    return EXIT_OK


def _cmd_verify_source(args: argparse.Namespace) -> int:
    entries = load_manifest(Path(args.manifest))
    targets = [find(entries, args.id)] if args.id else entries
    for entry in targets:
        sha = verify(entry, entry.path(Path(args.dir)))
        sys.stdout.write(f"{entry.id} matches manifest (sha256 {sha})\n")
    return EXIT_OK


def _read_json(path: str) -> dict[str, object]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise DiffError(f"{path} does not hold a parsed schedule")
    return payload


def _cmd_diff(args: argparse.Namespace) -> int:
    delta = schedule_diff(_read_json(args.old), _read_json(args.new))
    text = delta.to_jsonl() if args.jsonl else delta.to_markdown()
    if args.output:
        Path(args.output).write_text(text, encoding="utf-8")
    else:
        sys.stdout.write(text)
    counts = delta.summary()
    sys.stderr.write(
        f"{delta.document_id}: {counts['added']} added, {counts['removed']} removed, "
        f"{counts['changed']} changed\n"
    )
    return EXIT_CHANGED if delta.changes else EXIT_OK


def _pinned_schedules(path: str | None) -> list[str] | None:
    """The schedule codes the manifest pins, or None when none was given.

    None and an empty list are different answers and stay different: no
    manifest means the property was not tested, an empty manifest means it
    could not be.
    """
    if path is None:
        return None
    return [entry.schedule for entry in load_manifest(Path(path))]


def _cmd_check(args: argparse.Namespace) -> int:
    payload = _read_json(args.parsed)
    if not isinstance(payload, dict):
        raise CheckError("a parse payload is an object")
    source = payload.get("source")
    stated = source.get("document_id") if isinstance(source, dict) else None
    document_id = stated if isinstance(stated, str) and stated else Path(args.parsed).stem
    properties = check(payload, pinned=_pinned_schedules(args.manifest))
    text = to_json(document_id, properties) if args.json else to_text(document_id, properties)
    if args.output:
        Path(args.output).write_text(text, encoding="utf-8")
    else:
        sys.stdout.write(text)

    failed = unmet(properties, args.require)
    for prop in failed:
        sys.stderr.write(f"{document_id}: required property {prop.id} {prop.state}\n")
    return EXIT_PROPERTY if failed else EXIT_OK


def _cmd_export(args: argparse.Namespace) -> int:
    """Flatten a parse into cited tables, one row per record."""
    payload = _read_json(args.parsed)
    if not isinstance(payload, dict):
        raise ExportError("a parse payload is an object")
    render = render_jsonl if args.format == "jsonl" else render_csv
    if args.all:
        directory = Path(args.all)
        directory.mkdir(parents=True, exist_ok=True)
        for table in table_names():
            order = export_columns(table, snippets=args.snippets)
            written = directory / f"{table}.{args.format}"
            # Written even when the table is empty. A missing file reads as
            # "not exported"; a header with no rows reads as "this schedule
            # states none of these", which is what the parse says.
            written.write_text(
                render(rows(payload, table, snippets=args.snippets), order), encoding="utf-8"
            )
            sys.stderr.write(f"{table:<18} {written}\n")
        return EXIT_OK
    order = export_columns(args.table, snippets=args.snippets)
    text = render(rows(payload, args.table, snippets=args.snippets), order)
    if args.output:
        Path(args.output).write_text(text, encoding="utf-8")
    else:
        sys.stdout.write(text)
    return EXIT_OK


def _cmd_reconcile(args: argparse.Namespace) -> int:
    """Audit a URDB record the user supplied against the cited parse."""
    payload = _read_json(args.parsed)
    try:
        record = read_record(Path(args.record).read_text(encoding="utf-8"))
    except OSError as error:
        sys.stderr.write(f"error: cannot read {args.record}: {error}\n")
        return EXIT_UNREADABLE
    except ReconcileError as error:
        sys.stderr.write(f"error: {error}\n")
        return EXIT_UNREADABLE
    result = reconcile(payload, record)
    text = render_json(result) if args.json else render_text(result)
    if args.output:
        Path(args.output).write_text(text, encoding="utf-8")
    else:
        sys.stdout.write(text)
    contradicted = result.contradicted()
    for finding in contradicted:
        sys.stderr.write(f"{result.document_id}: {finding.field} contradicts the parse\n")
    return EXIT_CHANGED if contradicted else EXIT_OK


def _cmd_history(args: argparse.Namespace) -> int:
    """Rebuild a value's timeline from the committed watch reports."""
    if bool(args.match) == bool(args.all):
        raise HistoryError("history needs exactly one of --match and --all")
    criteria = parse_match(args.match) if args.match else None
    legs = read_legs(Path(args.changes_dir), args.id)
    baseline_path = Path(args.baseline_dir) / f"{args.id}.json"
    baseline = None
    if baseline_path.exists():
        baseline = _read_json(str(baseline_path))
        if not isinstance(baseline, dict):
            raise HistoryError(f"{baseline_path} is not a parse payload")
    elif not legs:
        raise HistoryError(
            f"no committed reports under {args.changes_dir} and no baseline at "
            f"{baseline_path}; there is nothing committed to build a timeline from"
        )
    built = timelines(legs, baseline, criteria)
    text = history_jsonl(args.id, built) if args.jsonl else history_text(args.id, built)
    if args.output:
        Path(args.output).write_text(text, encoding="utf-8")
    else:
        sys.stdout.write(text)
    if built:
        return EXIT_OK
    if args.all:
        # Not a failed match: nothing was asked for by name. An empty result
        # here means the committed reports mention no record for this
        # document, which `history_text` has already said in the output, and
        # which is a true statement about the record rather than an error.
        sys.stderr.write(
            f"{args.id}: no committed report under {args.changes_dir} mentions a "
            "record for this document. That is a statement about what has been "
            "committed, not about whether the document has changed\n"
        )
        return EXIT_OK
    sys.stderr.write(
        f"{args.id}: no record matched {args.match!r}. That is not the same as "
        "a record that has never changed, which is reported with one state\n"
    )
    return EXIT_NO_MATCH


def _cmd_calendar(args: argparse.Namespace) -> int:
    """Write the time rules the document stated, and the list of what it did not."""
    rendered = render(load_parse(args.parsed))
    directory = Path(args.dir)
    directory.mkdir(parents=True, exist_ok=True)
    calendar_path = directory / f"{rendered.document_id}.ics"
    refused_path = directory / f"{rendered.document_id}.refused.json"
    calendar_path.write_text(rendered.ics, encoding="utf-8", newline="")
    # Always written, even when nothing was refused. A missing file reads as
    # "no refusal list", which is not the same statement as "nothing refused".
    refused_path.write_text(rendered.refused_json(), encoding="utf-8")
    for line in summary(rendered):
        sys.stdout.write(f"{line}\n")
    sys.stdout.write(f"{calendar_path}\n{refused_path}\n")
    return EXIT_OK


def _cmd_baseline(args: argparse.Namespace) -> int:
    """Write the reviewed parse of each pinned document, from the pinned bytes only."""
    entries = load_manifest(Path(args.manifest))
    targets = [find(entries, args.id)] if args.id else entries
    for entry in targets:
        path = entry.path(Path(args.dir))
        verify(entry, path)
        parsed = parse_manifest_document(entry, path)
        written = write_baseline(Path(args.baseline_dir), entry.id, parsed.to_json())
        sys.stdout.write(f"{entry.id:<14} baseline written to {written}\n")
    return EXIT_OK


def _cmd_watch(args: argparse.Namespace) -> int:
    manifest = Path(args.manifest)
    entries = load_manifest(manifest)
    targets = [find(entries, args.id)] if args.id else entries
    today = args.date or datetime.datetime.now(datetime.UTC).date().isoformat()
    downloader = functools.partial(download, timeout=args.timeout)
    with tempfile.TemporaryDirectory(prefix="ca-tariff-watch-") as scratch:
        outcomes = watch(
            targets,
            downloader=downloader,
            baseline_dir=Path(args.baseline_dir),
            changes_dir=Path(args.changes_dir),
            work_dir=Path(args.work_dir) if args.work_dir else Path(scratch),
            today=today,
        )
    text = manifest.read_text(encoding="utf-8")
    for outcome in outcomes:
        sys.stdout.write(f"{outcome.id:<14} {outcome.state:<10} {outcome.detail}\n")
        if outcome.state == CHANGED and outcome.sha256 and outcome.bytes and outcome.pages:
            text = manifest_with(
                text,
                outcome.id,
                sha256=outcome.sha256,
                size=outcome.bytes,
                pages=outcome.pages,
                retrieved_at=today,
            )
    if any(outcome.state == CHANGED for outcome in outcomes):
        manifest.write_text(text, encoding="utf-8")
        sys.stdout.write(f"{manifest} updated for review; nothing is merged by this command\n")
    if args.summary:
        Path(args.summary).write_text(
            json.dumps(
                {"date": today, "outcomes": [outcome.to_json() for outcome in outcomes]},
                indent=2,
                ensure_ascii=False,
            )
            + "\n",
            encoding="utf-8",
        )
    return EXIT_ERROR if any(outcome.state == ERROR for outcome in outcomes) else EXIT_OK


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ca-tariff-parse",
        description=(
            "Turn a published California electricity rate schedule into structured "
            "data, with a citation for every value. Not rate advice, and not a bill "
            "estimate. Not affiliated with any utility."
        ),
        epilog=DISCLAIMER,
    )
    parser.add_argument("--version", action="version", version=PARSER_VERSION)
    subparsers = parser.add_subparsers(dest="command", required=True)

    def add_manifest(target: argparse.ArgumentParser) -> None:
        target.add_argument(
            "--manifest", default=str(DEFAULT_MANIFEST), help="path to sources.toml"
        )
        target.add_argument("--dir", default="sources", help="directory holding source documents")

    def add_document(target: argparse.ArgumentParser) -> None:
        target.add_argument("document", help="path to a source PDF or text fixture")
        target.add_argument(
            "--id",
            help=(
                "manifest id for this document. When given, the file is checked "
                "against the manifest's SHA-256 before it is parsed."
            ),
        )
        target.add_argument(
            "--manifest", default=str(DEFAULT_MANIFEST), help="path to sources.toml"
        )
        target.add_argument(
            "--min-coverage",
            type=float,
            help="exit non-zero if the recognized line ratio falls below this (0 to 1)",
        )
        target.add_argument(
            "--profile",
            choices=names(),
            help=(
                "document profile for a file that is not in the manifest. A profile "
                "supplies only what a document cannot state about itself. Registered "
                "documents take theirs from the manifest and ignore this."
            ),
        )

    p_parse = subparsers.add_parser("parse", help="parse a schedule to JSON")
    add_document(p_parse)
    p_parse.add_argument("-o", "--output", help="write JSON here instead of stdout")
    p_parse.set_defaults(func=_cmd_parse)

    p_coverage = subparsers.add_parser(
        "coverage", help="report how much of a document the parser accounted for"
    )
    add_document(p_coverage)
    p_coverage.add_argument(
        "--json",
        action="store_true",
        help="write the same figures as JSON instead of the text report",
    )
    p_coverage.set_defaults(func=_cmd_coverage)

    p_sources = subparsers.add_parser("sources", help="list documents in the manifest")
    add_manifest(p_sources)
    p_sources.set_defaults(func=_cmd_sources)

    p_fetch = subparsers.add_parser(
        "fetch", help="download a source document (the only networked command)"
    )
    add_manifest(p_fetch)
    p_fetch.add_argument("--id", help="fetch only this document id")
    p_fetch.set_defaults(func=_cmd_fetch)

    p_verify = subparsers.add_parser(
        "verify-source", help="check a local document against the manifest SHA-256"
    )
    add_manifest(p_verify)
    p_verify.add_argument("--id", help="verify only this document id")
    p_verify.set_defaults(func=_cmd_verify_source)

    p_diff = subparsers.add_parser(
        "diff", help="what changed between two parses of one schedule, value by value"
    )
    p_diff.add_argument("old", help="the earlier parse (JSON from parse, or a baseline)")
    p_diff.add_argument("new", help="the later parse")
    p_diff.add_argument(
        "--jsonl", action="store_true", help="one JSON object per change instead of Markdown"
    )
    p_diff.add_argument("-o", "--output", help="write the report here instead of stdout")
    p_diff.set_defaults(func=_cmd_diff)

    p_check = subparsers.add_parser(
        "check",
        help="report which properties of a parse hold, fail, or cannot be established",
    )
    p_check.add_argument("parsed", help="JSON from parse, or a watch baseline")
    p_check.add_argument(
        "--manifest",
        help=(
            "path to sources.toml. Without it the cross-reference property "
            "reports that it was not tested, rather than passing."
        ),
    )
    p_check.add_argument(
        "--json", action="store_true", help="write the report as JSON instead of text"
    )
    p_check.add_argument("-o", "--output", help="write the report here instead of stdout")
    p_check.add_argument(
        "--require",
        action="append",
        default=[],
        choices=list(PROPERTY_IDS),
        metavar="PROPERTY",
        help=(
            "exit non-zero unless this property holds. Repeatable. "
            '"cannot be established" counts as unmet: a caller who requires a '
            "property is saying a value depends on it, and not being able to "
            "tell is not permission to proceed. One of: " + ", ".join(PROPERTY_IDS)
        ),
    )
    p_check.set_defaults(func=_cmd_check)

    p_export = subparsers.add_parser(
        "export", help="flatten a parse into cited tables, one row per record"
    )
    p_export.add_argument("parsed", help="JSON from parse, or a watch baseline")
    p_export.add_argument(
        "--table",
        choices=list(table_names()),
        metavar="TABLE",
        help="which table to write. One of: " + ", ".join(table_names()),
    )
    p_export.add_argument(
        "--all",
        metavar="DIR",
        help="write every table into this directory instead, one file each",
    )
    p_export.add_argument("--format", choices=("csv", "jsonl"), default="csv", help="default: csv")
    p_export.add_argument(
        "--snippets",
        action="store_true",
        help=(
            "add a <field>.snippet column beside each locator. Off by default: "
            "a snippet carries the document's own text (ADR 0003)"
        ),
    )
    p_export.add_argument("-o", "--output", help="write here instead of stdout")
    p_export.set_defaults(func=_cmd_export)

    p_history = subparsers.add_parser(
        "history",
        help="rebuild a value's timeline from the committed watch reports",
    )
    p_history.add_argument("--id", required=True, help="the manifest id of the document")
    p_history.add_argument(
        "--match",
        help=(
            "select records by their identity fields, e.g. "
            "'kind=energy_usage label=\"Generation\" season=Summer'. A term that "
            "is not field=value is an error, not a term that matches everything."
        ),
    )
    p_history.add_argument("--all", action="store_true", help="every record the reports mention")
    p_history.add_argument(
        "--changes-dir", default=str(DEFAULT_CHANGES_DIR), help="default: data/changes"
    )
    p_history.add_argument(
        "--baseline-dir", default=str(DEFAULT_BASELINE_DIR), help="default: data/parsed"
    )
    p_history.add_argument("--jsonl", action="store_true", help="one JSON object per timeline")
    p_history.add_argument("-o", "--output", help="write here instead of stdout")
    p_history.set_defaults(func=_cmd_history)

    p_calendar = subparsers.add_parser(
        "calendar",
        help="render the stated TOU windows and holidays as iCalendar rules",
    )
    p_calendar.add_argument("parsed", help="JSON from parse")
    p_calendar.add_argument(
        "--dir",
        default=".",
        help=(
            "where to write <document_id>.ics and <document_id>.refused.json "
            "(default: the current directory). Both are always written; the "
            "refusal list is part of the output, not a log."
        ),
    )
    p_calendar.set_defaults(func=_cmd_calendar)

    p_reconcile = subparsers.add_parser(
        "reconcile",
        help="audit a URDB rate record you supply against the cited parse, field by field",
    )
    p_reconcile.add_argument("parsed", help="JSON from parse, or a watch baseline")
    p_reconcile.add_argument(
        "record",
        help=(
            "a URDB rate record you downloaded yourself, as JSON. Nothing is "
            "fetched: reconcile is offline."
        ),
    )
    p_reconcile.add_argument(
        "--json", action="store_true", help="write the report as JSON instead of text"
    )
    p_reconcile.add_argument("-o", "--output", help="write the report here instead of stdout")
    p_reconcile.set_defaults(func=_cmd_reconcile)

    p_baseline = subparsers.add_parser(
        "baseline", help="write the reviewed parse of each pinned document for the watch"
    )
    add_manifest(p_baseline)
    p_baseline.add_argument("--id", help="only this document id")
    p_baseline.add_argument(
        "--baseline-dir",
        default=str(DEFAULT_BASELINE_DIR),
        help="where baselines live (default: data/parsed)",
    )
    p_baseline.set_defaults(func=_cmd_baseline)

    p_watch = subparsers.add_parser(
        "watch",
        help=(
            "download each pinned document and, where the publisher revised it, "
            "diff the revision against its baseline (networked)"
        ),
    )
    p_watch.add_argument("--manifest", default=str(DEFAULT_MANIFEST), help="path to sources.toml")
    p_watch.add_argument("--id", help="only this document id")
    p_watch.add_argument(
        "--baseline-dir", default=str(DEFAULT_BASELINE_DIR), help="default: data/parsed"
    )
    p_watch.add_argument(
        "--changes-dir", default=str(DEFAULT_CHANGES_DIR), help="default: data/changes"
    )
    p_watch.add_argument(
        "--work-dir", help="where downloads land (default: a temporary directory, discarded)"
    )
    p_watch.add_argument("--date", help="the retrieval date to record (default: today, UTC)")
    p_watch.add_argument("--timeout", type=float, default=60.0, help="seconds per request")
    p_watch.add_argument("--summary", help="write a JSON summary of every outcome here")
    p_watch.set_defaults(func=_cmd_watch)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "export" and bool(args.table) == bool(args.all):
        parser.error("export needs exactly one of --table and --all")
    try:
        result: int = args.func(args)
    except (
        SourceError,
        UnknownProfileError,
        DiffError,
        ExportError,
        CalendarError,
        HistoryError,
        ReconcileError,
    ) as error:
        sys.stderr.write(f"error: {error}\n")
        return EXIT_ERROR
    return result


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
