#!/usr/bin/env python3
import os
import stat
import shlex
import subprocess
import json
import uuid
import asyncio
import traceback
import hashlib
import re
from pathlib import Path
from typing import Dict, Any, List, Optional

import jmespath
import redis
from fastapi import FastAPI, HTTPException, BackgroundTasks
from pydantic import BaseModel
from jinja2 import Environment, FileSystemLoader

from config import PROJECTS_DIR

app = FastAPI(title="Bug Helper Service", version="1.0.0")

# Redis singleton
class RedisManager:
    _instance = None
    _redis_client = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(RedisManager, cls).__new__(cls)
        return cls._instance
    
    def __init__(self):
        if self._redis_client is None:
            # Initialize Redis connection
            redis_host = os.getenv("REDIS_HOST", "localhost")
            redis_port = int(os.getenv("REDIS_PORT", 6379))
            redis_db = int(os.getenv("REDIS_DB", 0))
            redis_password = os.getenv("REDIS_PASSWORD", None)
            
            self._redis_client = redis.Redis(
                host=redis_host,
                port=redis_port,
                db=redis_db,
                password=redis_password,
                decode_responses=True,
                socket_connect_timeout=5,
                socket_timeout=5
            )
    
    @property
    def client(self):
        return self._redis_client
    
    def is_connected(self) -> bool:
        try:
            self._redis_client.ping()
            return True
        except:
            return False

# Global Redis manager instance
redis_manager = RedisManager()

sha_locks: Dict[str, asyncio.Lock] = {}
tasks: Dict[str, dict] = {}

class ReproduceRequest(BaseModel):
    bug_id: str
    is_force_cleanup: bool = True

class FixRequest(BaseModel):
    bug_id: str
    patch_path: str

def extract_patch_md5(patch_path: str) -> str:
    """Extract MD5 from patch path or generate one from the path"""
    basename = os.path.basename(patch_path)
    
    # Pattern: md5@sha_filename or just md5_filename
    if "@" in basename and len(basename.split("@", 1)[0]) == 32:
        return basename.split("@", 1)[0]
    
    # Look for 32-character hex string in the filename
    md5_pattern = r'([a-f0-9]{32})'
    match = re.search(md5_pattern, basename)
    if match:
        return match.group(1)
    
    # Generate MD5 from the patch path if not found
    return hashlib.md5(patch_path.encode()).hexdigest()

def build_redis_key(bug_id: str, patch_path: str) -> str:
    """Build Redis key from bug_id and patch_path"""
    project, sha = parse_bug_id(bug_id)
    patch_md5 = extract_patch_md5(patch_path)
    return f"patch_{sha}_{patch_md5}.log"

def get_cached_result(redis_key: str) -> Optional[dict]:
    """Get cached result from Redis"""
    try:
        if not redis_manager.is_connected():
            return None
        
        cached_data = redis_manager.client.hgetall(redis_key)
        if cached_data:
            return {
                "status": cached_data.get("status", "unknown"),
                "return_code": int(cached_data.get("return_code", -1)),
                "fix_log": cached_data.get("fix_log", ""),
                "fix_msg": cached_data.get("fix_msg", ""),
                "fix_status": cached_data.get("fix_status", ""),
                "error": cached_data.get("error", ""),
                "timestamp": cached_data.get("timestamp", ""),
                "from_cache": True
            }
    except Exception as e:
        print(f"Error reading from Redis: {e}")
    return None

def cache_result(redis_key: str, result_data: dict, ttl: int = 0 ):
    """Cache result to Redis with TTL (default 24 hours)"""
    try:
        if not redis_manager.is_connected():
            return
        
        # Prepare data for Redis hash
        cache_data = {
            "status": result_data.get("status", "unknown"),
            "return_code": str(result_data.get("return_code", -1)),
            "fix_log": result_data.get("fix_log", ""),
            "fix_msg": result_data.get("fix_msg", ""),
            "fix_status": result_data.get("fix_status", ""),
            "error": result_data.get("error", ""),
            "timestamp": str(result_data.get("timestamp", "")),
        }
        
        # Store as hash with TTL
        redis_manager.client.hset(redis_key, mapping=cache_data)
        #redis_manager.client.expire(redis_key, ttl)
        
    except Exception as e:
        print(f"Error caching to Redis: {e}")

