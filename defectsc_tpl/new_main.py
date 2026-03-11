#!/usr/bin/env python3
"""
defects4c_api.py – unified Bug-Runner + Patch-Builder service

Usable two ways:

  1. Standalone (gunicorn / uvicorn):
       gunicorn defects4c_api:app -k uvicorn.workers.UvicornWorker ...

  2. Mounted inside main.py via include_router:
       from defects4c_api import app as defects4c_app, init_data
       main_app.include_router(defects4c_app.router, tags=["defects4c"])
       # call init_data() from main.py's startup handler

Exports (for main.py)
---------------------
  app          – FastAPI instance (has .router for include_router)
  router       – APIRouter (same routes, use whichever is convenient)
  init_data()  – loads all data; safe to call from an external startup event
  load_metadata / load_guidance / load_src_content /
  load_prompt_list / load_prefix_suffix_meta
  ROOT_SRC, META_DICT, guidance_df, SRC_CONTENT, PROMPT_CONTENT, META_DICT_PREFIX_SUFFIX
"""

import asyncio
import base64
import glob
import hashlib
import json
import os
import random
import re
import shlex
import stat
import subprocess
import tempfile
import traceback
import uuid
from collections import deque
from pathlib import Path
from typing import Any, Dict, List, Optional

import jmespath
import pandas as pd
import redis
from fastapi import APIRouter, BackgroundTasks, FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from jinja2 import Environment, FileSystemLoader
from pydantic import BaseModel

try:
    import openai as _openai_lib
except ImportError:
    _openai_lib = None  # type: ignore

from config import PROJECTS_DIR

# ─────────────────────────── Global paths ────────────────────────────

SRC_ROOT  = Path(os.getenv("SRC_DIR",  "/src/"))
ROOT_SRC  = SRC_ROOT                                  # alias used by main.py
OUT_ROOT  = Path(os.getenv("ROOT_DIR", "/out/"))

PATCH_OUTPUT_DIR = Path(os.getenv("PATCH_OUTPUT_DIR", "/patches/"))
PATCH_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

PATCH_OUTPUT_BEFORE_DIR = Path(os.getenv("PATCH_OUTPUT_BEFORE_DIR", "/tmp/patches_before"))
PATCH_OUTPUT_BEFORE_DIR.mkdir(parents=True, exist_ok=True)

HERE = Path("/src/data")

INFILL_SPLIT = ">>> [ INFILL ] <<<"

# ─────────────────────────── LLM / Prompt globals ────────────────────

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
MODELNAME      = os.getenv("LLM_MODEL", "deepseek-chat")

PROMPT_DATA: Dict[str, Any] = {}   # bug_id → prompt record (populated by init_data)

# ─────────────────────────── In-memory stores ────────────────────────

META_DICT: Dict[str, Dict[str, Any]] = {}   # sha -> {**bug_record, "project": str}
META_DICT_PREFIX_SUFFIX: Dict[str, Any] = {}
guidance_df: Optional[pd.DataFrame] = None
SRC_CONTENT: Dict[str, str] = {}            # abs-path str -> file text
PROMPT_CONTENT: Dict[str, Any] = {}         # sha -> prompt record
SHA_META_DICT: Dict[str, str] = {}          # sha -> project name

# Regex for parsing GitHub commit URLs → (owner___repo, sha)
_SHA_URL_RE = re.compile(
    r"repos/(?P<owner>[^/]+)/(?P<repo>[^/]+)/commits/(?P<sha>[0-9a-f]{7,40})",
    re.I,
)

# ─────────────────────────── Redis ───────────────────────────────────

class RedisManager:
    _instance     = None
    _redis_client = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if self._redis_client is None:
            self._redis_client = redis.Redis(
                host     = os.getenv("REDIS_HOST", "localhost"),
                port     = int(os.getenv("REDIS_PORT", 6379)),
                db       = int(os.getenv("REDIS_DB",   0)),
                password = os.getenv("REDIS_PASSWORD", None),
                decode_responses       = True,
                socket_connect_timeout = 5,
                socket_timeout         = 5,
            )

    @property
    def client(self):
        return self._redis_client

    def is_connected(self) -> bool:
        try:
            self._redis_client.ping()
            return True
        except Exception:
            return False


redis_manager = RedisManager()

sha_locks: Dict[str, asyncio.Lock] = {}
tasks:     Dict[str, dict]         = {}   # in-memory store for /reproduce tasks

# ─────────────────────────── Pydantic models ─────────────────────────

class ReproduceRequest(BaseModel):
    bug_id: str
    is_force_cleanup: bool = True

class FixRequest(BaseModel):
    bug_id: str
    patch_path: str

class WritePatchRequest(BaseModel):
    bug_id:        str
    llm_response:  str
    method:        str  = "prefix"
    generate_diff: bool = True
    persist_flag:  bool = False

class WritePatchResponse(BaseModel):
    success:          bool
    md5_hash:         Optional[str] = None
    patch_content:    Optional[str] = None
    bug_id:           Optional[str] = None
    sha:              Optional[str] = None
    fix_p:            Optional[str] = None
    fix_p_diff:       Optional[str] = None
    func_start_byte:  Optional[int] = None
    func_end_byte:    Optional[int] = None
    content:          Optional[str] = None
    error:            Optional[str] = None
    error_code:       Optional[str] = None

class CodeFixRequest(BaseModel):
    code:     str
    feedback: str = ""
    model:    str = MODELNAME

# ─────────────────────────── Error codes ─────────────────────────────

class ErrorCodes:
    ERR_MARKDOWN_EXTRACT_FAIL      = "err_extract_code_fail"
    ERR_INVALID_BUG_ID_FORMAT      = "err_invalid_bug_id_format"
    ERR_GUIDANCE_NOT_LOADED        = "err_guidance_not_loaded"
    ERR_BUG_ID_NOT_IN_GUIDANCE     = "err_bug_id_not_in_guidance"
    ERR_RECORD_NOT_FOUND           = "err_record_not_found"
    ERR_SRC_CONTENT_NOT_CACHED     = "err_src_content_not_cached"
    ERR_CONTEXT_MISMATCH           = "err_context_mismatch_byte_range"
    ERR_NO_PATCH_CONTENT           = "err_no_patch_content_identified"
    ERR_PATCH_FILE_CREATION_FAILED = "err_patch_file_creation_failed"

def _http_err(status: int, code: str, msg: str) -> HTTPException:
    return HTTPException(status_code=status, detail={"error_code": code, "message": msg})

# Public alias – keeps both naming conventions working
create_http_error = _http_err

# ─────────────────────────── LLM debugger ────────────────────────────

