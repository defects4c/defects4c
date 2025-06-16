#!/usr/bin/env python3
"""
Unified Patch Service (minimal)

Startup auto-loads
• metadata → META_DICT from /src/projects/**/bugs_list*.json
• guidance → guidance_df from /src/guaidance.csv
• file text → SRC_CONTENT from /src/src_path_list.jsonl

Public endpoints
• GET /health
• POST /write_patch ← single entry for all patch operations
"""
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from pathlib import Path
from typing import Dict, Any, List, Optional
import pandas as pd
import hashlib, json, re, os, glob, tempfile, subprocess

app = FastAPI(title="Patch Service", version="1.0.0")

# ─────────────────────────── Error Codes ────────────────────────────
class ErrorCodes:
    ERR_MARKDOWN_EXTRACT_FAIL = "err_extract_code_fail"
    
    # Bug ID parsing errors
    ERR_INVALID_BUG_ID_FORMAT = "err_invalid_bug_id_format"
    
    # Data loading errors
    ERR_GUIDANCE_NOT_LOADED = "err_guidance_not_loaded"
    ERR_BUG_ID_NOT_IN_GUIDANCE = "err_bug_id_not_in_guidance"
    ERR_RECORD_NOT_FOUND = "err_record_not_found"
    ERR_SRC_CONTENT_NOT_CACHED = "err_src_content_not_cached"
    
    # Patch application errors
    ERR_CONTEXT_MISMATCH = "err_context_mismatch_byte_range"
    ERR_NO_PATCH_CONTENT = "err_no_patch_content_identified"
    ERR_PATCH_FILE_CREATION_FAILED = "err_patch_file_creation_failed"

def create_http_error(status_code: int, error_code: str, message: str):
    """Create HTTPException with error code in detail"""
    return HTTPException(
        status_code=status_code,
        detail={
            "error_code": error_code,
            "message": message
        }
    )

# ─────────────────────────── Globals ────────────────────────────────
META_DICT: Dict[str, Dict[str, str]] = {}
META_DICT_PREFIX_SUFFIX: Dict[str, Dict[str, str]] = {}
guidance_df: Optional[pd.DataFrame] = None
SRC_CONTENT: Dict[str, str] = {}  # src_path → file content
PROMPT_CONTENT: Dict[str, str] = {}  # src_path → file content

ROOT_SRC = Path(os.getenv("SRC_DIR", "/src"))
ROOT_OUT = Path(os.getenv("SRC_OUT", "/out"))
ROOT_META = Path(os.getenv("META_DIR", "/src/projects"))

# Create persistent output directory for patch files
PATCH_OUTPUT_DIR = Path(os.getenv("PATCH_OUTPUT_DIR", "/tmp/patches"))
PATCH_OUTPUT_DIR = Path(os.getenv("PATCH_OUTPUT_DIR", "/patches/"))
PATCH_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

PATCH_OUTPUT_BEFORE_DIR = Path(os.getenv("PATCH_OUTPUT_BEFORE_DIR", "/tmp/patches_before"))
PATCH_OUTPUT_BEFORE_DIR.mkdir(parents=True, exist_ok=True)
INFILL_SPLIT = ">>> [ INFILL ] <<<"

# ────────────────────────── Utilities ───────────────────────────
def md5(text: str) -> str:
    return hashlib.md5(text.strip().lower().encode()).hexdigest()

def is_unified_diff(txt: str) -> bool:
    return txt.lstrip().startswith(("--- ", "diff ", "@@ "))

def extract_inline_snippet(llm: str) -> str:
    """Return code between the first triple-backtick block or raw text."""
    m = re.search(r"```(?:\w*\n)?([\s\S]*?)```", llm, re.S)
    # return (m.group(1) if m else llm).strip()
    return m.group(1).strip() if m else None

def parse_bug_id(bug_id: str):
    proj, _, sha = bug_id.partition("@")
    if not proj or not sha:
        raise ValueError(f"bug_id must be 'project@sha', got: {bug_id}")
    return proj, sha

# ────────────────────────── Loaders ────────────────────────────
def load_metadata(paths: List[str]) -> int:
    count = 0
    for p in paths:
        with open(p) as f:
            lines = json.load(f)
            data = {x["commit_after"]: x for x in lines}
            META_DICT.update(data)
            count += len(data)
    return count

