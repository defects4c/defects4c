#!/usr/bin/env python3
"""
Read /tmp/status.list (one *.status path per line) and classify each
(project, sha) pair into:

  • is_bug_and_patch : buggy -> failed  AND  fix -> success
  • is_patch_error   : buggy -> failed  AND  fix -> failed
  • is_buggy_error   : buggy -> success (regardless of fix result)

Prints a short summary and – if desired – the full handle lists.
"""

import subprocess

from pathlib import Path
from collections import defaultdict
from typing import Dict, List, Tuple

STATUS_LIST = Path("/tmp/status.list")           # generated earlier

def build_status_list() -> None:
    """Run the exact shell command requested by the user."""
    cmd = (
        "find /out/**/logs -name '*status' -type f -maxdepth 1 "
        "> /tmp/status.list"
    )
    subprocess.run(cmd, shell=True, check=True)
build_status_list()


if not STATUS_LIST.is_file():
    raise FileNotFoundError(STATUS_LIST)


def extract_project(path: Path) -> str | None:
    """
    Given /out/<project>/logs/…, return <project>.
    Returns None if 'logs' is not in the path.
    """
    try:
        logs_idx = path.parts.index("logs")
        return path.parts[logs_idx - 1]
    except ValueError:          # 'logs' not found
        return None


def parse_statuses() -> Tuple[List[str], List[str], List[str]]:
    """
    Walk /tmp/status.list and build three lists:
    (is_bug_and_patch, is_patch_error, is_buggy_error)
    """
    # (project, sha) -> {'buggy': 'failed', 'fix': 'success'}
    status_map: Dict[Tuple[str, str], Dict[str, str]] = defaultdict(dict)

    for raw in STATUS_LIST.read_text().splitlines():
        path = Path(raw.strip())
        proj = extract_project(path)
        if proj is None:
            continue

        # filename pattern: test_<sha>_<kind>.status
        if  not path.name.endswith(".status"):
            continue
        try:
            sha, kind = path.stem[5:].rsplit("_", 1)      # kind ∈ {'buggy','fix'}
        except ValueError:
            continue

        status = path.read_text().strip().lower()         # 'success' | 'failed'
        status_map[(proj, sha)][kind] = status

    bug_and_patch, patch_error, buggy_error = [], [], []

    for (proj, sha), result in status_map.items():
        buggy = result.get("buggy").replace("\\n","").strip()
        fix   = result.get("fix").replace("\\n","").strip()
        if buggy is None or fix is None:                  # incomplete pair
            print ( "proj", proj , "->", sha , "result", result )
            continue

        handle = f"{proj}@{sha}"
        if buggy == "failed" and fix == "success":
            bug_and_patch.append(handle)
        elif buggy == "failed" and fix == "failed":
            patch_error.append(handle)
        elif buggy == "success":
            buggy_error.append(handle)                    # covers both fix outcomes
        else:
            print ("else??" "proj", proj , "->", sha , "result", result )


    return bug_and_patch, patch_error, buggy_error


def main() -> None:
    good, patch_err, buggy_err = parse_statuses()

    print("\n───── Classification Summary ─────────────────────────")
    print(f"is_bug_and_patch : {len(good)} handles")
    print(f"is_patch_error   : {len(patch_err)} handles")
    print(f"is_buggy_error   : {len(buggy_err)} handles\n")

    with open("/tmp/is_bug_and_patch.txt","w") as fw :
        fw.write("\n".join(good))
    with open("/tmp/is_patch_error.txt","w") as fw :
        fw.write("\n".join(patch_err))
    with open("/tmp/is_buggy_error.txt","w") as fw :
        fw.write("\n".join(buggy_err))

    # Uncomment these if you want the exact handles
    # print("is_bug_and_patch :", good)
    # print("is_patch_error   :", patch_err)
    # print("is_buggy_error   :", buggy_err)


if __name__ == "__main__":
    main()