class LLMDebugger:
    """Wraps an OpenAI-compatible client to generate and parse C/C++ fixes."""

    @staticmethod
    def _prompt(code: str, error_message: str) -> str:
        return (
            "Please analyze the following C/C++ code and fix the error:\n\n"
            f"ERROR MESSAGE:\n{error_message}\n\nCODE:\n{code}\n\n"
            "Respond in this format:\n"
            "<fixed_code>\n[fixed code]\n</fixed_code>\n\n"
            "<explanation>\n[explanation]\n</explanation>\n\n"
            "<changes_made>\n- change 1\n</changes_made>"
        )

    @staticmethod
    def _client():
        if _openai_lib is None:
            raise RuntimeError("openai package not installed")
        return _openai_lib.OpenAI(api_key=OPENAI_API_KEY)

    @staticmethod
    def _parse(content: str) -> dict:
        def _extract(tag: str) -> str:
            s = content.find(f"<{tag}>")
            e = content.find(f"</{tag}>")
            return content[s + len(tag) + 2:e].strip() if s != -1 and e != -1 else ""

        fixed  = _extract("fixed_code")
        expl   = _extract("explanation")
        ch_txt = _extract("changes_made")
        changes = [l.strip().lstrip("- •") for l in ch_txt.splitlines() if l.strip()]
        return {"fixed_code": fixed, "explanation": expl, "changes_made": changes}

    @classmethod
    def fix_code(cls, code: str, error_message: str, model: str = MODELNAME,
                 stream: bool = False):
        try:
            client = cls._client()
            messages = [
                {"role": "system", "content": "You are an expert C/C++ debugger."},
                {"role": "user",   "content": cls._prompt(code, error_message)},
            ]
            kwargs = dict(model=model, messages=messages, temperature=0.7, max_tokens=4096)
            if stream:
                return client.chat.completions.create(**kwargs, stream=True)
            resp    = client.chat.completions.create(**kwargs)
            content = resp.choices[0].message.content
            result  = cls._parse(content)
            return {**result, "fixed_code": result["fixed_code"] or code}
        except Exception as exc:
            if stream:
                raise
            return {"fixed_code": code,
                    "explanation": f"LLM error: {exc}",
                    "changes_made": []}

# ─────────────────────────── Small utilities ─────────────────────────

def md5(text: str) -> str:
    return hashlib.md5(text.strip().lower().encode()).hexdigest()

def is_unified_diff(txt: str) -> bool:
    return txt.lstrip().startswith(("--- ", "diff ", "@@ "))

def extract_inline_snippet(llm: str) -> Optional[str]:
    m = re.search(r"```(?:\w*\n)?([\s\S]*?)```", llm, re.S)
    return m.group(1).strip() if m else None

def parse_bug_id(bug_id: str):
    project, _, sha = bug_id.partition("@")
    if not project or not sha:
        raise ValueError("Bug ID must be in format 'project@sha'")
    return project, sha

def apt_install_tool() -> str:
    return """
apt_install_fn() {
    library=$1
    if dpkg -s "$library" &>/dev/null || which "$library" &>/dev/null; then
        echo "$library is already installed"
    else
        echo "$library is not installed, attempting to install..."
        sudo apt-get update -y && sudo apt-get install -y "$library"
    fi
}
"""

def read_file_limited(path, max_lines: int = 100, max_tokens: int = 512, keep_tail: bool = True) -> str:
    path = Path(path)
    if not path.exists():
        return ""
    with path.open("r", encoding="utf-8", errors="ignore") as fh:
        lines = deque(fh, maxlen=max_lines)
    tokens = " ".join(l.rstrip("\n") for l in lines).split()
    if len(tokens) > max_tokens:
        tokens = tokens[-max_tokens:] if keep_tail else tokens[:max_tokens]
    return " ".join(tokens)

# ─────────────────────────── Redis helpers ───────────────────────────

def extract_patch_md5(patch_path: str) -> str:
    basename = os.path.basename(patch_path)
    if "@" in basename and len(basename.split("@", 1)[0]) == 32:
        return basename.split("@", 1)[0]
    m = re.search(r"([a-f0-9]{32})", basename)
    return m.group(1) if m else hashlib.md5(patch_path.encode()).hexdigest()

def build_redis_key(bug_id: str, patch_path: str) -> str:
    _, sha = parse_bug_id(bug_id)
    return f"patch_{sha}_{extract_patch_md5(patch_path)}.log"

def redis_key_to_handle(redis_key: str) -> str:
    return base64.b64encode(redis_key.encode()).decode()

def handle_to_redis_key(handle: str) -> str:
    try:
        return base64.b64decode(handle.encode()).decode()
    except Exception:
        raise ValueError("Invalid handle format")

def store_task_in_redis(handle: str, task_data: dict, ttl: int = 86400):
    try:
        if not redis_manager.is_connected():
            return
        data = dict(task_data)
        if "log_paths"   in data: data["log_paths"]   = json.dumps(data["log_paths"])
        if "return_code" in data: data["return_code"] = str(data["return_code"])
        if "cached"      in data: data["cached"]      = str(data["cached"]).lower()
        for k, v in data.items():
            if isinstance(v, (dict, list)):              data[k] = json.dumps(v)
            elif v is None:                              data[k] = ""
            elif not isinstance(v, (str, int, float, bytes)): data[k] = str(v)
        task_key = f"task_{handle_to_redis_key(handle)}"
        redis_manager.client.hset(task_key, mapping=data)
        redis_manager.client.expire(task_key, ttl)
    except Exception as e:
        print(f"Error storing task in Redis: {e}")

def parse_redis_key(redis_key: str):
    """Return (project, sha, patch_md5) from a key like patch_{sha}_{md5}.log"""
    if not (redis_key.startswith("patch_") and redis_key.endswith(".log")):
        raise ValueError(f"Invalid Redis key format: {redis_key}")
    inner = redis_key[6:-4]
    parts = inner.split("_")
    if len(parts) < 2:
        raise ValueError(f"Cannot parse Redis key: {redis_key}")
    sha       = parts[0]
    patch_md5 = "_".join(parts[1:])
    if sha not in META_DICT:
        raise ValueError(f"Cannot find project for sha: {sha}")
    return META_DICT[sha]["project"], sha, patch_md5

def get_log_file_paths(project: str, sha: str, patch_md5: str) -> dict:
    log_dir = OUT_ROOT / project / "logs"
    return {
        "log":    str(log_dir / f"patch_{sha}_{patch_md5}.log"),
        "msg":    str(log_dir / f"patch_{sha}_{patch_md5}.msg"),
        "status": str(log_dir / f"patch_{sha}_{patch_md5}.status"),
    }

def read_result_from_files(project: str, sha: str, patch_md5: str) -> Optional[dict]:
    try:
        lp = get_log_file_paths(project, sha, patch_md5)
        if not os.path.exists(lp["log"]):
            return None
        rc = -1
        if os.path.exists(lp["status"]):
            try:
                c = open(lp["status"]).read().strip()
                if c.isdigit(): rc = int(c)
            except Exception:
                pass
        return {
            "status":      "completed" if rc == 0 else "failed",
            "return_code": rc,
            "fix_log":     read_file_limited(lp["log"]),
            "fix_msg":     read_file_limited(lp["msg"]),
            "fix_status":  read_file_limited(lp["status"]),
            "error":       f"Exit code {rc}" if rc != 0 else "",
            "timestamp":   str(os.path.getmtime(lp["log"])),
            "from_cache":  False,
            "from_files":  True,
        }
    except Exception as e:
        print(f"Error reading result from files: {e}")
        return None