def load_guidance(csv_path: str) -> int:
    global guidance_df
    guidance_df = pd.read_csv(csv_path)
    guidance_df["commit_after"] = guidance_df["github"].str.split(
        "/commit/|/commits/"
    ).str[-1]
    guidance_df["project"] = (
        guidance_df["github"]
        .str.replace(r"https?://(api\.github\.com/repos/|github\.com/)", "", regex=True)
        .str.replace(".git", "").str.replace("/", "___")
    )
    guidance_df["src_path"] = guidance_df["src_path"].apply(
        lambda x: str(PATCH_OUTPUT_BEFORE_DIR / os.path.basename(x).strip())
    )
    
    return len(guidance_df)

# def load_src_content(jsonl_path: str) -> int:
#     cnt = 0
#
#     def save_src_content(idx, content):
#         # fd3cb2497364d350632c288ce3771738499f718e___checkmemoryleak.cpp
#         idx = os.path.basename(idx)
#         sha = idx[40:]
#         assert idx[41] == "_", idx
#         idx = PATCH_OUTPUT_BEFORE_DIR / idx
#         idx.write_text(content)
#         return idx
#
#     with open(jsonl_path) as f:
#         for line in f:
#             rec = json.loads(line)
#             if "id" in rec and "content" in rec:
#                 idx = save_src_content(idx=rec["id"], content=rec["content"])
#                 SRC_CONTENT[str(idx)] = rec["content"]
#                 cnt += 1
#     SRC_CONTENT["d72ccf06c98259d7261e0f3ac4fd8717778782c1___extracts.cpp"]=PATCH_OUTPUT_BEFORE_DIR/"d72ccf06c98259d7261e0f3ac4fd8717778782c1___extracts.cpp".read_text()
#     return cnt
def load_src_content(jsonl_path: str) -> int:
    cnt = 0

    with open(jsonl_path, 'r') as f:
        for line in f:
            rec = json.loads(line)
            src_id  = rec.get("id")
            content = rec.get("content")
            if not src_id or content is None:
                continue

            filename = os.path.basename(src_id)
            parts = filename.split("___", 1)
            if len(parts) != 2:
                raise ValueError(f"Invalid id format: {src_id!r}")
            sha, rest = parts
            if len(sha) != 40:  # expecting a 40-char SHA
                raise ValueError(f"Invalid SHA length in id: {sha!r}")

            out_path = PATCH_OUTPUT_BEFORE_DIR / filename
            out_path.write_text(content)
            SRC_CONTENT[str(out_path)] = content
            cnt += 1

    # optionally preload a known extract file if present
    extract_file = "d72ccf06c98259d7261e0f3ac4fd8717778782c1___extracts.cpp"
    extract_path = PATCH_OUTPUT_BEFORE_DIR / extract_file
    print ("d72ccf06c98259d7261e0f3ac4fd8717778782c1___extracts", extract_path.exists() )
    if extract_path.exists():
        SRC_CONTENT[str(extract_path)] = extract_path.read_text(
            encoding='utf-8', errors='ignore'
        )
    cnt = len(SRC_CONTENT)
    return cnt


# ─────────────── helpers reused by write_patch ───────────────
def load_meta_record(bug_id: str):
    try:
        proj, sha = bug_id.split("@", 1)
        if sha not in META_DICT:
            raise RuntimeError(f"SHA {sha} not found in metadata, total len.META_DICT=={len(META_DICT)}")
        return proj, META_DICT[sha]
    except Exception as e:
        print(f"{bug_id}:Record not found for {str(e)}")
        raise RuntimeError(f"{bug_id}:Record not found for {str(e)}")

