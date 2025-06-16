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
import base64
from pathlib import Path
from typing import Dict, Any, List, Optional

import jmespath
import redis
from fastapi import FastAPI, HTTPException, BackgroundTasks
from pydantic import BaseModel
from jinja2 import Environment, FileSystemLoader

import glob
from config import PROJECTS_DIR

app = FastAPI(title="Bug Helper Service", version="1.0.0")

SRC_ROOT = Path(os.getenv("SRC_DIR", "/src/"))
ROOT_SRC = SRC_ROOT 
OUT_ROOT = Path(os.getenv("ROOT_DIR", "/out/"))



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
tasks: Dict[str, dict] = {}  # Keep for /reproduce compatibility

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

def redis_key_to_handle(redis_key: str) -> str:
    """Convert Redis key to base64 encoded handle"""
    return base64.b64encode(redis_key.encode()).decode()

def handle_to_redis_key(handle: str) -> str:
    """Convert base64 encoded handle back to Redis key"""
    try:
        return base64.b64decode(handle.encode()).decode()
    except Exception:
        raise ValueError("Invalid handle format")


def store_task_in_redis(handle: str, task_data: dict, ttl: int = 86400):
    """Store task data in Redis using handle"""
    try:
        if not redis_manager.is_connected():
            return
        
        redis_key = handle_to_redis_key(handle)
        task_key = f"task_{redis_key}"
        
        # Prepare data for Redis (serialize complex objects)
        redis_data = dict(task_data)
        
        # Convert complex objects to JSON strings
        if 'log_paths' in redis_data:
            redis_data['log_paths'] = json.dumps(redis_data['log_paths'])
        if 'return_code' in redis_data:
            redis_data['return_code'] = str(redis_data['return_code'])
        if 'cached' in redis_data:
            redis_data['cached'] = str(redis_data['cached']).lower()
        
        # Convert any remaining dict/list objects to JSON strings
        for key, value in redis_data.items():
            if isinstance(value, (dict, list)):
                redis_data[key] = json.dumps(value)
            elif value is None:
                redis_data[key] = ""
            elif not isinstance(value, (str, int, float, bytes)):
                redis_data[key] = str(value)
        
        # Store as hash with TTL
        redis_manager.client.hset(task_key, mapping=redis_data)
        redis_manager.client.expire(task_key, ttl)
        
    except Exception as e:
        print(f"Error storing task in Redis: {e}")




def parse_redis_key(redis_key: str) -> tuple[str, str, str]:
    """Parse Redis key to extract sha, patch_md5, and derive project info"""
    # Redis key format: patch_{sha}_{patch_md5}.log
    if not redis_key.startswith("patch_") or not redis_key.endswith(".log"):
        raise ValueError(f"Invalid Redis key format: {redis_key}")
    
    # Extract sha and patch_md5
    key_parts = redis_key[6:-4]  # Remove "patch_" prefix and ".log" suffix
    parts = key_parts.split("_")
    if len(parts) < 2:
        raise ValueError(f"Cannot parse Redis key: {redis_key}")
    
    sha = parts[0]
    patch_md5 = "_".join(parts[1:])  # In case MD5 contains underscores
    
    # Look up project from META_DICT using sha
    if sha not in META_DICT:
        raise ValueError(f"Cannot find project for sha: {sha}")
    
    project = META_DICT[sha]["project"]
    
    return project, sha, patch_md5

def get_log_file_paths(project: str, sha: str, patch_md5: str) -> dict:
    """Get log file paths for a given project, sha, and patch_md5"""
    OUT_ROOT = Path(os.getenv("ROOT_DIR", "/out/"))
    log_dir = OUT_ROOT / project / "logs"
    
    return {
        "log": str(log_dir / f"patch_{sha}_{patch_md5}.log"),
        "msg": str(log_dir / f"patch_{sha}_{patch_md5}.msg"), 
        "status": str(log_dir / f"patch_{sha}_{patch_md5}.status")
    }