def get_task_from_redis(handle: str) -> Optional[dict]:
    try:
        redis_key = handle_to_redis_key(handle)
        if redis_manager.is_connected():
            data = redis_manager.client.hgetall(f"task_{redis_key}")
            if data:
                data = dict(data)
                if data.get("return_code"):
                    try: data["return_code"] = int(data["return_code"])
                    except ValueError: pass
                if data.get("log_paths"):
                    try: data["log_paths"] = json.loads(data["log_paths"])
                    except json.JSONDecodeError: pass
                if "cached" in data:
                    data["cached"] = data["cached"].lower() == "true"
                for k, v in data.items():
                    if isinstance(v, str) and (v.startswith("{") or v.startswith("[")):
                        try: data[k] = json.loads(v)
                        except json.JSONDecodeError: pass
                return data
        # Fallback: read from disk
        try:
            project, sha, patch_md5 = parse_redis_key(redis_key)
            fr = read_result_from_files(project, sha, patch_md5)
            print("hit from local disk", fr, project, sha, patch_md5)
            if fr:
                lp = get_log_file_paths(project, sha, patch_md5)
                return {
                    "bug_id":      f"{project}@{sha}",
                    "sha":         sha,
                    "status":      fr["status"],
                    "return_code": fr["return_code"],
                    "fix_log":     fr["fix_log"],
                    "fix_msg":     fr["fix_msg"],
                    "fix_status":  fr["fix_status"],
                    "error":       fr["error"],
                    "timestamp":   fr["timestamp"],
                    "log_paths":   lp,
                    "result":      {"log_file": lp["log"], "return_code": fr["return_code"]},
                    "patch":       f"unknown_patch_{patch_md5}",
                    "redis_key":   redis_key,
                    "cached":      False,
                    "from_files":  True,
                }
        except Exception as e:
            print(f"Error reading from files for handle {handle}: {e}")
    except Exception as e:
        print(f"Error reading task from Redis: {e}")
    return None

def get_cached_result(redis_key: str) -> Optional[dict]:
    try:
        if redis_manager.is_connected():
            d = redis_manager.client.hgetall(redis_key)
            if d:
                return {
                    "status":      d.get("status", "unknown"),
                    "return_code": int(d.get("return_code", -1)),
                    "fix_log":     d.get("fix_log", ""),
                    "fix_msg":     d.get("fix_msg", ""),
                    "fix_status":  d.get("fix_status", ""),
                    "error":       d.get("error", ""),
                    "timestamp":   d.get("timestamp", ""),
                    "from_cache":  True,
                }
        # Fallback: read from disk
        try:
            project, sha, patch_md5 = parse_redis_key(redis_key)
            fr = read_result_from_files(project, sha, patch_md5)
            if fr:
                return {k: fr[k] for k in (
                    "status", "return_code", "fix_log", "fix_msg",
                    "fix_status", "error", "timestamp", "from_cache", "from_files"
                )}
        except Exception as e:
            print(f"Error reading from files for redis_key {redis_key}: {e}")
    except Exception as e:
        print(f"Error reading from Redis: {e}")
    return None

def cache_result(redis_key: str, result_data: dict):
    try:
        if not redis_manager.is_connected():
            return
        redis_manager.client.hset(redis_key, mapping={
            "status":      result_data.get("status", "unknown"),
            "return_code": str(result_data.get("return_code", -1)),
            "fix_log":     result_data.get("fix_log", ""),
            "fix_msg":     result_data.get("fix_msg", ""),
            "fix_status":  result_data.get("fix_status", ""),
            "error":       result_data.get("error", ""),
            "timestamp":   str(result_data.get("timestamp", "")),
        })
    except Exception as e:
        print(f"Error caching to Redis: {e}")

# ─────────────────────────── BugsInfo ────────────────────────────────

def exec_cmd(cmd_info: dict, *, raise_on_error: bool = True) -> int:
    cmd = cmd_info.pop("cmd")
    proc = subprocess.run(shlex.split(cmd), **cmd_info)
    if raise_on_error and proc.returncode != 0:
        raise subprocess.CalledProcessError(proc.returncode, cmd)
    return proc.returncode

class BugsInfo:
    def __init__(self, project: str, sha: str):
        if project not in PROJECTS_DIR:
            raise ValueError(f"Unknown project '{project}'")
        self.project       = project
        self.sha           = sha
        self.project_major = PROJECTS_DIR[project]
        self.src_dir       = str(SRC_ROOT)
        self.wrk_git = self._make_dir(
            OUT_ROOT / project / f"git_repo_dir_{sha}",
            OUT_ROOT / project / "git_repo_dir",
        )
        self.wrk_log = self._make_dir(OUT_ROOT / project / "logs")
        self.src_project = (
            SRC_ROOT / "projects_v1" / project
            if self.project_major == "projects_v1"
            else SRC_ROOT / self.project_major / project
        )
        bugs_file = self.src_project / "bugs_list_new.json"
        if not bugs_file.exists():
            bugs_file = self.src_project / "bugs_list.json"
        proj_file = self.src_project / "project.json"
        if not self.src_project.exists() or not bugs_file.exists() or not proj_file.exists():
            raise FileNotFoundError(
                f"Missing metadata in {self.src_project}; "
                f"bugs_file={bugs_file} proj_file={proj_file}"
            )
        with open(bugs_file) as f: meta_bugs           = json.load(f)
        with open(proj_file)  as f: self.meta_project  = json.load(f)

        matches: List[dict] = jmespath.search(f"[?commit_after=='{sha}']", meta_bugs)
        if len(matches) != 1:
            raise ValueError(f"Bug {sha} not found or ambiguous")
        self.meta_defect = matches[0]

        def _j(path, data):
            d = jmespath.search(path, data) or []
            if isinstance(d, dict):
                d = {k: v for k, v in d.items() if v is not None}
            return d

        compile_block = {
            **(_j("c_compile", self.meta_project) or {}),
            **(_j("c_compile", self.meta_defect)  or {}),
            "build_flags": (_j("c_compile.build_flags", self.meta_project)
                            + _j("c_compile.build_flags", self.meta_defect)),
            "test_flags":  (_j("c_compile.test_flags",  self.meta_project)
                            + _j("c_compile.test_flags",  self.meta_defect)),
            "env":         (_j("env", self.meta_project)
                            + _j("c_compile.env", self.meta_defect)),
        }
        compile_block = {k: v for k, v in compile_block.items() if v}

        self.meta_info: Dict[str, Any] = {
            "apt_install_fn": apt_install_tool(),
            "cpu_count":      max((os.cpu_count() or 2) - 1, 1),
            **self.meta_defect,
            "repo_dir":   self.wrk_git,
            "log_dir":    self.wrk_log,
            "build_dir":  f"build_{sha}",
            "test_log":   str(self.wrk_log / f"test_{sha}_fix.log"),
            "test_files": jmespath.search("files.test",   self.meta_defect),
            "src_file":   jmespath.search("files.src[0]", self.meta_defect),
            **compile_block,
        }

    def _make_dir(self, *candidates: Path) -> Path:
        for i, p in enumerate(candidates):
            if p.exists() or i == 0:
                p.mkdir(parents=True, exist_ok=True)
                return p
        last = candidates[-1]
        last.mkdir(parents=True, exist_ok=True)
        return last

    def _render_template(self, tpl: str, info: dict, dest: Path):
        tpl_path = str(tpl)
        if not os.path.exists(tpl_path):
            dest.write_text("#!/bin/bash\necho 'dummy script'\n")
        else:
            env = Environment(loader=FileSystemLoader(os.path.dirname(tpl_path) or "."))
            dest.write_text(env.get_template(os.path.basename(tpl_path)).render(**info))
        os.chmod(dest, stat.S_IRWXU | stat.S_IRWXG | stat.S_IRWXO)

    def _tpl_build(self):
        if "build" in self.meta_info and ".jinja" in str(self.meta_info["build"]):
            return os.path.join(self.src_project, self.meta_info["build"])
        return os.path.abspath(os.path.join("projects_v1", "common_build_tpl.jinja"))

    def _tpl_test(self):
        if "test" in self.meta_info and ".jinja" in str(self.meta_info["test"]):
            return os.path.join(self.src_project, self.meta_info["test"])
        return os.path.abspath(os.path.join("projects_v1", "common_test_tpl.jinja"))

    def set_reproduce_build(self):
        if self.project_major == "projects_v1":
            workflow_tpl = os.path.join(self.src_dir, self.project_major, "workflow_cmake_tpl.jinja")
        else:
            name = "workflow_tpl_user.jinja" if "znc___znc" in str(self.src_project) else "workflow_tpl.jinja"
            workflow_tpl = os.path.join(self.src_dir, self.project_major, name)
        self._render_template(self._tpl_build(), self.meta_info,                         self.wrk_git / "inplace_build.sh")
        self._render_template(self._tpl_build(), {**self.meta_info, "is_rebuild": True}, self.wrk_git / "inplace_rebuild.sh")
        self._render_template(self._tpl_test(),  self.meta_info,                         self.wrk_git / "inplace_test.sh")
        self._render_template(workflow_tpl,      self.meta_info,                         self.wrk_git / "run_reproduce.sh")

    def set_patch_build(self):
        workflow_tpl = os.path.join(self.src_dir, self.project_major, "workflow_cmake_rebuild_tpl.jinja")
        self._render_template(
            self._tpl_build(),
            {**self.meta_info, "is_rebuild": True,
             "test_log": str(self.wrk_log / f"test_{self.sha}_fix.log")},
            self.wrk_git / "inplace_rebuild.sh",
        )
        self._render_template(self._tpl_test(), self.meta_info, self.wrk_git / "inplace_test.sh")
        self._render_template(
            workflow_tpl,
            {**self.meta_info, "test_log": str(self.wrk_log / f"patch_{self.sha}_fix.log")},
            self.wrk_git / "run_patch.sh",
        )