def exec_cmd(cmd_info: dict, *, raise_on_error: bool = True) -> int:
    cmd = cmd_info.pop("cmd")
    proc = subprocess.run(shlex.split(cmd), **cmd_info)
    if raise_on_error and proc.returncode != 0:
        raise subprocess.CalledProcessError(proc.returncode, cmd)
    return proc.returncode

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

class BugsInfo:
    def __init__(self, project: str, sha: str):
        if project not in PROJECTS_DIR:
            raise ValueError(f"Unknown project '{project}'")
        self.project = project
        self.sha = sha
        self.project_major = PROJECTS_DIR[project]
        SRC_ROOT = Path(os.getenv("SRC_DIR", "/src/"))
        OUT_ROOT = Path(os.getenv("ROOT_DIR", "/out/"))
        self.src_dir = str(SRC_ROOT)
        self.wrk_git = self._make_dir(
            OUT_ROOT / project / f"git_repo_dir_{sha}",
            OUT_ROOT / project / "git_repo_dir",
        )
        self.wrk_log = self._make_dir(OUT_ROOT / project / "logs")
        if self.project_major == "projects_v1":
            self.src_project = SRC_ROOT / "projects_v1" / project
        else:
            self.src_project = SRC_ROOT / self.project_major / project
        bugs_file = self.src_project / "bugs_list_new.json"
        if not bugs_file.exists():
            bugs_file = self.src_project / "bugs_list.json"
        proj_file = self.src_project / "project.json"
        if not self.src_project.exists() or not bugs_file.exists() or not proj_file.exists():
            raise FileNotFoundError(
                f"Missing metadata in {self.src_project}; bugs_file={bugs_file} proj_file={proj_file}"
            )
        with open(bugs_file) as f:
            meta_bugs = json.load(f)
        with open(proj_file) as f:
            self.meta_project = json.load(f)
        matches: List[dict] = jmespath.search(f"[?commit_after=='{sha}']", meta_bugs)
        if len(matches) != 1:
            raise ValueError(f"Bug {sha} not found or ambiguous")
        self.meta_defect = matches[0]
        self.meta_info: Dict[str, Any] = {
            "apt_install_fn": apt_install_tool(),
            "cpu_count": max(os.cpu_count() - 1, 1),
            **self.meta_defect,
            "repo_dir": self.wrk_git,
            "log_dir": self.wrk_log,
            "build_dir": f"build_{sha}",
            "test_log": str(self.wrk_log / f"test_{sha}_fix.log"),
            "test_files": jmespath.search("files.test", self.meta_defect),
            "src_file": jmespath.search("files.src[0]", self.meta_defect),
        }
        def _j(path, data):
            _d = jmespath.search(path, data) or []
            if type(_d)==dict :
                _d={k:v for k,v in _d.items() if v is not None }
            return _d 
        build_flags = _j("c_compile.build_flags", self.meta_project) + _j(
            "c_compile.build_flags", self.meta_defect
        )
        test_flags = _j("c_compile.test_flags", self.meta_project) + _j(
            "c_compile.test_flags", self.meta_defect
        )
        env_flags = _j("env", self.meta_project) + _j(
            "c_compile.env", self.meta_defect
        )
        d1= (_j("c_compile", self.meta_project) or {})
        d2= (_j("c_compile", self.meta_defect) or {}) 

        compile_block = {
            **(_j("c_compile", self.meta_project) or {}),
            **(_j("c_compile", self.meta_defect) or {}),
            "build_flags": build_flags,
            "test_flags": test_flags,
            "env": env_flags,
        }
        compile_block = {k: v for k, v in compile_block.items() if v}
        self.meta_info.update(compile_block)
        # print ("-->self.meta_info, ", self.meta_info )

    def _make_dir(self, *candidates: Path) -> Path:
        for p in candidates:
            if p.exists() or not candidates.index(p):
                p.mkdir(parents=True, exist_ok=True)
                return p
        last = candidates[-1]
        last.mkdir(parents=True, exist_ok=True)
        return last
    def _render_template(self, tpl: str, info: dict, dest: Path):
        tpl_path = str(tpl)
        if not os.path.exists(tpl_path):
            with open(dest, "w") as f:
                f.write("#!/bin/bash\necho 'dummy script'\n")
        else:
            env = Environment(loader=FileSystemLoader(os.path.dirname(tpl_path) or "."))
            template = env.get_template(os.path.basename(tpl_path))
            with open(dest, "w") as f:
                f.write(template.render(**info))
        os.chmod(dest, stat.S_IRWXU | stat.S_IRWXG | stat.S_IRWXO)
    def set_reproduce_build(self):
        tpl_build = (
            os.path.join(self.src_project, self.meta_info["build"])
            if "build" in self.meta_info and ".jinja" in str(self.meta_info["build"])
            else os.path.abspath(os.path.join("projects_v1", "common_build_tpl.jinja"))
        )
        tpl_test = (
            os.path.join(self.src_project, self.meta_info["test"])
            if "test" in self.meta_info and ".jinja" in str(self.meta_info["test"])
            else os.path.abspath(os.path.join("projects_v1", "common_test_tpl.jinja"))
        )
        if self.project_major == "projects_v1":
            workflow_tpl = os.path.join(self.src_dir, self.project_major, "workflow_cmake_tpl.jinja")
        else:
            tpl_name = "workflow_tpl_user.jinja" if "znc___znc" in str(self.src_project) else "workflow_tpl.jinja"
            workflow_tpl = os.path.join(self.src_dir, self.project_major, tpl_name)
        self._render_template(tpl_build, self.meta_info, self.wrk_git / "inplace_build.sh")
        self._render_template(tpl_build, {**self.meta_info, "is_rebuild": True}, self.wrk_git / "inplace_rebuild.sh")
        self._render_template(tpl_test, self.meta_info, self.wrk_git / "inplace_test.sh")
        self._render_template(workflow_tpl, self.meta_info, self.wrk_git / "run_reproduce.sh")

    def set_patch_build(self):
        tpl_build = (
            os.path.join(self.src_project, self.meta_info["build"])
            if "build" in self.meta_info and ".jinja" in str(self.meta_info["build"])
            else os.path.abspath(os.path.join("projects_v1", "common_build_tpl.jinja"))
        )
        
        tpl_test = (
            os.path.join(self.src_project, self.meta_info["test"])
            if "test" in self.meta_info and ".jinja" in str(self.meta_info["test"])
            else os.path.abspath(os.path.join("projects_v1", "common_test_tpl.jinja"))
        )
        
        workflow_tpl = os.path.join(self.src_dir, self.project_major, "workflow_cmake_rebuild_tpl.jinja")
            
            
        self._render_template(tpl_build, 
            {**self.meta_info, "is_rebuild": True,"test_log": str(self.wrk_log / f"test_{self.sha}_fix.log")}, 
            self.wrk_git / "inplace_rebuild.sh")
        self._render_template(tpl_test, self.meta_info, self.wrk_git / "inplace_test.sh")
        self._render_template(
            workflow_tpl,
            {**self.meta_info, "test_log": str(self.wrk_log / f"patch_{self.sha}_fix.log")},
            self.wrk_git / "run_patch.sh",
        )
        
        
