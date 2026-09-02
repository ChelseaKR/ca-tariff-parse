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

from .diff import DiffError, schedule_diff
from .model import DISCLAIMER, ParsedSchedule
from .parser import PARSER_VERSION, parse_manifest_document, parse_path
from .profiles import UnknownProfileError, names, resolve
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
    try:
        result: int = args.func(args)
    except (SourceError, UnknownProfileError, DiffError) as error:
        sys.stderr.write(f"error: {error}\n")
        return EXIT_ERROR
    return result


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