# ─────────────────────────── Runner functions ────────────────────────

def _run_reproduce(instance: BugsInfo, log_path: str, force_cleanup: bool) -> int:
    timeout = 60 * 60 if "llvm" in instance.project else 60 * 30
    with open(log_path, "w") as lf:
        if force_cleanup:
            exec_cmd({"cmd": "git clean -dfx", "cwd": instance.wrk_git, "stdout": lf, "stderr": lf})
        instance.set_reproduce_build()
        return exec_cmd(
            {"cmd": "bash run_reproduce.sh", "cwd": instance.wrk_git,
             "stdout": lf, "stderr": lf, "timeout": timeout},
            raise_on_error=False,
        )

def _run_fix(instance: BugsInfo, patch: str, log_path: str) -> int:
    if not os.path.isfile(patch):
        raise FileNotFoundError(patch)
    with open(log_path, "a") as lf:
        instance.set_patch_build()
        return exec_cmd(
            {"cmd": f"bash run_patch.sh {patch}", "cwd": instance.wrk_git,
             "stdout": lf, "stderr": lf, "timeout": 60 * 30},
            raise_on_error=False,
        )

def prepare_result_data(instance: BugsInfo, patch_md5: str, rc: int, error: str = "") -> dict:
    lp = get_log_file_paths(instance.project, instance.sha, patch_md5)
    return {
        "status":      "completed" if rc == 0 else "failed",
        "return_code": rc,
        "fix_log":     read_file_limited(lp["log"]),
        "fix_msg":     read_file_limited(lp["msg"]),
        "fix_status":  read_file_limited(lp["status"]),
        "error":       error,
        "timestamp":   str(asyncio.get_event_loop().time()),
        "log_paths":   lp,
    }

# ─────────────────────────── Background tasks ────────────────────────

async def run_reproduce_queue(instance: BugsInfo, log_path: str, handle: str, force_cleanup: bool):
    lock = sha_locks.setdefault(instance.sha, asyncio.Lock())
    async with lock:
        tasks[handle]["status"] = "running"
        try:
            rc = await asyncio.to_thread(_run_reproduce, instance, log_path, force_cleanup)
            tasks[handle]["result"] = {"log_file": log_path, "return_code": rc}
            tasks[handle]["status"] = "completed" if rc == 0 else "failed"
            if rc != 0:
                tasks[handle]["error"] = f"run_reproduce.sh exited {rc}"
        except Exception:
            tasks[handle]["status"] = "failed"
            tasks[handle]["error"]  = traceback.format_exc()

def _build_fix_task(instance, patch, log_path, redis_key, result_data, rc, cached=False):
    return {
        "bug_id":      f"{instance.project}@{instance.sha}",
        "sha":         instance.sha,
        "status":      result_data["status"],
        "return_code": result_data["return_code"],
        "fix_log":     result_data["fix_log"],
        "fix_msg":     result_data["fix_msg"],
        "fix_status":  result_data["fix_status"],
        "error":       result_data["error"],
        "timestamp":   result_data["timestamp"],
        "log_paths":   result_data["log_paths"],
        "result":      {"log_file": log_path, "return_code": rc},
        "patch":       patch,
        "redis_key":   redis_key,
        "cached":      cached,
    }

async def run_fix_queue(instance: BugsInfo, patch: str, log_path: str, handle: str, redis_key: str):
    lock = sha_locks.setdefault(instance.sha, asyncio.Lock())
    async with lock:
        store_task_in_redis(handle, {
            "bug_id": f"{instance.project}@{instance.sha}", "sha": instance.sha,
            "status": "running", "patch": patch, "redis_key": redis_key, "cached": False,
        })

        # Cache check (includes file fallback via get_cached_result)
        cached = get_cached_result(redis_key)
        if cached:
            patch_md5 = extract_patch_md5(patch)
            lp = get_log_file_paths(instance.project, instance.sha, patch_md5)
            fake = {**cached, "log_paths": lp}
            store_task_in_redis(handle, _build_fix_task(
                instance, patch, log_path, redis_key, fake, cached["return_code"], cached=True
            ))
            return

        patch_md5 = extract_patch_md5(patch)
        lp = get_log_file_paths(instance.project, instance.sha, patch_md5)

        # Skip execution if log already exists on disk
        if os.path.exists(lp["log"]):
            print(f"Log files already exist for {patch_md5}, skipping execution")
            try:
                rc = -1
                if os.path.exists(lp["status"]):
                    c = open(lp["status"]).read().strip()
                    if c.isdigit(): rc = int(c)
                rd = prepare_result_data(instance, patch_md5, rc,
                                         f"run_patch.sh exited {rc}" if rc != 0 else "")
                store_task_in_redis(handle, _build_fix_task(instance, patch, log_path, redis_key, rd, rc))
                cache_result(redis_key, rd)
                return
            except Exception as e:
                print(f"Error reading existing log files: {e}")

        try:
            rc = await asyncio.to_thread(_run_fix, instance, patch, log_path)
            rd = prepare_result_data(instance, patch_md5, rc,
                                      f"run_patch.sh exited {rc}" if rc != 0 else "")
            store_task_in_redis(handle, _build_fix_task(instance, patch, log_path, redis_key, rd, rc))
            cache_result(redis_key, rd)
        except Exception:
            error_msg = traceback.format_exc()
            store_task_in_redis(handle, {
                "bug_id":    f"{instance.project}@{instance.sha}", "sha": instance.sha,
                "status":    "failed", "error": error_msg,
                "patch":     patch, "redis_key": redis_key, "cached": False,
            })
            cache_result(redis_key, {
                "status": "failed", "return_code": -1,
                "fix_log": "", "fix_msg": "", "fix_status": "",
                "error": error_msg, "timestamp": str(asyncio.get_event_loop().time()),
            })