def apply_patch_diff(bug_id: str, diff_text: str, tmp: Path, src_path_content: str):
    proj, rec = load_meta_record(bug_id)
    loc = rec["files"]["src0_location"]
    f_start = loc.get("hunk_start_byte") or loc["byte_start"]
    f_end = loc.get("hunk_end_byte") or loc["byte_end"]
    
    original = src_path_content
    old, new = [], []
    for ln in diff_text.splitlines():
        if ln.startswith("-") and not ln.startswith("---"):
            old.append(ln[1:].rstrip())
        elif ln.startswith("+") and not ln.startswith("+++"):
            new.append(ln[1:].rstrip())
    
    original_segment = original[f_start:f_end]
    if "\n".join(old) not in original_segment:
        raise RuntimeError(f"Context mismatch in byte range [{f_start}:{f_end}] for {bug_id}")
    
    updated = original[:f_start] + "\n".join(new) + "\n" + original[f_end:]
    tmp.write_text(updated)
    
    return {
        "func_start_byte": f_start,
        "func_end_byte": f_start + len("\n".join(new)) + 1,
        "changed_content": [line + "\n" for line in new],
    }

def apply_direct_replace(bug_id: str, direct_text: str, tmp: Path, src_path_content: str):
    """Byte-accurate replacement of the function body."""
    proj, sha = bug_id.split("@", 1)
    _, rec = load_meta_record(bug_id)
    
    row = guidance_df.loc[guidance_df["commit_after"] == sha].iloc[0]
    f_start = row["func_start_byte"]
    f_end = row["func_end_byte"]
    
    is_replace_infill = sha in PROMPT_CONTENT
    replacement = direct_text.rstrip() + "\n"
    
    if is_replace_infill:
        prompt_processed = PROMPT_CONTENT[sha]["prompt_processed"]
        prompt_processed = prompt_processed.replace(INFILL_SPLIT, direct_text)
        return {
            "func_start_byte": f_start,
            "func_end_byte": f_end,  # f_start + len(replacement),
            "changed_content": [prompt_processed],
        }
    
    updated = src_path_content[:f_start] + replacement + src_path_content[f_end:]
    tmp.write_text(updated)
    
    return {
        "func_start_byte": f_start,
        "func_end_byte": f_end,  # f_start + len(replacement),
        "changed_content": [replacement],
    }

inline_patch_via_meta = apply_patch_diff  # alias

def embed_patch(sha, patch_part):
    if sha not in META_DICT_PREFIX_SUFFIX:
        return None
    assert sha in META_DICT_PREFIX_SUFFIX, sha
    meta = META_DICT_PREFIX_SUFFIX[sha]
    if "prefix" not in meta:
        return patch_part  # func
    prefix = meta["prefix"]
    suffix = meta["suffix"]
    return "\n".join([prefix, patch_part, suffix])

def apply_prefix_replace(bug_id: str, direct_text: str, tmp: Path, src_path_content: str):
    """Byte-accurate replacement of the function body."""
    proj, sha = bug_id.split("@", 1)
    _, rec = load_meta_record(bug_id)
    
    row = guidance_df.loc[guidance_df["commit_after"] == sha].iloc[0]
    f_start = row["func_start_byte"]
    f_end = row["func_end_byte"]
    
    replacement = direct_text.rstrip() + "\n"
    
    if sha not in META_DICT_PREFIX_SUFFIX:
        return apply_direct_replace(bug_id=bug_id, direct_text=direct_text, tmp=tmp, src_path_content=src_path_content)
    
    assert sha in META_DICT_PREFIX_SUFFIX, sha
    meta = META_DICT_PREFIX_SUFFIX[sha]
    if "prefix" not in meta:
        return {
            "func_start_byte": f_start,
            "func_end_byte": f_end,
            "changed_content": [replacement],
        }  # func
    
    prefix = meta["prefix"]
    suffix = meta["suffix"]
    replacement = "\n".join([prefix, direct_text.rstrip() + "\n", suffix])
    replacement = replacement.strip() + "\n"
    return {
        "func_start_byte": f_start,
        "func_end_byte": f_end,
        "changed_content": [replacement],
    }  # func

def format_patch_header(patch_content: str, original_path: str, sha: str) -> str:
    """Format patch header to use proper file paths instead of temp paths."""
    lines = patch_content.splitlines()
    if len(lines) < 4:
        return patch_content
    
    formatted_lines = []
    for i, line in enumerate(lines):
        if line.startswith("diff --git"):
            # Replace with proper paths
            formatted_lines.append(f"diff --git a{original_path} b{original_path}")
        elif line.startswith("--- a/"):
            formatted_lines.append(f"--- a{original_path}")
        elif line.startswith("+++ b/"):
            formatted_lines.append(f"+++ b{original_path}")
        else:
            formatted_lines.append(line)
    
    return "\n".join(formatted_lines)