def _run_reproduce(instance: BugsInfo, log_path: str, force_cleanup: bool) -> int:
    is_llvm = "llvm" in instance.project or "llvm" in str(instance.src_project)
    timeout = 60 * 60 if is_llvm else 60 * 30
    with open(log_path, "w") as log_f:
        if force_cleanup:
            exec_cmd({"cmd": "git clean -dfx", "cwd": instance.wrk_git, "stdout": log_f, "stderr": log_f})
        instance.set_reproduce_build()
        rc = exec_cmd(
            {
                "cmd": "bash run_reproduce.sh",
                "cwd": instance.wrk_git,
                "stdout": log_f,
                "stderr": log_f,
                "timeout": timeout,
            },
            raise_on_error=False,
        )
    return rc

def _run_fix(instance: BugsInfo, patch: str, log_path: str) -> int:
    if not os.path.isfile(patch):
        raise FileNotFoundError(patch)
    with open(log_path, "a") as log_f:
        instance.set_patch_build()
        rc = exec_cmd(
            {
                "cmd": f"bash run_patch.sh {patch}",
                "cwd": instance.wrk_git,
                "stdout": log_f,
                "stderr": log_f,
                "timeout": 60 * 30,
            },
            raise_on_error=False,
        )
    return rc

def read_file_limited(path: str | Path,
                      max_lines: int = 100,
                      max_tokens: int = 512,
                      keep_tail: bool = True) -> str:
    from collections import deque
    path = Path(path)
    if not path.exists():
        return ""
    # Keep only the last `max_lines` while streaming the file
    with path.open("r", encoding="utf-8", errors="ignore") as fh:
        lines = deque(fh, maxlen=max_lines)

    # Collapse to a single string and split on whitespace
    tokens = " ".join(line.rstrip("\n") for line in lines).split()

    if len(tokens) > max_tokens:
        tokens = tokens[-max_tokens:] if keep_tail else tokens[:max_tokens]

    return " ".join(tokens)