# ─────────────────────────── Patch helpers ───────────────────────────

def load_meta_record(bug_id: str):
    proj, sha = bug_id.split("@", 1)
    if sha not in META_DICT:
        raise RuntimeError(f"{bug_id}: SHA {sha} not found in metadata (total={len(META_DICT)})")
    return proj, META_DICT[sha]

def apply_patch_diff(bug_id: str, diff_text: str, tmp: Path, src_path_content: str) -> dict:
    _, rec  = load_meta_record(bug_id)
    loc     = rec["files"]["src0_location"]
    f_start = loc.get("hunk_start_byte") or loc["byte_start"]
    f_end   = loc.get("hunk_end_byte")   or loc["byte_end"]
    old, new = [], []
    for ln in diff_text.splitlines():
        if ln.startswith("-") and not ln.startswith("---"):
            old.append(ln[1:].rstrip())
        elif ln.startswith("+") and not ln.startswith("+++"):
            new.append(ln[1:].rstrip())
    if "\n".join(old) not in src_path_content[f_start:f_end]:
        raise RuntimeError(f"Context mismatch in byte range [{f_start}:{f_end}] for {bug_id}")
    joined = "\n".join(new)
    tmp.write_text(src_path_content[:f_start] + joined + "\n" + src_path_content[f_end:])
    return {"func_start_byte": f_start, "func_end_byte": f_start + len(joined) + 1,
            "changed_content": [l + "\n" for l in new]}

inline_patch_via_meta = apply_patch_diff

def apply_direct_replace(bug_id: str, direct_text: str, tmp: Path, src_path_content: str) -> dict:
    _, sha = bug_id.split("@", 1)
    row = guidance_df.loc[guidance_df["commit_after"] == sha].iloc[0]
    f_start, f_end = int(row["func_start_byte"]), int(row["func_end_byte"])
    replacement = direct_text.rstrip() + "\n"
    if sha in PROMPT_CONTENT:
        processed = PROMPT_CONTENT[sha]["prompt_processed"].replace(INFILL_SPLIT, direct_text)
        return {"func_start_byte": f_start, "func_end_byte": f_end, "changed_content": [processed]}
    tmp.write_text(src_path_content[:f_start] + replacement + src_path_content[f_end:])
    return {"func_start_byte": f_start, "func_end_byte": f_end, "changed_content": [replacement]}

def apply_prefix_replace(bug_id: str, direct_text: str, tmp: Path, src_path_content: str) -> dict:
    _, sha = bug_id.split("@", 1)
    row = guidance_df.loc[guidance_df["commit_after"] == sha].iloc[0]
    f_start, f_end = int(row["func_start_byte"]), int(row["func_end_byte"])
    if sha not in META_DICT_PREFIX_SUFFIX:
        return apply_direct_replace(bug_id, direct_text, tmp, src_path_content)
    meta = META_DICT_PREFIX_SUFFIX[sha]
    if "prefix" not in meta:
        return {"func_start_byte": f_start, "func_end_byte": f_end,
                "changed_content": [direct_text.rstrip() + "\n"]}
    replacement = ("\n".join([meta["prefix"], direct_text.rstrip() + "\n", meta["suffix"]])).strip() + "\n"
    return {"func_start_byte": f_start, "func_end_byte": f_end, "changed_content": [replacement]}

def format_patch_header(patch_content: str, original_path: str) -> str:
    out = []
    for line in patch_content.splitlines():
        if   line.startswith("diff --git"): out.append(f"diff --git a{original_path} b{original_path}")
        elif line.startswith("--- a/"):     out.append(f"--- a{original_path}")
        elif line.startswith("+++ b/"):     out.append(f"+++ b{original_path}")
        else:                               out.append(line)
    return "\n".join(out)

def create_patch_file(df: pd.DataFrame, info: Dict[str, Any], generate_diff=False, persist_flag=False):
    row = df.loc[df["commit_after"] == info["sha"]]
    if row.empty:
        return None, f"Bug ID {info['bug_id']} not found in guidance data"
    row = row.iloc[0]
    src_path = PATCH_OUTPUT_BEFORE_DIR / os.path.basename(str(row["src_path"]).strip())
    if not src_path.exists():
        return None, f"Source file not found: {src_path}"
    content = SRC_CONTENT.get(str(src_path))
    if content is None:
        return None, f"Source content not cached for {src_path}"

    patched = (content[:int(row["func_start_byte"])]
               + info["patch"]
               + content[int(row["func_end_byte"]):])

    if persist_flag:
        out_dir = PATCH_OUTPUT_DIR / info["project"]
        out_dir.mkdir(parents=True, exist_ok=True)
        fix_file = out_dir / f"{info['md5']}@{src_path.name}"
        fix_file.write_text(patched)
    else:
        fd, tmp_path = tempfile.mkstemp(suffix=f"@{src_path.name}", dir=PATCH_OUTPUT_DIR)
        os.close(fd)
        fix_file = Path(tmp_path)
        fix_file.write_text(patched)

    try:
        result = subprocess.run(
            f"git diff --no-index -- {src_path} {fix_file}",
            shell=True, capture_output=True,
        )
        raw_patch = result.stdout.decode("utf-8", errors="ignore")
        sha, project = info["sha"], info["project"]
        try:
            _, meta_rec   = load_meta_record(info["bug_id"])
            original_src  = meta_rec["files"]["src"][0]
            original_path = f"{OUT_ROOT}/{project}/git_repo_dir_{sha}/{original_src}"
        except Exception:
            original_path = f"{OUT_ROOT}/{project}/git_repo_dir_{sha}/unknown_path.cpp"

        patch_content  = format_patch_header(raw_patch, original_path)
        patch_file_path = None
        if generate_diff:
            if persist_flag:
                out_dir = PATCH_OUTPUT_DIR / project
                out_dir.mkdir(parents=True, exist_ok=True)
                patch_file_path = out_dir / f"{info['md5']}@{src_path.name}.patch"
                patch_file_path.write_text(patch_content)
            else:
                fd2, pp = tempfile.mkstemp(suffix=".patch", dir=PATCH_OUTPUT_DIR)
                os.close(fd2)
                patch_file_path = Path(pp)
                patch_file_path.write_text(patch_content)

        return {
            "bug_id":     info["bug_id"],
            "sha":        sha,
            "fix_p":      str(fix_file),
            "fix_p_diff": str(patch_file_path) if patch_file_path else None,
            "patch":      patch_content,
        }, None
    finally:
        if not persist_flag:
            fix_file.unlink(missing_ok=True)
            if generate_diff and patch_file_path and Path(str(patch_file_path)).exists():
                Path(str(patch_file_path)).unlink(missing_ok=True)