def read_result_from_files(project: str, sha: str, patch_md5: str) -> Optional[dict]:
    """Read result data from log files when Redis is unavailable"""
    try:
        log_paths = get_log_file_paths(project, sha, patch_md5)
        
        # Check if at least the main log file exists
        if not os.path.exists(log_paths["log"]):
            return None
        
        # Read log files using the same logic as prepare_result_data
        fix_log = read_file_limited(log_paths["log"])
        fix_msg = read_file_limited(log_paths["msg"])
        fix_status = read_file_limited(log_paths["status"])
        
        # Try to determine return code from status file or log content
        return_code = -1
        if os.path.exists(log_paths["status"]):
            try:
                with open(log_paths["status"], "r") as f:
                    status_content = f.read().strip()
                    if status_content.isdigit():
                        return_code = int(status_content)
            except:
                pass
        
        # Determine status based on return code
        status = "completed" if return_code == 0 else "failed"
        
        # Get file modification time as timestamp
        timestamp = str(os.path.getmtime(log_paths["log"]))
        
        return {
            "status": status,
            "return_code": return_code,
            "fix_log": fix_log,
            "fix_msg": fix_msg,
            "fix_status": fix_status,
            "error": f"Exit code {return_code}" if return_code != 0 else "",
            "timestamp": timestamp,
            "from_cache": False,
            "from_files": True
        }
        
    except Exception as e:
        print(f"Error reading result from files: {e}")
        return None

def get_task_from_redis(handle: str) -> Optional[dict]:
    """Get task data from Redis using handle, fallback to files if Redis unavailable"""
    try:
        redis_key = handle_to_redis_key(handle)
        
        # Try Redis first if connected
        if redis_manager.is_connected():
            task_key = f"task_{redis_key}"
            task_data = redis_manager.client.hgetall(task_key)
            if task_data:
                # Convert string values back to appropriate types
                task_data = dict(task_data)
                
                # Convert back to appropriate types
                if 'return_code' in task_data and task_data['return_code']:
                    try:
                        task_data['return_code'] = int(task_data['return_code'])
                    except ValueError:
                        pass
                        
                if 'log_paths' in task_data and task_data['log_paths']:
                    try:
                        task_data['log_paths'] = json.loads(task_data['log_paths'])
                    except json.JSONDecodeError:
                        pass
                        
                if 'cached' in task_data:
                    task_data['cached'] = task_data['cached'].lower() == 'true'
                
                # Handle any other JSON-serialized fields
                for key, value in task_data.items():
                    if isinstance(value, str) and (value.startswith('{') or value.startswith('[')):
                        try:
                            task_data[key] = json.loads(value)
                        except json.JSONDecodeError:
                            # Keep as string if not valid JSON
                            pass
                            
                return task_data
        
        # Fallback to reading from files if Redis is unavailable or task not found
        try:
            project, sha, patch_md5 = parse_redis_key(redis_key)
            file_result = read_result_from_files(project, sha, patch_md5)
            print ("hit from local disk ", file_result, project, sha, patch_md5 )
            
            if file_result:
                # Convert to task format
                log_paths = get_log_file_paths(project, sha, patch_md5)
                bug_id = f"{project}@{sha}"
                
                return {
                    "bug_id": bug_id,
                    "sha": sha,
                    "status": file_result["status"],
                    "return_code": file_result["return_code"],
                    "fix_log": file_result["fix_log"],
                    "fix_msg": file_result["fix_msg"],
                    "fix_status": file_result["fix_status"],
                    "error": file_result["error"],
                    "timestamp": file_result["timestamp"],
                    "log_paths": log_paths,
                    "result": {"log_file": log_paths["log"], "return_code": file_result["return_code"]},
                    "patch": f"unknown_patch_{patch_md5}",  # We can't recover the original patch path
                    "redis_key": redis_key,
                    "cached": False,
                    "from_files": True
                }
                
        except Exception as e:
            print(f"Error reading from files for handle {handle}: {e}")
            
    except Exception as e:
        print(f"Error reading task from Redis: {e}")
    
    return None