def prepare_result_data(instance: BugsInfo, patch_md5: str, rc: int, error: str = "") -> dict:
    """Prepare structured result data for both caching and task storage"""
    log_file = os.path.join(instance.wrk_log, f"patch_{instance.sha}_{patch_md5}.log")
    msg_file = os.path.join(instance.wrk_log, f"patch_{instance.sha}_{patch_md5}.msg")
    status_file = os.path.join(instance.wrk_log, f"patch_{instance.sha}_{patch_md5}.status")
    
    fix_log = read_file_limited(log_file)
    fix_msg = read_file_limited(msg_file)
    fix_status = read_file_limited(status_file)
    
    return {
        "status": "completed" if rc == 0 else "failed",
        "return_code": rc,
        "fix_log": fix_log,
        "fix_msg": fix_msg,
        "fix_status": fix_status,
        "error": error,
        "timestamp": str(asyncio.get_event_loop().time()),
        "log_paths": {
            "log": log_file,
            "msg": msg_file,
            "status": status_file
        }
    }

async def run_reproduce_queue(instance: BugsInfo, log_path: str, handle: str, force_cleanup: bool):
    lock = sha_locks.setdefault(instance.sha, asyncio.Lock())
    async with lock:
        tasks[handle]["status"] = "running"
        try:
            rc = await asyncio.to_thread(_run_reproduce, instance, log_path, force_cleanup)
            tasks[handle]["result"] = {"log_file": log_path, "return_code": rc}
            if rc == 0:
                tasks[handle]["status"] = "completed"
            else:
                tasks[handle]["status"] = "failed"
                tasks[handle]["error"] = f"run_reproduce.sh exited {rc}"
        except Exception:
            tasks[handle]["status"] = "failed"
            tasks[handle]["error"] = traceback.format_exc()

async def run_fix_queue(instance: BugsInfo, patch: str, log_path: str, handle: str, redis_key: str):
    lock = sha_locks.setdefault(instance.sha, asyncio.Lock())
    async with lock:
        tasks[handle]["status"] = "running"
        
        # Double-check cache before doing expensive work
        cached_result = get_cached_result(redis_key)
        if cached_result:
            # Update task with cached data in uniform style
            patch_md5 = extract_patch_md5(patch)
            log_paths = {
                "log": os.path.join(instance.wrk_log, f"patch_{instance.sha}_{patch_md5}.log"),
                "msg": os.path.join(instance.wrk_log, f"patch_{instance.sha}_{patch_md5}.msg"),
                "status": os.path.join(instance.wrk_log, f"patch_{instance.sha}_{patch_md5}.status")
            }
            
            tasks[handle].update({
                "status": cached_result["status"],
                "return_code": cached_result["return_code"],
                "fix_log": cached_result["fix_log"],
                "fix_msg": cached_result["fix_msg"],
                "fix_status": cached_result["fix_status"],
                "error": cached_result.get("error", ""),
                "timestamp": cached_result.get("timestamp", ""),
                "log_paths": log_paths,
                "result": {"log_file": log_path, "return_code": cached_result["return_code"]},
                "cached": True
            })
            return
        
        try:
            rc = await asyncio.to_thread(_run_fix, instance, patch, log_path)
            
            # Extract patch MD5 for file naming
            patch_md5 = extract_patch_md5(patch)
            
            # Prepare structured result data (single source of truth)
            error_msg = f"run_patch.sh exited {rc}" if rc != 0 else ""
            result_data = prepare_result_data(instance, patch_md5, rc, error_msg)
            
            # Update task with structured data
            tasks[handle].update({
                "status": result_data["status"],
                "return_code": result_data["return_code"],
                "fix_log": result_data["fix_log"],
                "fix_msg": result_data["fix_msg"],
                "fix_status": result_data["fix_status"],
                "error": result_data["error"],
                "timestamp": result_data["timestamp"],
                "log_paths": result_data["log_paths"],
                "result": {"log_file": log_path, "return_code": rc},
                "cached": False
            })
            
            # Cache the result (single Redis save)
            cache_result(redis_key, result_data)
            
        except Exception:
            error_msg = traceback.format_exc()
            tasks[handle]["status"] = "failed"
            tasks[handle]["error"] = error_msg
            
            # Cache the error result
            error_result = {
                "status": "failed",
                "return_code": -1,
                "fix_log": "",
                "fix_msg": "",
                "fix_status": "",
                "error": error_msg,
                "timestamp": str(asyncio.get_event_loop().time())
            }
            cache_result(redis_key, error_result)