# ─────────────────────────── Data loaders (importable by main.py) ────

def load_metadata(paths: List[str]) -> int:
    """Populate META_DICT from bug*.json files."""
    count = 0
    for p in paths:
        with open(p) as f:
            lines = json.load(f)
        project = os.path.basename(os.path.dirname(p))
        data = {x["commit_after"]: {**x, "project": project} for x in lines}
        META_DICT.update(data)
        count += len(data)
    return count

def load_guidance(csv_path: str) -> int:
    """Populate guidance_df from CSV."""
    global guidance_df
    guidance_df = pd.read_csv(csv_path)
    guidance_df["commit_after"] = (
        guidance_df["github"].str.split("/commit/|/commits/").str[-1]
    )
    guidance_df["project"] = (
        guidance_df["github"]
        .str.replace(r"https?://(api\.github\.com/repos/|github\.com/)", "", regex=True)
        .str.replace(".git", "").str.replace("/", "___")
    )
    guidance_df["src_path"] = guidance_df["src_path"].apply(
        lambda x: str(PATCH_OUTPUT_BEFORE_DIR / os.path.basename(x).strip())
    )
    return len(guidance_df)

def load_src_content(jsonl_path: str) -> int:
    """Populate SRC_CONTENT from JSONL of {id, content}."""
    with open(jsonl_path) as f:
        for line in f:
            rec = json.loads(line)
            src_id, content = rec.get("id"), rec.get("content")
            if not src_id or content is None:
                continue
            filename = os.path.basename(src_id)
            parts = filename.split("___", 1)
            if len(parts) != 2 or len(parts[0]) != 40:
                continue
            out_path = PATCH_OUTPUT_BEFORE_DIR / filename
            out_path.write_text(content)
            SRC_CONTENT[str(out_path)] = content
    extract_path = (PATCH_OUTPUT_BEFORE_DIR
                    / "d72ccf06c98259d7261e0f3ac4fd8717778782c1___extracts.cpp")
    if extract_path.exists():
        SRC_CONTENT[str(extract_path)] = extract_path.read_text(encoding="utf-8", errors="ignore")
    return len(SRC_CONTENT)

def load_prompt_list(prompt_json_p: str) -> int:
    """Populate PROMPT_CONTENT from JSONL of prompts."""
    global PROMPT_CONTENT
    with open(prompt_json_p) as fr:
        lines = [json.loads(x) for x in fr]
    result = {}
    for item in lines:
        prompt_parts = item.get("prompt", [])
        prompt_str   = prompt_parts[1]["content"] if len(prompt_parts) > 1 else ""
        snippet      = extract_inline_snippet(prompt_str)
        if not snippet or INFILL_SPLIT not in snippet:
            continue
        idx_base = os.path.basename(item.get("idx", ""))
        sha = idx_base[:40]
        if len(sha) == 40:
            result[sha] = {**item, "prompt_processed": snippet, "sha": sha}
    PROMPT_CONTENT = result
    return len(PROMPT_CONTENT)

def load_prefix_suffix_meta(prefix_dirs=None) -> int:
    """Populate META_DICT_PREFIX_SUFFIX from per-role JSON files."""
    role = "buggy_errmsg"
    default_dirs = [
        HERE / f"../data/{role}/single_function_repair.json",
        HERE / f"../data/{role}/single_function_single_hunk_repair.json",
        HERE / f"../data/{role}/single_function_single_line_repair.json",
        HERE / f"../data/{role}_cve/single_function_repair.json",
        HERE / f"../data/{role}_cve/single_function_single_hunk_repair.json",
        HERE / f"../data/{role}_cve/single_function_single_line_repair.json",
    ]
    meta = {}
    for x in (prefix_dirs or default_dirs):
        try:
            meta.update(json.load(open(x)))
        except (FileNotFoundError, json.JSONDecodeError):
            pass
    # Keys are sha40 + rest; strip sha prefix to get the suffix key
    META_DICT_PREFIX_SUFFIX.update({k[40:]: v for k, v in meta.items()})
    return len(META_DICT_PREFIX_SUFFIX)


def load_meta_sha_with_project(csv_path: Optional[str] = None) -> int:
    """
    Build SHA → project mapping from the raw_info CSV and populate SHA_META_DICT.

    Mirrors the SHA_META_DICT logic that was in prompt_api.py's startup event.
    Called by init_data() so the mapping is available to prompt/defect endpoints.

    Returns the number of entries loaded (0 if file is missing or on error).
    """
    global SHA_META_DICT

    if csv_path is None or not Path(csv_path).is_file():
        return 0

    def _parse_url(url: str):
        m = _SHA_URL_RE.search(url or "")
        if not m:
            return None, None
        return f"{m.group('owner')}___{m.group('repo')}", m.group("sha")

    try:
        df = pd.read_csv(csv_path)
        url_col = (
            df["api_url"].fillna(df["github"])
            if "api_url" in df.columns
            else df["github"]
        )
        parsed       = url_col.apply(lambda u: pd.Series(_parse_url(u)))
        df["_proj"]  = parsed[0]
        df["_sha"]   = parsed[1]
        df = df.dropna(subset=["_sha"])
        SHA_META_DICT.update(
            pd.Series(df["_proj"].values, index=df["_sha"]).to_dict()
        )
        return len(SHA_META_DICT)
    except Exception as exc:
        print(f"[load_meta_sha_with_project] error: {exc}")
        return 0


def load_prompt_data_for_api() -> int:
    """
    Build PROMPT_DATA (bug_id → record) from the already-loaded PROMPT_CONTENT.
    Must be called after load_prompt_list() and load_meta_sha_with_project().
    Returns the number of entries loaded.
    """
    global PROMPT_DATA
    raw = {x["idx"]: x for x in PROMPT_CONTENT.values()}

    result: Dict[str, Any] = {}
    for idx, entry in raw.items():
        try:
            proj, sha = parse_bug_id(idx)
            bug_id = f"{proj}@{sha}"
        except ValueError:
            # Fallback: use SHA_META_DICT to reconstruct project@sha
            sha = idx[:40] if len(idx) >= 40 else idx
            project = SHA_META_DICT.get(sha)
            bug_id = f"{project}@{sha}" if project else sha
        entry = dict(entry)
        entry["bug_id"] = bug_id
        result[bug_id] = entry

    PROMPT_DATA = result
    return len(PROMPT_DATA)