def get_cached_result(redis_key: str) -> Optional[dict]:
    """Get cached result from Redis, fallback to files if Redis unavailable"""
    try:
        # Try Redis first if connected
        if redis_manager.is_connected():
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
        
        # Fallback to reading from files if Redis is unavailable or data not cached
        try:
            project, sha, patch_md5 = parse_redis_key(redis_key)
            file_result = read_result_from_files(project, sha, patch_md5)
            
            if file_result:
                return {
                    "status": file_result["status"],
                    "return_code": file_result["return_code"],
                    "fix_log": file_result["fix_log"],
                    "fix_msg": file_result["fix_msg"],
                    "fix_status": file_result["fix_status"],
                    "error": file_result["error"],
                    "timestamp": file_result["timestamp"],
                    "from_cache": False,
                    "from_files": True
                }
                
        except Exception as e:
            print(f"Error reading from files for redis_key {redis_key}: {e}")
            
    except Exception as e:
        print(f"Error reading from Redis: {e}")
    
    return None





def get_cached_result(redis_key: str) -> Optional[dict]:
    """Get cached result from Redis, fallback to files if Redis unavailable"""
    try:
        # Try Redis first if connected
        if redis_manager.is_connected():
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
        
        # Fallback to reading from files if Redis is unavailable or data not cached
        try:
            project, sha, patch_md5 = parse_redis_key(redis_key)
            file_result = read_result_from_files(project, sha, patch_md5)
            
            if file_result:
                return {
                    "status": file_result["status"],
                    "return_code": file_result["return_code"],
                    "fix_log": file_result["fix_log"],
                    "fix_msg": file_result["fix_msg"],
                    "fix_status": file_result["fix_status"],
                    "error": file_result["error"],
                    "timestamp": file_result["timestamp"],
                    "from_cache": False,
                    "from_files": True
                }
                
        except Exception as e:
            print(f"Error reading from files for redis_key {redis_key}: {e}")
            
    except Exception as e:
        print(f"Error reading from Redis: {e}")
    
    return None


