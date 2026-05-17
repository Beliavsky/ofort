"""Prune procedures reported unused by ``ofort --unused-procs``.

The default mode is a dry run.  Use ``--write`` to edit files in place.
"""

from __future__ import annotations

import argparse
import csv
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OFORT = ROOT / "ofort.exe"


PROC_START_RE = re.compile(
    r"^\s*(?!end\b)(?:(?:[\w(),=*:+-]+)\s+)*"
    r"(?P<kind>subroutine|function)\s+(?P<name>[a-z_]\w*)\b",
    re.IGNORECASE,
)
PROC_END_RE = re.compile(
    r"^\s*end\s*(?P<kind>subroutine|function)?(?:\s+(?P<name>[a-z_]\w*))?\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class UnusedProcedure:
    kind: str
    name: str
    module: str
    file: Path
    line: int
    global_line: int


@dataclass(frozen=True)
class Removal:
    proc: UnusedProcedure
    start: int
    end: int


def strip_comment(line: str) -> str:
    quote: str | None = None
    i = 0
    while i < len(line):
        ch = line[i]
        if quote:
            if ch == quote:
                if i + 1 < len(line) and line[i + 1] == quote:
                    i += 2
                    continue
                quote = None
        elif ch in ("'", '"'):
            quote = ch
        elif ch == "!":
            return line[:i]
        i += 1
    return line


def logical_line(lines: list[str], index: int) -> str:
    text = strip_comment(lines[index]).rstrip("\r\n")
    j = index
    while text.rstrip().endswith("&") and j + 1 < len(lines):
        text = text.rstrip()
        text = text[:-1]
        j += 1
        cont = strip_comment(lines[j]).strip()
        if cont.startswith("&"):
            cont = cont[1:].lstrip()
        text += " " + cont.rstrip("\r\n")
    return text


def parse_unused_procs(stdout: str) -> list[UnusedProcedure]:
    lines = stdout.splitlines()
    if len(lines) < 2 or lines[0] != "ofort-unused-procs-v1":
        raise ValueError("ofort --unused-procs did not produce the expected TSV header")
    reader = csv.DictReader(lines[1:], delimiter="\t")
    records: list[UnusedProcedure] = []
    for row in reader:
        if row.get("status") != "unused":
            continue
        file_text = row.get("file", "")
        line_text = row.get("line", "")
        if not file_text or not line_text:
            continue
        records.append(
            UnusedProcedure(
                kind=row.get("kind", ""),
                name=row.get("name", ""),
                module=row.get("module", ""),
                file=Path(file_text),
                line=int(line_text),
                global_line=int(row.get("global_line", "0") or "0"),
            )
        )
    return records


def run_unused_procs(args: argparse.Namespace) -> list[UnusedProcedure]:
    cmd = [str(args.ofort), "--unused-procs"]
    if args.dep:
        cmd.append("--dep")
    cmd.extend(str(path) for path in args.sources)
    result = subprocess.run(
        cmd,
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=args.timeout,
    )
    if result.returncode != 0:
        if result.stdout:
            sys.stdout.write(result.stdout)
        if result.stderr:
            sys.stderr.write(result.stderr)
        raise SystemExit(result.returncode)
    return parse_unused_procs(result.stdout)


def find_procedure_span(path: Path, proc: UnusedProcedure) -> Removal | None:
    try:
        lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    except OSError as exc:
        print(f"skip\t{path}\t{proc.line}\t{proc.kind}\t{proc.name}\t{exc}", file=sys.stderr)
        return None
    if proc.kind not in {"subroutine", "function"}:
        print(
            f"skip\t{path}\t{proc.line}\t{proc.kind}\t{proc.name}\tunsupported procedure kind",
            file=sys.stderr,
        )
        return None
    if proc.line < 1 or proc.line > len(lines):
        print(f"skip\t{path}\t{proc.line}\t{proc.kind}\t{proc.name}\tline out of range", file=sys.stderr)
        return None

    start_index = proc.line - 1
    start_match = PROC_START_RE.match(logical_line(lines, start_index))
    if (
        not start_match
        or start_match.group("kind").lower() != proc.kind
        or start_match.group("name").lower() != proc.name.lower()
    ):
        print(
            f"skip\t{path}\t{proc.line}\t{proc.kind}\t{proc.name}\tprocedure header not recognized",
            file=sys.stderr,
        )
        return None

    depth = 1
    for index in range(start_index + 1, len(lines)):
        text = logical_line(lines, index)
        if PROC_START_RE.match(text):
            depth += 1
            continue
        end_match = PROC_END_RE.match(text)
        if not end_match:
            continue
        end_kind = end_match.group("kind")
        end_name = end_match.group("name")
        if depth == 1:
            if end_kind and end_kind.lower() != proc.kind:
                continue
            if end_name and end_name.lower() != proc.name.lower():
                continue
        depth -= 1
        if depth == 0:
            return Removal(proc=proc, start=proc.line, end=index + 1)

    print(f"skip\t{path}\t{proc.line}\t{proc.kind}\t{proc.name}\tmatching END not found", file=sys.stderr)
    return None


def detect_overlaps(removals: list[Removal]) -> list[Removal]:
    kept: list[Removal] = []
    by_file: dict[Path, list[Removal]] = {}
    for removal in removals:
        by_file.setdefault(removal.proc.file.resolve(), []).append(removal)
    for group in by_file.values():
        group.sort(key=lambda item: (item.start, item.end))
        last_end = 0
        for removal in group:
            if removal.start <= last_end:
                print(
                    f"skip\t{removal.proc.file}\t{removal.start}\t{removal.proc.kind}\t"
                    f"{removal.proc.name}\toverlaps another removal",
                    file=sys.stderr,
                )
                continue
            kept.append(removal)
            last_end = removal.end
    return kept


def apply_removals(removals: list[Removal], backup: bool) -> None:
    by_file: dict[Path, list[Removal]] = {}
    for removal in removals:
        by_file.setdefault(removal.proc.file, []).append(removal)

    for path, group in by_file.items():
        lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
        if backup:
            backup_path = path.with_suffix(path.suffix + ".bak")
            shutil.copy2(path, backup_path)
        for removal in sorted(group, key=lambda item: item.start, reverse=True):
            del lines[removal.start - 1 : removal.end]
        path.write_text("".join(lines), encoding="utf-8")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("sources", nargs="+", type=Path, help="main source file(s) passed to ofort")
    parser.add_argument("--ofort", type=Path, default=DEFAULT_OFORT, help="path to ofort executable")
    parser.add_argument("--dep", action="store_true", help="pass --dep to ofort before pruning")
    parser.add_argument("--write", action="store_true", help="edit files in place; default is dry-run")
    parser.add_argument("--backup", action="store_true", help="write .bak files before editing")
    parser.add_argument("--timeout", type=float, default=30.0, help="seconds allowed for ofort analysis")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if not args.ofort.exists():
        print(f"ofort executable not found: {args.ofort}", file=sys.stderr)
        return 2

    procs = run_unused_procs(args)
    removals = [span for proc in procs if (span := find_procedure_span(proc.file, proc)) is not None]
    removals = detect_overlaps(removals)

    action = "remove" if args.write else "would-remove"
    for removal in removals:
        proc = removal.proc
        print(f"{action}\t{proc.file}\t{removal.start}\t{removal.end}\t{proc.kind}\t{proc.module}\t{proc.name}")

    if args.write and removals:
        apply_removals(removals, args.backup)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