def init_data(here: Optional[Path] = None):
    """
    Load all runtime data.

    Can be called from:
      - an external startup handler in main.py (pass here=Path(__file__).parent)
      - the local app's on_event("startup")

    Parameters
    ----------
    here : Path, optional
        Parent directory containing the ./data subfolder.
        Defaults to /src (i.e. HERE.parent).
    """
    base = here or HERE.parent   # /src by default

    meta_paths = (
        glob.glob(os.path.join(str(ROOT_SRC), "projects/**/bug*.json"),    recursive=True) +
        glob.glob(os.path.join(str(ROOT_SRC), "projects_v1/**/bug*.json"), recursive=True)
    )
    print(f"[defects4c_api] startup: scanning {len(meta_paths)} metadata files")
    m = load_metadata(meta_paths)

    guidance_csv = base / "data/raw_info_step1.csv"
    src_jsonl    = base / "data/github_src_path.jsonl"
    prompt_jsonl = base / "data/single_function_allinone.saved.jsonl"

    g      = load_guidance(str(guidance_csv))    if guidance_csv.exists()  else 0
    s      = load_src_content(str(src_jsonl))    if src_jsonl.exists()     else 0
    p      = load_prompt_list(str(prompt_jsonl)) if prompt_jsonl.exists()  else 0
    sha_m  = load_meta_sha_with_project(str(guidance_csv) if guidance_csv.exists() else None)
    pd_    = load_prompt_data_for_api()
    prefix = load_prefix_suffix_meta()

    print(f"[defects4c_api] metadata={m}, guidance={g}, "
          f"src_content={s}, prompt_len={p}, sha_meta={sha_m}, "
          f"prompt_data={pd_}, prefix={prefix}")

# ─────────────────────────── Router + App ────────────────────────────
#
#  All HTTP endpoints live on `router`.
#  `app` wraps `router` for standalone deployment and exposes `app.router`
#  for use with include_router in main.py.
#
# Usage in main.py:
#   from defects4c_api import app as defects4c_app, init_data
#   main_app.include_router(defects4c_app.router, tags=["defects4c"])

router = APIRouter()

@router.get("/health")
def health():
    return {"status": "ok"}

@router.get("/projects")
def list_projects():
    return {"projects": list(PROJECTS_DIR)}

@router.post("/reproduce")
def reproduce(req: ReproduceRequest, background_tasks: BackgroundTasks):
    try:
        project, sha = parse_bug_id(req.bug_id)
        instance = BugsInfo(project, sha)
    except Exception:
        raise HTTPException(status_code=400, detail=traceback.format_exc())
    handle   = uuid.uuid4().hex
    log_file = str(instance.wrk_log / f"{sha}_reproduce_{handle}.log")
    tasks[handle] = {
        "bug_id": req.bug_id, "sha": sha, "status": "queued",
        "log_file": log_file, "force_cleanup": req.is_force_cleanup,
    }
    background_tasks.add_task(run_reproduce_queue, instance, log_file, handle, req.is_force_cleanup)
    return {"handle": handle}

@router.post("/fix")
def fix(req: FixRequest, background_tasks: BackgroundTasks):
    try:
        project, sha = parse_bug_id(req.bug_id)
        instance = BugsInfo(project, sha)
    except Exception:
        raise HTTPException(status_code=400, detail=traceback.format_exc())

    redis_key = build_redis_key(req.bug_id, req.patch_path)
    handle    = redis_key_to_handle(redis_key)
    patch_md5 = extract_patch_md5(req.patch_path)
    log_paths = get_log_file_paths(project, sha, patch_md5)

    cached = get_cached_result(redis_key)
    if cached:
        store_task_in_redis(handle, {
            "bug_id":      req.bug_id,      "sha":    sha,
            "status":      cached["status"],
            "return_code": cached["return_code"],
            "fix_log":     cached["fix_log"],
            "fix_msg":     cached["fix_msg"],
            "fix_status":  cached["fix_status"],
            "error":       cached.get("error", ""),
            "timestamp":   cached.get("timestamp", ""),
            "log_paths":   log_paths,
            "patch":       req.patch_path,
            "redis_key":   redis_key,
            "cached":      True,
        })
        return {"handle": handle, "redis_key": redis_key}

    store_task_in_redis(handle, {
        "bug_id": req.bug_id, "sha": sha, "status": "queued",
        "log_paths": log_paths, "patch": req.patch_path,
        "redis_key": redis_key, "cached": False,
    })
    background_tasks.add_task(
        run_fix_queue, instance, req.patch_path, log_paths["log"], handle, redis_key
    )
    return {"handle": handle, "redis_key": redis_key}

@router.get("/status/{handle}")
def get_status(handle: str):
    if handle in tasks:
        return tasks[handle].copy()
    data = get_task_from_redis(handle)
    if data is None:
        raise HTTPException(status_code=404, detail="Handle not found")
    return data

@router.get("/cache/status")
def get_cache_status():
    return {
        "redis_connected": redis_manager.is_connected(),
        "redis_info":      redis_manager.client.info() if redis_manager.is_connected() else None,
    }

@router.delete("/cache/{redis_key}")
def clear_cache_entry(redis_key: str):
    try:
        if not redis_manager.is_connected():
            raise HTTPException(status_code=503, detail="Redis not connected")
        return {"deleted": bool(redis_manager.client.delete(redis_key)), "key": redis_key}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/all_tasks")
def get_all_tasks():
    all_tasks = dict(tasks)
    try:
        if redis_manager.is_connected():
            for task_key in redis_manager.client.keys("task_*"):
                redis_key = task_key[5:]    # strip leading "task_"
                handle    = redis_key_to_handle(redis_key)
                if handle not in all_tasks:
                    d = get_task_from_redis(handle)
                    if d: all_tasks[handle] = d
    except Exception as e:
        print(f"Error fetching Redis tasks: {e}")
    return all_tasks

