"""
Robust build-log parser.

Key refinements vs. earlier draft
---------------------------------
* **Single-pass, pre-compiled regexes** for speed (`ERROR_RE`, `EXCLUDE_RE`).
* **Word-boundary aware** keyword search to cut false positives (e.g. *failed* vs. *detailed*).
* **Stable phase detection order** in `PHASE_ORDER`.
* **Dataclass** for structured error entries.
* Automatic **duplicate-line suppression** (preserves order).
* Utility helpers (`get_most_critical_errors`, `format_error_report`) unchanged.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Set

# --------------------------------------------------------------------------- #
# Phase patterns (compile once)
# --------------------------------------------------------------------------- #
PHASE_PATTERNS = {
    "configure": re.compile(r"(?:cmake|configure|configuring|autogen)", re.I),
    "build":     re.compile(r"(?:ninja:\s*entering\s+directory|make(?:\[\d+\])?:\s*entering)", re.I),
    "compile":   re.compile(r"(?:building|compiling|cc1|gcc|clang|\bcc\b.*\.c|\bg\+\+\b)", re.I),
    "link":      re.compile(r"(?:linking|/usr/bin/ld|collect2|ld\s+returned)", re.I),
    "test":      re.compile(r"(?:running\s+tests?|ctest)", re.I),
}
PHASE_ORDER: List[str] = ["configure", "build", "compile", "link", "test"]

# --------------------------------------------------------------------------- #
# Error keywords
# --------------------------------------------------------------------------- #
ERROR_KEYWORDS = [
    # declaration / definition
    "undeclared", "undefined reference", "undefined symbol",
    # syntax
    "expected", "unexpected", "extraneous", "missing",
    # critical
    "fatal", "failed", "error:", "abort",
    # file / permission
    "no such file", "permission denied", "cannot find",
    # compilation
    "multiple definition", "redefinition", "conflicting types",
    # linker
    "collect2:", "ld returned",
]

# word-boundary aware OR-pattern (longer keywords first)
ERROR_RE = re.compile(
    "|".join(rf"\b{re.escape(k)}" if k.isalpha() else re.escape(k)
             for k in sorted(ERROR_KEYWORDS, key=len, reverse=True)),
    re.I,
)

# --------------------------------------------------------------------------- #
# Exclusion patterns (warnings, notes, etc.)
# --------------------------------------------------------------------------- #
EXCLUSION_PATTERNS = [
    r"warning:",
    r"note:",
    r"info:",
    r"debug:",
    r"\d+%\s+tests?\s+passed",
    r"all\s+heap\s+blocks\s+were\s+freed",
    r"error\s+summary:\s+0\s+errors",
]
EXCLUDE_RE = re.compile("|".join(f"(?:{p})" for p in EXCLUSION_PATTERNS), re.I)

# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
@dataclass
class ErrorEntry:
    line: str
    context: Optional[List[str]] = None
    keywords: List[str] = field(default_factory=list)
    severity: str = "general"
    phase: Optional[str] = None


def should_exclude(line: str) -> bool:
    """True if line matches any exclusion pattern."""
    return bool(EXCLUDE_RE.search(line))


def extract_context(idx: int, lines: List[str]) -> List[str]:
    """Return error line plus up to two continuation/marker lines."""
    ctx = [lines[idx].strip()]
    for j in range(idx + 1, min(idx + 3, len(lines))):
        nxt = lines[j]
        if not nxt.strip():
            break
        if nxt.startswith((" ", "\t")) or nxt.lstrip().startswith(("^", "~", "|", "note:", "In ")):
            ctx.append(nxt.strip())
        else:
            break
    return ctx


def normalize(line: str) -> str:
    """Collapse long paths & whitespace."""
    line = re.sub(r"/[^/\s]+(?:/[^/\s]+){3,}/", ".../", line)   # deep paths → .../
    return " ".join(line.split()).strip()


def severity_for(line: str) -> str:
    """Infer severity category."""
    l = line.lower()
    if any(k in l for k in ("fatal", "abort", "critical")):
        return "fatal"
    if any(k in l for k in ("undefined reference", "collect2", "ld returned")):
        return "linker"
    if any(k in l for k in ("undeclared", "expected", "syntax")):
        return "syntax"
    return "general"

# --------------------------------------------------------------------------- #
# Main extractor
# --------------------------------------------------------------------------- #
def extract_error_info(log: str) -> Dict[str, Optional[List[str]]]:
    if not log or not log.strip():
        return {k: None for k in ("phase", "error_keywords", "errors", "error_summary")}

    lines = log.splitlines()
    found_keywords: Set[str] = set()
    error_entries: List[ErrorEntry] = []
    first_error_phase: Optional[str] = None
    current_phase: Optional[str] = None
    seen_lines: Set[str] = set()  # de-dupe

    for i, raw in enumerate(lines):
        if not raw.strip():
            continue

        # Phase tracking
        for ph in PHASE_ORDER:
            if PHASE_PATTERNS[ph].search(raw):
                current_phase = ph
                break

        if should_exclude(raw):
            continue

        if not ERROR_RE.search(raw):
            continue  # no keyword → not an error

        norm = normalize(raw)
        if norm in seen_lines:
            continue
        seen_lines.add(norm)

        # keyword collection
        low = raw.lower()
        kw_here = {kw for kw in ERROR_KEYWORDS if kw in low}
        found_keywords.update(kw_here)

        if first_error_phase is None:
            first_error_phase = current_phase

        entry = ErrorEntry(
            line=norm,
            context=extract_context(i, lines),
            keywords=sorted(kw_here),
            severity=severity_for(raw),
            phase=current_phase,
        )
        error_entries.append(entry)

    if not error_entries:
        return {k: None for k in ("phase", "error_keywords", "errors", "error_summary")}

    # Summary
    summary: Dict[str, any] = {
        "total_errors": len(error_entries),
        "by_severity": {},
        "by_phase": {},
        "fatal_errors": [e.__dict__ for e in error_entries if e.severity == "fatal"],
    }
    for e in error_entries:
        summary["by_severity"][e.severity] = summary["by_severity"].get(e.severity, 0) + 1
        ph = e.phase or "unknown"
        summary["by_phase"][ph] = summary["by_phase"].get(ph, 0) + 1

    return {
        "phase": first_error_phase,
        "error_keywords": sorted(found_keywords) or None,
        "errors": [e.line for e in error_entries],
        "error_summary": summary,
    }

# --------------------------------------------------------------------------- #
# Convenience helpers (unchanged API)
# --------------------------------------------------------------------------- #
def get_most_critical_errors(result: Dict) -> List[str]:
    if not result.get("error_summary"):
        return []
    fatals = result["error_summary"].get("fatal_errors", [])
    return [e["line"] for e in fatals[:5]]


def format_error_report(result: Dict) -> str:
    if not result.get("errors"):
        return "No errors detected in the build log."

    out: List[str] = ["Build Error Analysis", "=" * 50]
    if result.get("phase"):
        out.append(f"First error detected in phase: {result['phase']}")
    if result.get("error_keywords"):
        out.append(f"Error types found: {', '.join(result['error_keywords'])}")

    summary = result.get("error_summary")
    if summary:
        out.append(f"Total errors: {summary['total_errors']}")
        if summary["by_severity"]:
            out.append("Errors by severity:")
            for sev, cnt in summary["by_severity"].items():
                out.append(f"  - {sev}: {cnt}")

    out.append("\nFirst few errors:")
    for i, line in enumerate(result["errors"][:3], 1):
        out.append(f"{i}. {line}")
    return "\n".join(out)