def cache_result(redis_key: str, result_data: dict, ttl: int = 86400):
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
        # redis_manager.client.expire(redis_key, ttl)
        
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
        # Update task status to running in Redis
        task_data = {
            "bug_id": f"{instance.project}@{instance.sha}",
            "sha": instance.sha,
            "status": "running",
            "patch": patch,
            "redis_key": redis_key,
            "cached": False
        }
        store_task_in_redis(handle, task_data)
        
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
            
            cached_task_data = {
                "bug_id": f"{instance.project}@{instance.sha}",
                "sha": instance.sha,
                "status": cached_result["status"],
                "return_code": cached_result["return_code"],
                "fix_log": cached_result["fix_log"],
                "fix_msg": cached_result["fix_msg"],
                "fix_status": cached_result["fix_status"],
                "error": cached_result.get("error", ""),
                "timestamp": cached_result.get("timestamp", ""),
                "log_paths": log_paths,
                "result": {"log_file": log_path, "return_code": cached_result["return_code"]},
                "patch": patch,
                "redis_key": redis_key,
                "cached": True
            }
            store_task_in_redis(handle, cached_task_data)
            return

        # Extract patch MD5 for file naming (needed for log path construction)
        patch_md5 = extract_patch_md5(patch)
        
        # Define log file paths
        log_paths = {
            "log": os.path.join(instance.wrk_log, f"patch_{instance.sha}_{patch_md5}.log"),
            "msg": os.path.join(instance.wrk_log, f"patch_{instance.sha}_{patch_md5}.msg"),
            "status": os.path.join(instance.wrk_log, f"patch_{instance.sha}_{patch_md5}.status")
        }
        
        # Check if log files already exist (skip execution if they do)
        if os.path.exists(log_paths["log"]):
            print(f"Log files already exist for {patch_md5}, skipping execution")
            
            # Read existing results from files
            try:
                # Try to get return code from status file
                rc = -1
                if os.path.exists(log_paths["status"]):
                    try:
                        with open(log_paths["status"], "r") as f:
                            status_content = f.read().strip()
                            if status_content.isdigit():
                                rc = int(status_content)
                    except:
                        pass
                
                # Prepare structured result data from existing files
                error_msg = f"run_patch.sh exited {rc}" if rc != 0 else ""
                result_data = prepare_result_data(instance, patch_md5, rc, error_msg)
                
                # Update task with structured data in Redis
                final_task_data = {
                    "bug_id": f"{instance.project}@{instance.sha}",
                    "sha": instance.sha,
                    "status": result_data["status"],
                    "return_code": result_data["return_code"],
                    "fix_log": result_data["fix_log"],
                    "fix_msg": result_data["fix_msg"],
                    "fix_status": result_data["fix_status"],
                    "error": result_data["error"],
                    "timestamp": result_data["timestamp"],
                    "log_paths": result_data["log_paths"],
                    "result": {"log_file": log_path, "return_code": rc},
                    "patch": patch,
                    "redis_key": redis_key,
                    "cached": False
                }
                store_task_in_redis(handle, final_task_data)
                
                # Cache the result (single Redis save)
                cache_result(redis_key, result_data)
                return
                
            except Exception as e:
                print(f"Error reading existing log files: {e}")
                # If we can't read existing files, continue with normal execution
        
        try:
            rc = await asyncio.to_thread(_run_fix, instance, patch, log_path)
            
            # Prepare structured result data (single source of truth)
            error_msg = f"run_patch.sh exited {rc}" if rc != 0 else ""
            result_data = prepare_result_data(instance, patch_md5, rc, error_msg)
            
            # Update task with structured data in Redis
            final_task_data = {
                "bug_id": f"{instance.project}@{instance.sha}",
                "sha": instance.sha,
                "status": result_data["status"],
                "return_code": result_data["return_code"],
                "fix_log": result_data["fix_log"],
                "fix_msg": result_data["fix_msg"],
                "fix_status": result_data["fix_status"],
                "error": result_data["error"],
                "timestamp": result_data["timestamp"],
                "log_paths": result_data["log_paths"],
                "result": {"log_file": log_path, "return_code": rc},
                "patch": patch,
                "redis_key": redis_key,
                "cached": False
            }
            store_task_in_redis(handle, final_task_data)
            
            # Cache the result (single Redis save)
            cache_result(redis_key, result_data)
            
        except Exception:
            error_msg = traceback.format_exc()
            error_task_data = {
                "bug_id": f"{instance.project}@{instance.sha}",
                "sha": instance.sha,
                "status": "failed",
                "error": error_msg,
                "patch": patch,
                "redis_key": redis_key,
                "cached": False
            }
            store_task_in_redis(handle, error_task_data)
            
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
# @app.get("/projects")
# def list_projects():
#     return {"projects": list(PROJECTS_DIR)}
#
# @app.post("/reproduce")
# def reproduce(req: ReproduceRequest, background_tasks: BackgroundTasks):
#     try:
#         project, sha = parse_bug_id(req.bug_id)
#         instance = BugsInfo(project, sha)
#     except Exception:
#         raise HTTPException(status_code=400, detail=traceback.format_exc())
#     handle = uuid.uuid4().hex
#     log_file = os.path.join(instance.wrk_log, f"{sha}_reproduce_{handle}.log")
#     tasks[handle] = {
#         "bug_id": req.bug_id,
#         "sha": sha,
#         "status": "queued",
#         "log_file": log_file,
#         "force_cleanup": req.is_force_cleanup,
#     }
#     background_tasks.add_task(run_reproduce_queue, instance, log_file, handle, req.is_force_cleanup)
#     return {"handle": handle}