# ─────────────── patch-file builder (no code-snippet) ───────────────
def create_patch_file(df: pd.DataFrame, info: Dict[str, Any], generate_diff=False, persist_flag=False):
    """Create patch file using temporary or persistent files, return patch content and metadata."""
    row = df.loc[df["commit_after"] == info["sha"]]
    if row.empty:
        return None, f"Bug ID {info['bug_id']} not found in guidance data"
    row = row.iloc[0]
    
    sha = info["sha"]
    
    src_path = row["src_path"].strip()
    src_path = PATCH_OUTPUT_BEFORE_DIR / os.path.basename(src_path)
    
    if not src_path.exists():
        return None, f"Source file not found: {src_path}"
    
    content = SRC_CONTENT.get(str(src_path))
    if content is None:
        return None, f"Source content not cached for {src_path} (original: {row['src_path']})"
    
    patched = (
        content[: row["func_start_byte"]] +
        info["patch"] +
        content[row["func_end_byte"] :]
    )
    
    # Create fix file based on persist_flag
    if persist_flag:
        # Create persistent file with structured naming
        out_dir = PATCH_OUTPUT_DIR / info["project"]
        out_dir.mkdir(parents=True, exist_ok=True)
        fix_file = out_dir / f"{info['md5']}@{Path(src_path).name}"
        fix_file.write_text(patched)
    else:
        # Create temporary file for the patched content in PATCH_OUTPUT_DIR
        with tempfile.NamedTemporaryFile(
            mode='w',
            suffix=f"@{Path(src_path).name}",
            dir=PATCH_OUTPUT_DIR,
            delete=False
        ) as temp_file:
            temp_file.write(patched)
            fix_file = Path(temp_file.name)
    
    try:
        # Generate git diff and capture the patch content as bytes
        result = subprocess.run(
            f"git diff --no-index -- {src_path} {fix_file}",
            shell=True,
            capture_output=True  # stdout/stderr will be bytes
        )
        # decode with errors ignored
        raw_patch_content = result.stdout.decode('utf-8', errors='ignore')
        
        # Format the patch header to use proper file paths
        sha     = info["sha"]
        project = info["project"]
        
        # Try to get original path from metadata first
        try:
            _, meta_rec       = load_meta_record(info["bug_id"])
            original_src_path = meta_rec["files"]["src"][0]
            original_path     = f"{ROOT_OUT}/{project}/git_repo_dir_{sha}/{original_src_path}"
        except:
            original_path = f"{ROOT_OUT}/{project}/git_repo_dir_{sha}/unknown_path.cpp"
        
        patch_content = format_patch_header(raw_patch_content, original_path, sha)
        
        patch_file_path = None
        if generate_diff:
            # Save patch to file when generate_diff=True
            if persist_flag:
                out_dir = PATCH_OUTPUT_DIR / project
                out_dir.mkdir(parents=True, exist_ok=True)
                patch_file_path = out_dir / f"{info['md5']}@{Path(src_path).name}.patch"
                patch_file_path.write_text(patch_content)
            else:
                with tempfile.NamedTemporaryFile(
                    mode='w',
                    suffix='.patch',
                    dir=PATCH_OUTPUT_DIR,
                    delete=False
                ) as patch_temp:
                    patch_temp.write(patch_content)
                    patch_file_path = patch_temp.name
        
        meta = {
            "bug_id":     info["bug_id"],
            "sha":        info["sha"],
            "fix_p":      str(fix_file),
            "fix_p_diff": str(patch_file_path) if patch_file_path else None,
            "patch":      patch_content,
        }
        return meta, None
    
    finally:
        # Clean up files only if not persisting
        if not persist_flag:
            fix_file.unlink(missing_ok=True)
            if generate_diff and patch_file_path and Path(patch_file_path).exists():
                Path(patch_file_path).unlink(missing_ok=True)