@app.get("/projects")
def list_projects():
    return {"projects": list(PROJECTS_DIR)}

@app.post("/reproduce")
def reproduce(req: ReproduceRequest, background_tasks: BackgroundTasks):
    try:
        project, sha = parse_bug_id(req.bug_id)
        instance = BugsInfo(project, sha)
    except Exception:
        raise HTTPException(status_code=400, detail=traceback.format_exc())
    handle = uuid.uuid4().hex
    log_file = os.path.join(instance.wrk_log, f"{sha}_reproduce_{handle}.log")
    tasks[handle] = {
        "bug_id": req.bug_id,
        "sha": sha,
        "status": "queued",
        "log_file": log_file,
        "force_cleanup": req.is_force_cleanup,
    }
    background_tasks.add_task(run_reproduce_queue, instance, log_file, handle, req.is_force_cleanup)
    return {"handle": handle}

@app.post("/fix")
def fix(req: FixRequest, background_tasks: BackgroundTasks):
    try:
        project, sha = parse_bug_id(req.bug_id)
        instance = BugsInfo(project, sha)
    except Exception:
        raise HTTPException(status_code=400, detail=traceback.format_exc())

    # Build Redis key and extract patch MD5
    redis_key = build_redis_key(req.bug_id, req.patch_path)
    patch_md5 = extract_patch_md5(req.patch_path)
    handle = uuid.uuid4().hex
    
    # Define log file paths
    log_file = os.path.join(instance.wrk_log, f"patch_{sha}_{patch_md5}.log")
    msg_file = os.path.join(instance.wrk_log, f"patch_{sha}_{patch_md5}.msg")
    status_file = os.path.join(instance.wrk_log, f"patch_{sha}_{patch_md5}.status")
    
    log_paths = {"log": log_file, "msg": msg_file, "status": status_file}

    # Check cache first
    cached_result = get_cached_result(redis_key)
    if cached_result:
        # Store cached result in tasks with consistent structure
        tasks[handle] = {
            "bug_id": req.bug_id,
            "sha": sha,
            "status": cached_result["status"],
            "return_code": cached_result["return_code"],
            "fix_log": cached_result["fix_log"],
            "fix_msg": cached_result["fix_msg"],
            "fix_status": cached_result["fix_status"],
            "error": cached_result.get("error", ""),
            "timestamp": cached_result.get("timestamp", ""),
            "log_paths": log_paths,
            "patch": req.patch_path,
            "redis_key": redis_key,
            "cached": True
        }
        return {"handle": handle, "redis_key": redis_key}
    
    # Not cached, create new task and queue for processing
    tasks[handle] = {
        "bug_id": req.bug_id,
        "sha": sha,
        "status": "queued",
        "log_paths": log_paths,
        "patch": req.patch_path,
        "redis_key": redis_key,
        "cached": False
    }
    
    background_tasks.add_task(run_fix_queue, instance, req.patch_path, log_file, handle, redis_key)
    return {"handle": handle, "redis_key": redis_key}

@app.get("/status/{handle}")
def get_status(handle: str):
    if handle not in tasks:
        raise HTTPException(status_code=404, detail="Handle not found")
    
    # Return task info directly - it's already properly structured
    return tasks[handle].copy()

@app.get("/cache/status")
def get_cache_status():
    """Get Redis connection status"""
    return {
        "redis_connected": redis_manager.is_connected(),
        "redis_info": redis_manager.client.info() if redis_manager.is_connected() else None
    }

@app.delete("/cache/{redis_key}")
def clear_cache_entry(redis_key: str):
    """Clear specific cache entry"""
    try:
        if redis_manager.is_connected():
            result = redis_manager.client.delete(redis_key)
            return {"deleted": bool(result), "key": redis_key}
        else:
            raise HTTPException(status_code=503, detail="Redis not connected")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/all_tasks")
def get_all_tasks():
    return tasks

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