@app.post("/fix2")
def fix(req: FixRequest, background_tasks: BackgroundTasks):
    try:
        project, sha = parse_bug_id(req.bug_id)
        instance = BugsInfo(project, sha)
    except Exception:
        raise HTTPException(status_code=400, detail=traceback.format_exc())

    # Build Redis key and convert to base64 handle
    redis_key = build_redis_key(req.bug_id, req.patch_path)
    handle = redis_key_to_handle(redis_key)
    patch_md5 = extract_patch_md5(req.patch_path)
    
    # Define log file paths
    log_file = os.path.join(instance.wrk_log, f"patch_{sha}_{patch_md5}.log")
    msg_file = os.path.join(instance.wrk_log, f"patch_{sha}_{patch_md5}.msg")
    status_file = os.path.join(instance.wrk_log, f"patch_{sha}_{patch_md5}.status")
    
    log_paths = {"log": log_file, "msg": msg_file, "status": status_file}

    # Check cache first
    cached_result = get_cached_result(redis_key)
    if cached_result:
        # Store cached result in Redis with consistent structure
        cached_task_data = {
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
        store_task_in_redis(handle, cached_task_data)
        return {"handle": handle, "redis_key": redis_key}
    
    # Not cached, create new task and queue for processing
    initial_task_data = {
        "bug_id": req.bug_id,
        "sha": sha,
        "status": "queued",
        "log_paths": log_paths,
        "patch": req.patch_path,
        "redis_key": redis_key,
        "cached": False
    }
    store_task_in_redis(handle, initial_task_data)
    
    background_tasks.add_task(run_fix_queue, instance, req.patch_path, log_file, handle, redis_key)
    return {"handle": handle, "redis_key": redis_key}

# @app.get("/status/{handle}")
# def get_status(handle: str):
#     # For /reproduce compatibility, check in-memory tasks first
#     if handle in tasks:
#         return tasks[handle].copy()
#
#     # For /fix operations, get from Redis
#     task_data = get_task_from_redis(handle)
#     if task_data is None:
#         raise HTTPException(status_code=404, detail="Handle not found")
#
#     return task_data
#
# @app.get("/cache/status")
# def get_cache_status():
#     """Get Redis connection status"""
#     return {
#         "redis_connected": redis_manager.is_connected(),
#         "redis_info": redis_manager.client.info() if redis_manager.is_connected() else None
#     }
#
# @app.delete("/cache/{redis_key}")
# def clear_cache_entry(redis_key: str):
#     """Clear specific cache entry"""
#     try:
#         if redis_manager.is_connected():
#             result = redis_manager.client.delete(redis_key)
#             return {"deleted": bool(result), "key": redis_key}
#         else:
#             raise HTTPException(status_code=503, detail="Redis not connected")
#     except Exception as e:
#         raise HTTPException(status_code=500, detail=str(e))
#
# @app.get("/all_tasks")
# def get_all_tasks():
#     """Get all tasks - includes both in-memory (reproduce) and Redis-based (fix) tasks"""
#     all_tasks = {}
#
#     # Add in-memory tasks (reproduce operations)
#     all_tasks.update(tasks)
#
#     # Add Redis-based tasks (fix operations)
#     try:
#         if redis_manager.is_connected():
#             # Get all task keys from Redis
#             task_keys = redis_manager.client.keys("task_*")
#             for task_key in task_keys:
#                 # Extract the original redis key from task key
#                 redis_key = task_key.replace("task_", "")
#                 handle = redis_key_to_handle(redis_key)
#
#                 # Get task data
#                 task_data = get_task_from_redis(handle)
#                 if task_data:
#                     all_tasks[handle] = task_data
#     except Exception as e:
#         print(f"Error fetching Redis tasks: {e}")
#
#     return all_tasks




# ───────────────────── startup: load all data ─────────────
HERE = Path("/src/data")  # PathPath(__file__).resolve()#.parent
META_DICT = {}
def load_metadata(paths: List[str]) -> int:
    count = 0
    for p in paths:
        with open(p) as f:
            lines = json.load(f)
            project = os.path.basename( os.path.dirname(p))
            data = {x["commit_after"]: {**x,"project":project} for x in lines}
            META_DICT.update(data)
            count += len(data)
    return count

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
    print(f"[startup] metadata={m}" )#, guidance={g}, src_content={s}, prompt_len={p}, prefix={prefix} ")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