# ──────────────────────── Schemas ─────────────────────────
class WritePatchRequest(BaseModel):
    bug_id: str  # "project@sha"
    llm_response: str  # inline or unified diff
    method: str = "prefix"  # optional override
    generate_diff: bool = True  # store *.patch diff
    persist_flag: bool = False  # save files persistently or use tempfiles

class WritePatchResponse(BaseModel):
    success: bool
    md5_hash: Optional[str] = None
    patch_content: Optional[str] = None
    bug_id: Optional[str] = None
    sha: Optional[str] = None
    fix_p: Optional[str] = None
    fix_p_diff: Optional[str] = None
    func_start_byte: Optional[int] = None
    func_end_byte: Optional[int] = None
    content: Optional[str] = None
    error: Optional[str] = None
    error_code: Optional[str] = None

@app.post("/build_patch", response_model=WritePatchResponse)
def write_patch(req: WritePatchRequest):
    try:
        project, sha = parse_bug_id(req.bug_id)
    except ValueError as e:
        raise create_http_error(400, ErrorCodes.ERR_INVALID_BUG_ID_FORMAT, str(e))
    
    if guidance_df is None:
        raise create_http_error(400, ErrorCodes.ERR_GUIDANCE_NOT_LOADED, "Guidance data not loaded")
    
    row = guidance_df.loc[guidance_df["commit_after"] == sha]
    if row.empty:
        raise create_http_error(400, ErrorCodes.ERR_BUG_ID_NOT_IN_GUIDANCE, f"Bug ID {req.bug_id} not found in guidance data")
    
    row = row.iloc[0]
    src_path = row["src_path"]
    
    try:
        _, rec = load_meta_record(req.bug_id)
    except RuntimeError as e:
        raise create_http_error(400, ErrorCodes.ERR_RECORD_NOT_FOUND, str(e))
    
    if src_path not in SRC_CONTENT:
        raise create_http_error(400, ErrorCodes.ERR_SRC_CONTENT_NOT_CACHED, f"Source content not cached for {src_path}")
    
    src_path_content = SRC_CONTENT[src_path]
    
    # choose patching strategy
    method = (req.method or "").lower()
    if method not in {"diff", "inline", "inline+meta", "direct", "prefix"}:
        method = "inline+meta" if is_unified_diff(req.llm_response) else "direct"
    
    # Use tempfile.mkstemp() - it doesn't auto-delete by default
    tmp_fd, tmp_path = tempfile.mkstemp()
    tmp = Path(tmp_path)
    
    patch_text = None
    try:
        os.close(tmp_fd)  # Close the file descriptor but keep the file
        
        if method == "diff":
            tmp.write_text(src_path_content)
            chg = apply_patch_diff(req.bug_id, req.llm_response, tmp, src_path_content)
        elif method == "inline+meta":
            chg = inline_patch_via_meta(req.bug_id, req.llm_response, tmp, src_path_content)
        elif method == "prefix":
            chg = apply_prefix_replace(req.bug_id, req.llm_response, tmp, src_path_content)
        else:  # direct/inline
            snippet = extract_inline_snippet(req.llm_response)
            if not snippet:
                raise create_http_error(400, ErrorCodes.ERR_MARKDOWN_EXTRACT_FAIL, "markdown extract fail")
            
            snippet = snippet.rstrip() + "\n"
            chg = apply_direct_replace(req.bug_id, snippet, tmp, src_path_content)
        
        patch_text = "".join(chg["changed_content"])
    except RuntimeError as e:
        if "context mismatch" in str(e).lower():
            raise create_http_error(400, ErrorCodes.ERR_CONTEXT_MISMATCH, str(e))
        else:
            raise create_http_error(400, ErrorCodes.ERR_PATCH_FILE_CREATION_FAILED, str(e))
    finally:
        tmp.unlink(missing_ok=True)
    
    if not patch_text:
        raise create_http_error(400, ErrorCodes.ERR_NO_PATCH_CONTENT, "Cannot identify patch content")
    
    md5_hash = md5(patch_text)
    info = {
        "sha": sha,
        "bug_id": req.bug_id,
        "project": project,
        "patch": patch_text,
        "md5": md5_hash,
    }
    
    # Pass persist_flag to create_patch_file
    meta, err = create_patch_file(guidance_df, info, req.generate_diff, req.persist_flag)
    if meta is None:
        # Determine appropriate error code based on error message
        if "not found in guidance data" in err:
            error_code = ErrorCodes.ERR_BUG_ID_NOT_IN_GUIDANCE
        elif "not cached" in err:
            error_code = ErrorCodes.ERR_SRC_CONTENT_NOT_CACHED
        else:
            error_code = ErrorCodes.ERR_PATCH_FILE_CREATION_FAILED
        
        return WritePatchResponse(success=False, error=err, error_code=error_code)
    
    # Extract patch content from meta and expand all meta fields into response
    diff_content = meta.pop("patch")
    
    return WritePatchResponse(
        success=True,
        md5_hash=md5_hash,
        patch_content=diff_content,
        bug_id=meta["bug_id"],
        sha=meta["sha"],
        fix_p=meta["fix_p"],
        fix_p_diff=meta["fix_p_diff"],
        func_start_byte=chg["func_start_byte"],
        func_end_byte=chg["func_end_byte"],
        content=patch_text,
    )