@router.post("/build_patch", response_model=WritePatchResponse)
def write_patch(req: WritePatchRequest):
    try:
        project, sha = parse_bug_id(req.bug_id)
    except ValueError as e:
        raise _http_err(400, ErrorCodes.ERR_INVALID_BUG_ID_FORMAT, str(e))

    if guidance_df is None:
        raise _http_err(400, ErrorCodes.ERR_GUIDANCE_NOT_LOADED, "Guidance data not loaded")

    row = guidance_df.loc[guidance_df["commit_after"] == sha]
    if row.empty:
        raise _http_err(400, ErrorCodes.ERR_BUG_ID_NOT_IN_GUIDANCE,
                        f"Bug ID {req.bug_id} not found in guidance data")
    row      = row.iloc[0]
    src_path = row["src_path"]

    try:
        _, rec = load_meta_record(req.bug_id)
    except RuntimeError as e:
        raise _http_err(400, ErrorCodes.ERR_RECORD_NOT_FOUND, str(e))

    if src_path not in SRC_CONTENT:
        raise _http_err(400, ErrorCodes.ERR_SRC_CONTENT_NOT_CACHED,
                        f"Source content not cached for {src_path}")

    src_content = SRC_CONTENT[src_path]
    method = (req.method or "").lower()
    if method not in {"diff", "inline", "inline+meta", "direct", "prefix"}:
        method = "inline+meta" if is_unified_diff(req.llm_response) else "direct"

    fd, tmp_path = tempfile.mkstemp()
    tmp  = Path(tmp_path)
    chg  = None
    patch_text = None
    try:
        os.close(fd)
        if method == "diff":
            tmp.write_text(src_content)
            chg = apply_patch_diff(req.bug_id, req.llm_response, tmp, src_content)
        elif method == "inline+meta":
            chg = inline_patch_via_meta(req.bug_id, req.llm_response, tmp, src_content)
        elif method == "prefix":
            chg = apply_prefix_replace(req.bug_id, req.llm_response, tmp, src_content)
        else:
            snippet = extract_inline_snippet(req.llm_response)
            if not snippet:
                raise _http_err(400, ErrorCodes.ERR_MARKDOWN_EXTRACT_FAIL, "markdown extract fail")
            chg = apply_direct_replace(req.bug_id, snippet.rstrip() + "\n", tmp, src_content)
        patch_text = "".join(chg["changed_content"])
    except HTTPException:
        raise
    except RuntimeError as e:
        ec = (ErrorCodes.ERR_CONTEXT_MISMATCH if "context mismatch" in str(e).lower()
              else ErrorCodes.ERR_PATCH_FILE_CREATION_FAILED)
        raise _http_err(400, ec, str(e))
    finally:
        tmp.unlink(missing_ok=True)

    if not patch_text:
        raise _http_err(400, ErrorCodes.ERR_NO_PATCH_CONTENT, "Cannot identify patch content")

    md5_hash = md5(patch_text)
    info = {"sha": sha, "bug_id": req.bug_id, "project": project,
            "patch": patch_text, "md5": md5_hash}

    meta, err = create_patch_file(guidance_df, info, req.generate_diff, req.persist_flag)
    if meta is None:
        if "not found in guidance" in (err or ""):  ec = ErrorCodes.ERR_BUG_ID_NOT_IN_GUIDANCE
        elif "not cached" in (err or ""):            ec = ErrorCodes.ERR_SRC_CONTENT_NOT_CACHED
        else:                                        ec = ErrorCodes.ERR_PATCH_FILE_CREATION_FAILED
        return WritePatchResponse(success=False, error=err, error_code=ec)

    diff_content = meta.pop("patch")
    return WritePatchResponse(
        success=True, md5_hash=md5_hash, patch_content=diff_content,
        bug_id=meta["bug_id"], sha=meta["sha"],
        fix_p=meta["fix_p"], fix_p_diff=meta["fix_p_diff"],
        func_start_byte=chg["func_start_byte"],
        func_end_byte=chg["func_end_byte"],
        content=patch_text,
    )

# ─────────────────────────── Prompt / LLM endpoints ─────────────────

async def _get_defect_record(defect_id: str) -> dict:
    """Shared logic for /reset and /get_defect/{defect_id}."""
    sha_id   = defect_id.partition("@")[2][:40] or defect_id[:40]
    entry    = dict(PROMPT_DATA[defect_id])
    bug_id   = entry.get("bug_id", defect_id)
    extra: Dict[str, Any] = {}

    if sha_id in META_DICT:
        extra["metadata"] = META_DICT[sha_id]

    if guidance_df is not None:
        row = guidance_df.loc[guidance_df["commit_after"] == sha_id]
        if not row.empty:
            extra["guidance"] = row.iloc[0].to_dict()

    if sha_id in META_DICT_PREFIX_SUFFIX:
        extra["prefix_suffix"] = META_DICT_PREFIX_SUFFIX[sha_id]

    src_path = extra.get("guidance", {}).get("src_path")
    if src_path:
        extra["has_source_content"]    = src_path in SRC_CONTENT
        extra["source_content_length"] = len(SRC_CONTENT[src_path]) if src_path in SRC_CONTENT else 0

    return {
        "status":                 "success",
        "defect_id":              bug_id,
        "sha_id":                 sha_id,
        "bug_id":                 bug_id,
        "prompt_data":            entry,
        "additional_info":        extra,
        "total_defects_available": len(PROMPT_DATA),
    }


@router.get("/reset")
async def reset_random_prompt():
    """Return a randomly selected defect from PROMPT_DATA."""
    if not PROMPT_DATA:
        raise HTTPException(status_code=404, detail="No prompt data available")
    return await _get_defect_record(random.choice(list(PROMPT_DATA)))


@router.get("/get_defect/{defect_id:path}")
async def get_defect(defect_id: str):
    """Return a defect by its bug_id (project@sha)."""
    if not PROMPT_DATA:
        raise HTTPException(status_code=404, detail="No prompt data available")
    if defect_id not in PROMPT_DATA:
        sample = list(PROMPT_DATA)[:10]
        raise HTTPException(
            status_code=404,
            detail=f"Defect '{defect_id}' not found. "
                   f"{len(PROMPT_DATA)} total available, e.g. {sample}",
        )
    try:
        return await _get_defect_record(defect_id)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Error retrieving defect: {exc}")


@router.get("/list_defects_ids")
async def list_defects_ids():
    """List all defect idx keys in PROMPT_DATA."""
    if not PROMPT_DATA:
        raise HTTPException(status_code=404, detail="No prompt data available")
    ids = sorted({v.get("idx", k) for k, v in PROMPT_DATA.items()})
    return {"status": "success", "total_count": len(ids),
            "defect_ids": ids, "sample_ids": ids[:5]}


@router.get("/list_defects_bugid")
async def list_defects_bugid():
    """List all defects in 'project___repo@sha' format."""
    if not PROMPT_DATA:
        raise HTTPException(status_code=404, detail="No prompt data available")
    bug_ids = sorted(v.get("bug_id", k) for k, v in PROMPT_DATA.items())
    return {"status": "success", "total_count": len(bug_ids),
            "defects": bug_ids, "sample_defects": bug_ids[:5]}


@router.post("/ask_llm")
async def ask_llm(request: CodeFixRequest):
    """Non-streaming LLM code-fix."""
    try:
        return LLMDebugger.fix_code(request.code, request.feedback, model=request.model)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"LLM error: {exc}")


@router.post("/ask_llm_stream")
async def ask_llm_stream(request: CodeFixRequest):
    """Streaming LLM code-fix; returns XML-tagged chunks."""

    def _generate():
        chunks: List[str] = []
        try:
            stream = LLMDebugger.fix_code(
                request.code, request.feedback,
                model=request.model, stream=True,
            )
            for chunk in stream:
                delta = ""
                if hasattr(chunk, "choices") and chunk.choices:
                    delta = chunk.choices[0].delta.content or ""
                elif isinstance(chunk, str):
                    delta = chunk
                if delta:
                    chunks.append(delta)
        except Exception as exc:
            yield f"<error>{exc}</error>"
            return

        full = "".join(chunks)

        # If LLM already returned XML tags, pass through unchanged
        if "<fixed_code>" in full:
            yield full
            return

        # Otherwise wrap in expected XML format
        parsed = LLMDebugger._parse(full)
        code_block = parsed["fixed_code"] or request.code
        expl       = parsed["explanation"] or "No explanation provided"
        changes    = "\n".join(f"- {c}" for c in parsed["changes_made"]) or "- No changes listed"
        yield (
            f"<fixed_code>\n{code_block}\n</fixed_code>\n\n"
            f"<explanation>\n{expl}\n</explanation>\n\n"
            f"<changes_made>\n{changes}\n</changes_made>"
        )

    return StreamingResponse(_generate(), media_type="text/plain")


# ─────────────────────────── Standalone FastAPI app ──────────────────

app = FastAPI(title="Defects4C Service", version="2.0.0")
app.include_router(router)

@app.on_event("startup")
def _startup():
    """Runs when used standalone; NOT called when mounted via include_router."""
    init_data()

# ─────────────────────────── CLI entry point ─────────────────────────

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=80)