def load_prompt_list(prompt_json_p):
    """
    only hunk and single_line
    """
    global PROMPT_CONTENT
    
    def extract_context(prompt_str):
        p_str = extract_inline_snippet(prompt_str)
        if INFILL_SPLIT in p_str:
            return p_str
        return None
    
    with open(prompt_json_p) as fr:
        lines = [json.loads(x) for x in fr.readlines()]
    for i in range(len(lines)):
        item = lines[i]
        prompt_str = item["prompt"][1]["content"]
        prompt_str = extract_context(prompt_str)
        if not prompt_str:
            continue
        
        lines[i]["prompt_processed"] = prompt_str
        sha = os.path.basename(item["idx"])[:40]
        assert os.path.basename(item["idx"])[41] == "_", os.path.basename(item["idx"])
        lines[i]["sha"] = sha
    
    PROMPT_CONTENT = {x["sha"]: x for x in lines if "prompt_processed" in x}
    # print("Loaded prompt content for:", list(PROMPT_CONTENT.keys())[:10])
    return len(PROMPT_CONTENT)

def load_prefix_suffix_meta(prefix_dirs=None):
    role = "buggy_errmsg"
    meta = {}
    
    raw_dirs = [
        HERE / f"../data/{role}/single_function_repair.json",
        HERE / f"../data/{role}/single_function_single_hunk_repair.json",
        HERE / f"../data/{role}/single_function_single_line_repair.json",
        HERE / f"../data/{role}_cve/single_function_repair.json",
        HERE / f"../data/{role}_cve/single_function_single_hunk_repair.json",
        HERE / f"../data/{role}_cve/single_function_single_line_repair.json",
    ]
    raw_dirs = prefix_dirs or raw_dirs
    
    print("load meta")
    [meta.update(json.load(open(x))) for x in raw_dirs]
    print("load meta, done")
    meta = {k[40:]: v for k, v in meta.items()}
    META_DICT_PREFIX_SUFFIX.update(meta)
    return len(META_DICT_PREFIX_SUFFIX)

# ───────────────────── startup: load all data ─────────────
HERE = Path("/src/data")  # PathPath(__file__).resolve()#.parent

@app.on_event("startup")
def init_data():
    meta_paths = (
        glob.glob(os.path.join(str(ROOT_SRC), "projects/**/bug*.json"), recursive=True) +
        glob.glob(os.path.join(str(ROOT_SRC), "projects_v1/**/bug*.json"), recursive=True)
    )
    print(f"startup: scanning {len(meta_paths)} metadata files")
    prefix = 0
    p = []
    m = load_metadata(meta_paths)
    g = load_guidance(str(HERE / "../data/raw_info_step1.csv"))
    s = load_src_content(str(HERE / "../data/github_src_path.jsonl"))
    p = load_prompt_list(str(HERE / "../data/single_function_allinone.saved.jsonl"))
    
    prefix = load_prefix_suffix_meta()
    print(f"[startup] metadata={m}, guidance={g}, src_content={s}, prompt_len={p}, prefix={prefix} ")
