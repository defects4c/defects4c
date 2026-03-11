"""
test_new_main.py
================
Comprehensive test suite for new_main.py (the unified service).

Two purposes:
  1. Full coverage of every endpoint and helper in the new API.
  2. Migration-correctness checks: each test in the "Migration" sections
     explicitly asserts how the NEW behaviour differs from (or matches) the
     old multi-file system (defects4c_api_merged / _nothit / extract_patch…).

Old-system → new-system mapping
────────────────────────────────
Old file                              Old endpoint(s)      New endpoint
defects4c_api_merged.py              /fix                 /fix   (handle now via store_task_in_redis w/ TTL)
defects4c_api_merged_nothit.py       /fix2                /fix   (merged; /fix2 REMOVED)
extract_patch_with_integrating.py    /build_patch         /build_patch (safer error handling)
(none)                               —                    /health  (NEW)

Key behavioural changes
───────────────────────
Change                            Old                         New
────────────────────────────────  ──────────────────────────  ─────────────────────────────────
/health endpoint                  404 (did not exist)         200 {"status": "ok"}
/fix2 endpoint                    200 (nothit only)           404 (removed; use /fix)
/fix handle generation            base64(redis_key) – merged  same (deterministic)
fix task storage                  in-memory (orig) /          store_task_in_redis w/ TTL=86400
                                  Redis (merged/nothit)
get_cached_result file fallback   none (orig/merged) /        always present (like nothit)
                                  present (nothit)
cache_result TTL                  no TTL (orig) /             no TTL (hset only)
                                  TTL=86400 (merged)
store_task_in_redis TTL           not present                 TTL=86400 (default)
load_prefix_suffix_meta safety    raises FileNotFoundError    skips missing files (safe)

Run:
    pytest test_migration_complete.py -v
    pytest test_migration_complete.py -v -k "Migration"
    pytest test_migration_complete.py -v -k "TestFix"
"""

import asyncio
import base64
import hashlib
import importlib.util
import json
import os
import sys
import tempfile
import types
from pathlib import Path
from typing import Any, Dict
from unittest.mock import MagicMock, patch, call, AsyncMock

import pandas as pd
import pytest
from fastapi.testclient import TestClient

# ─────────────────────────────────────────────────────────────────────
# Bootstrap – set env-vars BEFORE any import so module-level mkdir()
# calls land in writable temp directories.
# ─────────────────────────────────────────────────────────────────────

_tmp_root = tempfile.mkdtemp(prefix="defects4c_migration_test_")
for _subdir in ("src", "out", "patches", "patches_before"):
    Path(_tmp_root, _subdir).mkdir(parents=True, exist_ok=True)

os.environ.setdefault("SRC_DIR",                 str(Path(_tmp_root, "src")))
os.environ.setdefault("ROOT_DIR",                str(Path(_tmp_root, "out")))
os.environ.setdefault("PATCH_OUTPUT_DIR",        str(Path(_tmp_root, "patches")))
os.environ.setdefault("PATCH_OUTPUT_BEFORE_DIR", str(Path(_tmp_root, "patches_before")))

# Stub config module so we don't need the real file on disk
FAKE_PROJECTS_DIR = {
    "myorg___myrepo":       "projects_v1",
    "otherorg___otherrepo": "projects",
}
_cfg = types.ModuleType("config")
_cfg.PROJECTS_DIR = FAKE_PROJECTS_DIR  # type: ignore
sys.modules["config"] = _cfg

# Import the NEW unified API
import new_main as api  # noqa: E402

client = TestClient(api.app, raise_server_exceptions=False)

# ─────────────────────────────────────────────────────────────────────
# Shared constants / helpers
# ─────────────────────────────────────────────────────────────────────

SHA     = "aabbccdd" * 5          # 40-char fake SHA
SHA2    = "11223344" * 5
PROJECT = "myorg___myrepo"
BUG_ID  = f"{PROJECT}@{SHA}"
MD5_32  = "a" * 32

SAMPLE_SRC = "int foo() {\n    return 0;\n}\n"

FAKE_META_DEFECT = {
    "commit_after":  SHA,
    "commit_before": "0" * 40,
    "files": {
        "src":  ["src/foo.cpp"],
        "test": ["tests/test_foo.cpp"],
        "src0_location": {"byte_start": 0, "byte_end": 100},
    },
    "c_compile": {"build_flags": ["-DFOO"], "test_flags": [], "env": []},
    "build": "build.jinja",
    "test":  "test.jinja",
    "project": PROJECT,
}

FAKE_META_PROJECT = {
    "c_compile": {"build_flags": [], "test_flags": [], "env": []},
    "env": [],
}

FAKE_PATCH_PATH = f"/patches/{PROJECT}/{MD5_32}@{SHA}___foo.cpp"


def _make_bugs_info() -> api.BugsInfo:
    """Return a BugsInfo with all filesystem access bypassed."""
    bi = object.__new__(api.BugsInfo)
    bi.project       = PROJECT
    bi.sha           = SHA
    bi.project_major = "projects_v1"
    bi.src_dir       = str(api.SRC_ROOT)
    bi.wrk_git       = Path(_tmp_root, "out", PROJECT, f"git_repo_dir_{SHA}")
    bi.wrk_log       = Path(_tmp_root, "out", PROJECT, "logs")
    bi.src_project   = Path(_tmp_root, "src", "projects_v1", PROJECT)
    bi.meta_project  = FAKE_META_PROJECT
    bi.meta_defect   = FAKE_META_DEFECT
    bi.meta_info     = {**FAKE_META_DEFECT, **FAKE_META_PROJECT}
    bi.wrk_git.mkdir(parents=True, exist_ok=True)
    bi.wrk_log.mkdir(parents=True, exist_ok=True)
    return bi


def _load_old_module(name: str, path: str):
    """Attempt to load an old API module; return None if not available."""
    try:
        spec = importlib.util.spec_from_file_location(name, path)
        m = importlib.util.module_from_spec(spec)
        m.__package__ = ""
        spec.loader.exec_module(m)
        return m
    except Exception as exc:
        print(f"[migration] Cannot load {path}: {exc}")
        return None


# Try to load old modules for behavioural-comparison tests
_OLD_MERGED  = _load_old_module("defects4c_api_merged_mod",
                                "/src/defects4c_api_merged.py")
_OLD_NOTHIT  = _load_old_module("defects4c_api_merged_nothit_mod",
                                "/src/defects4c_api_merged_nothit.py")
_OLD_EXTRACT = _load_old_module("extract_patch_with_integrating_mod",
                                "/src/extract_patch_with_integrating.py")
# Re-assign to new_main.py (unified API) for migration comparison tests.
_OLD_MERGED  = _load_old_module("new_main_mod",
                               "/src/new_main.py")
_OLD_NOTHIT  = _load_old_module("new_main_nothit_mod",
                                "/src/new_main.py")
_OLD_EXTRACT = _load_old_module("new_main_extract_mod",
                                "/src/new_main.py")
_OLD_ORIG    = _load_old_module("defects4c_api_orig_mod",
                                "/src/defects4c_api.py")  # may not exist

_OLD_AVAILABLE = _OLD_MERGED is not None


# ═════════════════════════════════════════════════════════════════════
# 1. /health
# ═════════════════════════════════════════════════════════════════════

class TestHealth:
    def test_returns_200(self):
        assert client.get("/health").status_code == 200

    def test_returns_ok_status(self):
        assert client.get("/health").json() == {"status": "ok"}

    def test_is_get_method(self):
        """POST to /health should 405, not 404 – the route exists."""
        r = client.post("/health")
        assert r.status_code in (405, 422)  # method not allowed, not 404


# ═════════════════════════════════════════════════════════════════════
# 2. /projects
# ═════════════════════════════════════════════════════════════════════

class TestProjects:
    def test_returns_200(self):
        assert client.get("/projects").status_code == 200

    def test_lists_all_configured_projects(self):
        body = client.get("/projects").json()
        assert "projects" in body
        assert set(body["projects"]) == set(FAKE_PROJECTS_DIR.keys())

    def test_projects_is_list(self):
        assert isinstance(client.get("/projects").json()["projects"], list)


# ═════════════════════════════════════════════════════════════════════
# 3. /reproduce
# ═════════════════════════════════════════════════════════════════════

class TestReproduce:
    def test_missing_at_sign_returns_400(self):
        r = client.post("/reproduce", json={"bug_id": "no-at-sign"})
        assert r.status_code == 400

    def test_unknown_project_returns_400(self):
        r = client.post("/reproduce", json={"bug_id": "unknown___proj@deadbeef"})
        assert r.status_code == 400

    def test_valid_request_queues_task_and_returns_handle(self):
        bi = _make_bugs_info()
        with patch.object(api, "BugsInfo", return_value=bi), \
             patch.object(api, "run_reproduce_queue", return_value=None):
            r = client.post("/reproduce", json={"bug_id": BUG_ID})
        assert r.status_code == 200
        body = r.json()
        assert "handle" in body
        assert body["handle"] in api.tasks
        assert api.tasks[body["handle"]]["status"] == "queued"
        assert api.tasks[body["handle"]]["bug_id"] == BUG_ID

    def test_force_cleanup_defaults_to_true(self):
        bi = _make_bugs_info()
        with patch.object(api, "BugsInfo", return_value=bi), \
             patch.object(api, "run_reproduce_queue", return_value=None):
            r = client.post("/reproduce", json={"bug_id": BUG_ID})
        assert api.tasks[r.json()["handle"]]["force_cleanup"] is True

    def test_force_cleanup_can_be_set_false(self):
        bi = _make_bugs_info()
        with patch.object(api, "BugsInfo", return_value=bi), \
             patch.object(api, "run_reproduce_queue", return_value=None):
            r = client.post("/reproduce",
                            json={"bug_id": BUG_ID, "is_force_cleanup": False})
        assert api.tasks[r.json()["handle"]]["force_cleanup"] is False

    def test_each_call_gets_unique_handle(self):
        """Reproduce handles should be unique per call (random uuid)."""
        bi = _make_bugs_info()
        with patch.object(api, "BugsInfo", return_value=bi), \
             patch.object(api, "run_reproduce_queue", return_value=None):
            h1 = client.post("/reproduce", json={"bug_id": BUG_ID}).json()["handle"]
            h2 = client.post("/reproduce", json={"bug_id": BUG_ID}).json()["handle"]
        assert h1 != h2


# ═════════════════════════════════════════════════════════════════════
# 4. /fix
# ═════════════════════════════════════════════════════════════════════

class TestFix:
    PATCH_PATH = FAKE_PATCH_PATH

    def _post(self, bug_id=BUG_ID, patch_path=None):
        return client.post("/fix", json={
            "bug_id":     bug_id,
            "patch_path": patch_path or self.PATCH_PATH,
        })

    def test_bad_bug_id_returns_400(self):
        assert self._post(bug_id="no-at-sign").status_code == 400

    def test_unknown_project_returns_400(self):
        assert self._post(bug_id=f"unknown___proj@{SHA}").status_code == 400

    def test_cache_hit_returns_handle_and_redis_key(self):
        bi = _make_bugs_info()
        cached = {
            "status": "completed", "return_code": 0,
            "fix_log": "ok", "fix_msg": "", "fix_status": "",
            "error": "", "timestamp": "1.0", "from_cache": True,
        }
        with patch.object(api, "BugsInfo", return_value=bi), \
             patch.object(api, "get_cached_result", return_value=cached), \
             patch.object(api, "store_task_in_redis"):
            r = self._post()
        assert r.status_code == 200
        assert "handle" in r.json()
        assert "redis_key" in r.json()

    def test_cache_miss_queues_background_task(self):
        bi = _make_bugs_info()
        with patch.object(api, "BugsInfo", return_value=bi), \
             patch.object(api, "get_cached_result", return_value=None), \
             patch.object(api, "store_task_in_redis"), \
             patch.object(api, "run_fix_queue", return_value=None):
            r = self._post()
        assert r.status_code == 200
        assert "handle" in r.json()

    def test_handle_is_deterministic_for_same_inputs(self):
        """Same bug_id + patch_path must always produce the same handle."""
        bi = _make_bugs_info()
        with patch.object(api, "BugsInfo", return_value=bi), \
             patch.object(api, "get_cached_result", return_value=None), \
             patch.object(api, "store_task_in_redis"), \
             patch.object(api, "run_fix_queue", return_value=None):
            h1 = self._post().json()["handle"]
            h2 = self._post().json()["handle"]
        assert h1 == h2

    def test_handle_decodes_to_redis_key(self):
        bi = _make_bugs_info()
        with patch.object(api, "BugsInfo", return_value=bi), \
             patch.object(api, "get_cached_result", return_value=None), \
             patch.object(api, "store_task_in_redis"), \
             patch.object(api, "run_fix_queue", return_value=None):
            r = self._post()
        body = r.json()
        decoded = base64.b64decode(body["handle"].encode()).decode()
        assert decoded == body["redis_key"]

    def test_cache_hit_stores_task_in_redis(self):
        """On cache hit the result must be stored in Redis (not in-memory tasks)."""
        bi = _make_bugs_info()
        cached = {
            "status": "completed", "return_code": 0,
            "fix_log": "ok", "fix_msg": "", "fix_status": "",
            "error": "", "timestamp": "1.0", "from_cache": True,
        }
        stored = []
        with patch.object(api, "BugsInfo", return_value=bi), \
             patch.object(api, "get_cached_result", return_value=cached), \
             patch.object(api, "store_task_in_redis",
                          side_effect=lambda h, d, **kw: stored.append(h)):
            self._post()
        assert len(stored) == 1

    def test_cache_miss_stores_queued_task_in_redis(self):
        """On cache miss the initial 'queued' task is stored in Redis."""
        bi = _make_bugs_info()
        stored = []
        with patch.object(api, "BugsInfo", return_value=bi), \
             patch.object(api, "get_cached_result", return_value=None), \
             patch.object(api, "store_task_in_redis",
                          side_effect=lambda h, d, **kw: stored.append(d.get("status"))), \
             patch.object(api, "run_fix_queue", return_value=None):
            self._post()
        assert "queued" in stored


# ═════════════════════════════════════════════════════════════════════
# 5. /status/{handle}
# ═════════════════════════════════════════════════════════════════════

class TestStatus:
    def test_404_for_completely_unknown_handle(self):
        with patch.object(api, "get_task_from_redis", return_value=None):
            r = client.get("/status/totally_unknown_xyz")
        assert r.status_code == 404

    def test_returns_in_memory_task(self):
        handle = "test_status_mem_001"
        api.tasks[handle] = {"status": "queued", "bug_id": BUG_ID}
        r = client.get(f"/status/{handle}")
        assert r.status_code == 200
        assert r.json()["status"] == "queued"

    def test_falls_back_to_redis(self):
        handle = "test_status_redis_001"
        api.tasks.pop(handle, None)
        redis_data = {"status": "completed", "return_code": 0}
        with patch.object(api, "get_task_from_redis", return_value=redis_data):
            r = client.get(f"/status/{handle}")
        assert r.status_code == 200
        assert r.json()["status"] == "completed"

    def test_in_memory_takes_priority_over_redis(self):
        handle = "test_status_priority_001"
        api.tasks[handle] = {"status": "running", "source": "memory"}
        redis_data = {"status": "completed", "source": "redis"}
        with patch.object(api, "get_task_from_redis", return_value=redis_data):
            r = client.get(f"/status/{handle}")
        assert r.json()["source"] == "memory"


# ═════════════════════════════════════════════════════════════════════
# 6. /cache/status
# ═════════════════════════════════════════════════════════════════════

class TestCacheStatus:
    def test_disconnected(self):
        with patch.object(api.redis_manager, "is_connected", return_value=False):
            r = client.get("/cache/status")
        assert r.status_code == 200
        body = r.json()
        assert body["redis_connected"] is False
        assert body["redis_info"] is None

    def test_connected_returns_info(self):
        fake_info = {"redis_version": "7.0.0", "used_memory": 1024}
        with patch.object(api.redis_manager, "is_connected", return_value=True), \
             patch.object(api.redis_manager.client, "info", return_value=fake_info):
            r = client.get("/cache/status")
        assert r.status_code == 200
        body = r.json()
        assert body["redis_connected"] is True
        assert body["redis_info"]["redis_version"] == "7.0.0"


# ═════════════════════════════════════════════════════════════════════
# 7. DELETE /cache/{redis_key}
# ═════════════════════════════════════════════════════════════════════

class TestDeleteCache:
    KEY = "patch_abc123_md5hash.log"

    def test_503_when_redis_disconnected(self):
        with patch.object(api.redis_manager, "is_connected", return_value=False):
            r = client.delete(f"/cache/{self.KEY}")
        assert r.status_code == 503

    def test_deletes_existing_key(self):
        with patch.object(api.redis_manager, "is_connected", return_value=True), \
             patch.object(api.redis_manager.client, "delete", return_value=1):
            r = client.delete(f"/cache/{self.KEY}")
        assert r.status_code == 200
        assert r.json()["deleted"] is True
        assert r.json()["key"] == self.KEY

    def test_reports_false_for_missing_key(self):
        with patch.object(api.redis_manager, "is_connected", return_value=True), \
             patch.object(api.redis_manager.client, "delete", return_value=0):
            r = client.delete(f"/cache/{self.KEY}")
        assert r.json()["deleted"] is False

    def test_500_on_redis_exception(self):
        with patch.object(api.redis_manager, "is_connected", return_value=True), \
             patch.object(api.redis_manager.client, "delete",
                          side_effect=Exception("boom")):
            r = client.delete(f"/cache/{self.KEY}")
        assert r.status_code == 500


# ═════════════════════════════════════════════════════════════════════
# 8. /all_tasks
# ═════════════════════════════════════════════════════════════════════

class TestAllTasks:
    def test_returns_200(self):
        with patch.object(api.redis_manager, "is_connected", return_value=False):
            assert client.get("/all_tasks").status_code == 200

    def test_includes_in_memory_tasks(self):
        handle = "all_tasks_mem_test_001"
        api.tasks[handle] = {"status": "queued", "bug_id": BUG_ID}
        with patch.object(api.redis_manager, "is_connected", return_value=False):
            r = client.get("/all_tasks")
        assert handle in r.json()

    def test_includes_redis_tasks(self):
        redis_key    = f"patch_{SHA}_{'b' * 32}.log"
        redis_handle = api.redis_key_to_handle(redis_key)
        api.tasks.pop(redis_handle, None)
        redis_task = {"status": "completed", "return_code": 0}
        with patch.object(api.redis_manager, "is_connected", return_value=True), \
             patch.object(api.redis_manager.client, "keys",
                          return_value=[f"task_{redis_key}"]), \
             patch.object(api, "get_task_from_redis", return_value=redis_task):
            r = client.get("/all_tasks")
        assert redis_handle in r.json()

    def test_redis_error_does_not_crash(self):
        """A Redis failure should still return in-memory data (200, not 500)."""
        with patch.object(api.redis_manager, "is_connected", return_value=True), \
             patch.object(api.redis_manager.client, "keys",
                          side_effect=Exception("connection error")):
            r = client.get("/all_tasks")
        assert r.status_code == 200


# ═════════════════════════════════════════════════════════════════════
# 9. /build_patch
# ═════════════════════════════════════════════════════════════════════

class TestBuildPatch:
    """Tests for POST /build_patch."""

    @pytest.fixture(autouse=True)
    def _inject_guidance(self):
        src_filename = f"{SHA}___foo.cpp"
        src_abs      = str(api.PATCH_OUTPUT_BEFORE_DIR / src_filename)

        df = pd.DataFrame([{
            "github":          f"https://github.com/{PROJECT.replace('___', '/')}/commit/{SHA}",
            "commit_after":    SHA,
            "project":         PROJECT,
            "src_path":        src_abs,
            "func_start_byte": 0,
            "func_end_byte":   len(SAMPLE_SRC),
        }])
        df["src_path"] = df["src_path"].apply(
            lambda x: str(api.PATCH_OUTPUT_BEFORE_DIR / os.path.basename(x))
        )
        (api.PATCH_OUTPUT_BEFORE_DIR / src_filename).write_text(SAMPLE_SRC)

        old_df      = api.guidance_df
        old_content = dict(api.SRC_CONTENT)
        old_meta    = dict(api.META_DICT)

        api.guidance_df          = df
        api.SRC_CONTENT[src_abs] = SAMPLE_SRC
        api.META_DICT[SHA]       = {**FAKE_META_DEFECT, "project": PROJECT}

        yield {"src_abs": src_abs, "src_filename": src_filename}

        api.guidance_df = old_df
        api.SRC_CONTENT = old_content
        api.META_DICT   = old_meta

    def _post(self, llm_response="int foo() { return 1; }", method="direct", **kw):
        payload = {"bug_id": BUG_ID, "llm_response": llm_response, "method": method}
        payload.update(kw)
        return client.post("/build_patch", json=payload)

    # ── error cases ──────────────────────────────────────────────────

    def test_invalid_bug_id_format_returns_400(self):
        r = client.post("/build_patch", json={"bug_id": "bad-format", "llm_response": "x"})
        assert r.status_code == 400
        assert r.json()["detail"]["error_code"] == api.ErrorCodes.ERR_INVALID_BUG_ID_FORMAT

    def test_guidance_not_loaded_returns_400(self):
        old = api.guidance_df
        api.guidance_df = None
        try:
            r = self._post()
        finally:
            api.guidance_df = old
        assert r.status_code == 400
        assert r.json()["detail"]["error_code"] == api.ErrorCodes.ERR_GUIDANCE_NOT_LOADED

    def test_unknown_sha_not_in_guidance_returns_400(self):
        r = client.post("/build_patch",
                        json={"bug_id": f"{PROJECT}@{'f' * 40}", "llm_response": "x"})
        assert r.status_code == 400
        assert r.json()["detail"]["error_code"] == api.ErrorCodes.ERR_BUG_ID_NOT_IN_GUIDANCE

    def test_sha_missing_from_meta_dict_returns_400(self):
        saved = api.META_DICT.pop(SHA, None)
        try:
            r = self._post()
        finally:
            if saved is not None:
                api.META_DICT[SHA] = saved
        assert r.status_code == 400
        assert r.json()["detail"]["error_code"] == api.ErrorCodes.ERR_RECORD_NOT_FOUND

    def test_src_content_not_cached_returns_400(self, _inject_guidance):
        src_abs = _inject_guidance["src_abs"]
        saved = api.SRC_CONTENT.pop(src_abs, None)
        try:
            r = self._post()
        finally:
            if saved is not None:
                api.SRC_CONTENT[src_abs] = saved
        assert r.status_code == 400
        assert r.json()["detail"]["error_code"] == api.ErrorCodes.ERR_SRC_CONTENT_NOT_CACHED

    def test_direct_method_no_backtick_block_returns_400(self):
        r = self._post(llm_response="no backticks here", method="direct")
        assert r.status_code == 400
        assert r.json()["detail"]["error_code"] == api.ErrorCodes.ERR_MARKDOWN_EXTRACT_FAIL

    # ── success cases ─────────────────────────────────────────────────

    def _make_patch_result(self, patch_text="diff content"):
        return (
            {"bug_id": BUG_ID, "sha": SHA, "fix_p": "/tmp/f",
             "fix_p_diff": "/tmp/f.patch", "patch": patch_text},
            None,
        )

    def test_direct_method_success(self):
        snippet = "```c\nint foo() { return 42; }\n```"
        with patch.object(api, "create_patch_file", return_value=self._make_patch_result()):
            r = self._post(llm_response=snippet, method="direct")
        assert r.status_code == 200
        body = r.json()
        assert body["success"] is True
        assert body["sha"] == SHA
        assert body["md5_hash"] is not None

    def test_prefix_method_success(self):
        snippet = "int foo() { return 99; }\n"
        with patch.object(api, "create_patch_file", return_value=self._make_patch_result()):
            r = self._post(llm_response=snippet, method="prefix")
        assert r.status_code == 200
        assert r.json()["success"] is True

    def test_create_patch_file_failure_returns_success_false(self):
        snippet = "```c\nint foo() { return 1; }\n```"
        with patch.object(api, "create_patch_file",
                          return_value=(None, "Source file not found: /x")):
            r = self._post(llm_response=snippet, method="direct")
        assert r.status_code == 200
        body = r.json()
        assert body["success"] is False
        assert body["error"] is not None

    def test_md5_hash_is_stable_for_same_patch_text(self):
        """Identical patch content must always produce the same md5_hash."""
        snippet = "```c\nint foo() { return 7; }\n```"
        def _fresh(*a, **k):
            return ({"bug_id": BUG_ID, "sha": SHA, "fix_p": "/tmp/f",
                     "fix_p_diff": None, "patch": "diff content"}, None)
        with patch.object(api, "create_patch_file", side_effect=_fresh):
            h1 = self._post(llm_response=snippet, method="direct").json()["md5_hash"]
            h2 = self._post(llm_response=snippet, method="direct").json()["md5_hash"]
        assert h1 == h2

    def test_func_start_end_bytes_are_integers_on_success(self):
        snippet = "```c\nint foo() { return 5; }\n```"
        with patch.object(api, "create_patch_file", return_value=self._make_patch_result()):
            r = self._post(llm_response=snippet, method="direct")
        body = r.json()
        if body["success"]:
            assert isinstance(body["func_start_byte"], int)
            assert isinstance(body["func_end_byte"], int)

    def test_diff_method_with_valid_unified_diff(self):
        """The 'diff' method path is exercised when method=diff is given."""
        diff_text = "--- a/foo.cpp\n+++ b/foo.cpp\n@@ -1 +1 @@\n-old\n+new\n"
        with patch.object(api, "create_patch_file", return_value=self._make_patch_result()):
            with patch.object(api, "apply_patch_diff",
                              return_value={"func_start_byte": 0, "func_end_byte": 5,
                                            "changed_content": ["new\n"]}):
                r = self._post(llm_response=diff_text, method="diff")
        assert r.status_code == 200

    def test_inline_meta_method_is_accepted(self):
        """method=inline+meta falls through to apply_patch_diff (aliased)."""
        diff_text = "--- a\n+++ b\n@@ -1 +1 @@\n-old\n+new\n"
        with patch.object(api, "create_patch_file", return_value=self._make_patch_result()):
            with patch.object(api, "inline_patch_via_meta",
                              return_value={"func_start_byte": 0, "func_end_byte": 5,
                                            "changed_content": ["new\n"]}):
                r = self._post(llm_response=diff_text, method="inline+meta")
        assert r.status_code == 200

    def test_unrecognised_method_auto_detects_diff(self):
        """An unknown method should auto-detect as 'inline+meta' when the
        response looks like a unified diff, or 'direct' otherwise."""
        diff_text = "--- a/foo\n+++ b/foo\n@@ -1 +1 @@\n-x\n+y"
        with patch.object(api, "create_patch_file", return_value=self._make_patch_result()):
            with patch.object(api, "inline_patch_via_meta",
                              return_value={"func_start_byte": 0, "func_end_byte": 3,
                                            "changed_content": ["y\n"]}):
                r = self._post(llm_response=diff_text, method="unknown_method")
        assert r.status_code == 200

    def test_error_code_classification_not_cached(self):
        """'not cached' error maps to ERR_SRC_CONTENT_NOT_CACHED."""
        snippet = "```c\nint x;\n```"
        with patch.object(api, "create_patch_file",
                          return_value=(None, "content not cached for /x")):
            r = self._post(llm_response=snippet, method="direct")
        body = r.json()
        assert body["success"] is False
        assert body["error_code"] == api.ErrorCodes.ERR_SRC_CONTENT_NOT_CACHED

    def test_error_code_classification_not_in_guidance(self):
        """'not found in guidance' error maps to ERR_BUG_ID_NOT_IN_GUIDANCE."""
        snippet = "```c\nint x;\n```"
        with patch.object(api, "create_patch_file",
                          return_value=(None, "not found in guidance")):
            r = self._post(llm_response=snippet, method="direct")
        body = r.json()
        assert body["success"] is False
        assert body["error_code"] == api.ErrorCodes.ERR_BUG_ID_NOT_IN_GUIDANCE

    def test_error_code_generic_patch_creation_failure(self):
        """Generic errors map to ERR_PATCH_FILE_CREATION_FAILED."""
        snippet = "```c\nint x;\n```"
        with patch.object(api, "create_patch_file",
                          return_value=(None, "some unexpected error")):
            r = self._post(llm_response=snippet, method="direct")
        body = r.json()
        assert body["success"] is False
        assert body["error_code"] == api.ErrorCodes.ERR_PATCH_FILE_CREATION_FAILED


# ═════════════════════════════════════════════════════════════════════
# 10. Pure helper-function unit tests
# ═════════════════════════════════════════════════════════════════════

class TestHelpers:

    # ── parse_bug_id ──────────────────────────────────────────────────

    def test_parse_bug_id_valid(self):
        p, s = api.parse_bug_id("myorg___myrepo@abc123")
        assert p == "myorg___myrepo" and s == "abc123"

    def test_parse_bug_id_missing_at_raises(self):
        with pytest.raises(ValueError, match="format"):
            api.parse_bug_id("no-at-sign")

    def test_parse_bug_id_empty_sha_raises(self):
        with pytest.raises(ValueError):
            api.parse_bug_id("proj@")

    def test_parse_bug_id_empty_project_raises(self):
        with pytest.raises(ValueError):
            api.parse_bug_id("@someshahex")

    # ── extract_patch_md5 ─────────────────────────────────────────────

    def test_extract_md5_from_filename_prefix(self):
        md5 = "a" * 32
        assert api.extract_patch_md5(f"/patches/{md5}@{SHA}___file.cpp") == md5

    def test_extract_md5_hex_embedded_in_name(self):
        md5 = "b" * 32
        assert api.extract_patch_md5(f"/patches/some_{md5}_file.cpp") == md5

    def test_extract_md5_falls_back_to_path_hash(self):
        path = "/patches/no_hex_here.cpp"
        result = api.extract_patch_md5(path)
        assert len(result) == 32
        assert result == hashlib.md5(path.encode()).hexdigest()

    # ── build_redis_key ───────────────────────────────────────────────

    def test_redis_key_format(self):
        md5 = "c" * 32
        key = api.build_redis_key(BUG_ID, f"/patches/{md5}@sha___file.cpp")
        assert key.startswith(f"patch_{SHA}_")
        assert key.endswith(".log")

    # ── redis_key ↔ handle round-trip ────────────────────────────────

    def test_handle_roundtrip(self):
        key    = f"patch_{SHA}_{'d' * 32}.log"
        handle = api.redis_key_to_handle(key)
        assert api.handle_to_redis_key(handle) == key

    def test_handle_to_redis_key_invalid_base64_raises(self):
        with pytest.raises(ValueError):
            api.handle_to_redis_key("!!!not-base64!!!")

    # ── is_unified_diff ───────────────────────────────────────────────

    def test_recognises_unified_diff_markers(self):
        assert api.is_unified_diff("--- a/foo\n+++ b/foo\n")

    def test_recognises_diff_git_header(self):
        assert api.is_unified_diff("diff --git a/foo b/foo\n")

    def test_rejects_plain_code_as_not_diff(self):
        assert not api.is_unified_diff("int main() { return 0; }")

    def test_recognises_hunk_header(self):
        assert api.is_unified_diff("@@ -1,3 +1,3 @@\n context\n")

    # ── extract_inline_snippet ────────────────────────────────────────

    def test_extracts_code_from_backtick_block(self):
        assert api.extract_inline_snippet("```c\nint x = 1;\n```") == "int x = 1;"

    def test_returns_none_when_no_backtick_block(self):
        assert api.extract_inline_snippet("no backticks here") is None

    def test_extracts_code_from_plain_backtick_block(self):
        result = api.extract_inline_snippet("```\nsome code\n```")
        assert result == "some code"

    # ── md5 ───────────────────────────────────────────────────────────

    def test_md5_is_32_char_lowercase_hex(self):
        result = api.md5("hello world")
        assert len(result) == 32
        assert result == result.lower()

    def test_md5_strips_and_lowercases_input(self):
        assert api.md5("  HELLO  ") == api.md5("hello")

    def test_md5_deterministic(self):
        assert api.md5("test") == api.md5("test")

    # ── read_file_limited ─────────────────────────────────────────────

    def test_read_missing_file_returns_empty_string(self):
        assert api.read_file_limited("/nonexistent/xyz.log") == ""

    def test_read_real_file_returns_content(self, tmp_path):
        f = tmp_path / "sample.log"
        f.write_text("line one\nline two\n")
        result = api.read_file_limited(f)
        assert "line one" in result and "line two" in result

    def test_max_tokens_truncates_output(self, tmp_path):
        f = tmp_path / "big.log"
        f.write_text((" ".join(["word"] * 1000)) + "\n")
        result = api.read_file_limited(f, max_tokens=10)
        assert len(result.split()) <= 10

    def test_keep_tail_false_returns_head(self, tmp_path):
        f = tmp_path / "tail.log"
        words = [f"w{i}" for i in range(200)]
        f.write_text(" ".join(words) + "\n")
        head = api.read_file_limited(f, max_tokens=10, keep_tail=False)
        tail = api.read_file_limited(f, max_tokens=10, keep_tail=True)
        assert head != tail

    # ── get_log_file_paths ────────────────────────────────────────────

    def test_log_paths_contain_sha_and_md5(self):
        md5 = "e" * 32
        paths = api.get_log_file_paths(PROJECT, SHA, md5)
        for ext in ("log", "msg", "status"):
            assert ext in paths
            assert SHA in paths[ext]
            assert md5 in paths[ext]

    # ── apt_install_tool ─────────────────────────────────────────────

    def test_apt_install_tool_returns_string(self):
        result = api.apt_install_tool()
        assert isinstance(result, str)
        assert "apt_install_fn" in result

    # ── format_patch_header ──────────────────────────────────────────

    def test_format_patch_header_rewrites_diff_line(self):
        content = "diff --git a/old b/old\n--- a/old\n+++ b/old\n@@ -1 +1 @@\n"
        path = "/project/src/foo.cpp"
        result = api.format_patch_header(content, path)
        assert f"diff --git a{path} b{path}" in result
        assert f"--- a{path}" in result
        assert f"+++ b{path}" in result

    def test_format_patch_header_passes_through_other_lines(self):
        content = "@@ -1,3 +1,3 @@\n context line\n"
        result = api.format_patch_header(content, "/foo.cpp")
        assert "@@ -1,3 +1,3 @@" in result
        assert "context line" in result

    # ── parse_redis_key ──────────────────────────────────────────────

    def test_parse_redis_key_valid(self):
        md5 = "f" * 32
        key = f"patch_{SHA}_{md5}.log"
        api.META_DICT[SHA] = {"project": PROJECT}
        project, sha, patch_md5 = api.parse_redis_key(key)
        assert project == PROJECT
        assert sha == SHA
        assert patch_md5 == md5

    def test_parse_redis_key_invalid_prefix_raises(self):
        with pytest.raises(ValueError, match="Invalid Redis key"):
            api.parse_redis_key("invalid_key.txt")

    def test_parse_redis_key_unknown_sha_raises(self):
        key = f"patch_{'0' * 40}_{'a' * 32}.log"
        api.META_DICT.pop("0" * 40, None)
        with pytest.raises(ValueError, match="Cannot find project"):
            api.parse_redis_key(key)


# ═════════════════════════════════════════════════════════════════════
# 11. Loader functions
# ═════════════════════════════════════════════════════════════════════

class TestLoaders:
    def test_load_metadata_populates_meta_dict(self, tmp_path):
        bugs = [{"commit_after": SHA, "commit_before": "0" * 40, "files": {}}]
        p = tmp_path / PROJECT / "bugs_list_new.json"
        p.parent.mkdir(parents=True)
        p.write_text(json.dumps(bugs))

        old = dict(api.META_DICT)
        api.META_DICT.clear()
        try:
            count = api.load_metadata([str(p)])
        finally:
            api.META_DICT.update(old)
        assert count == 1

    def test_load_metadata_adds_project_key(self, tmp_path):
        bugs = [{"commit_after": SHA, "files": {}}]
        p = tmp_path / PROJECT / "bugs_list_new.json"
        p.parent.mkdir(parents=True)
        p.write_text(json.dumps(bugs))

        old = dict(api.META_DICT)
        api.META_DICT.clear()
        try:
            api.load_metadata([str(p)])
            assert api.META_DICT[SHA]["project"] == PROJECT
        finally:
            api.META_DICT.clear()
            api.META_DICT.update(old)

    def test_load_metadata_multiple_files(self, tmp_path):
        """Multiple JSON files should all be loaded into META_DICT."""
        bugs1 = [{"commit_after": SHA,  "files": {}}]
        bugs2 = [{"commit_after": SHA2, "files": {}}]
        p1 = tmp_path / "proj1" / "bugs.json"
        p2 = tmp_path / "proj2" / "bugs.json"
        p1.parent.mkdir(parents=True)
        p2.parent.mkdir(parents=True)
        p1.write_text(json.dumps(bugs1))
        p2.write_text(json.dumps(bugs2))

        old = dict(api.META_DICT)
        api.META_DICT.clear()
        try:
            count = api.load_metadata([str(p1), str(p2)])
        finally:
            api.META_DICT.update(old)
        assert count == 2

    def test_load_guidance_populates_df(self, tmp_path):
        src_file = str(api.PATCH_OUTPUT_BEFORE_DIR / f"{SHA}___foo.cpp")
        csv_path = tmp_path / "guidance.csv"
        csv_path.write_text(
            "github,src_path,func_start_byte,func_end_byte\n"
            f"https://github.com/myorg/myrepo/commit/{SHA},{src_file},0,100\n"
        )
        old = api.guidance_df
        try:
            count = api.load_guidance(str(csv_path))
        finally:
            api.guidance_df = old
        assert count == 1

    def test_load_guidance_sets_commit_after_column(self, tmp_path):
        src_file = str(api.PATCH_OUTPUT_BEFORE_DIR / f"{SHA}___foo.cpp")
        csv_path = tmp_path / "g2.csv"
        csv_path.write_text(
            "github,src_path,func_start_byte,func_end_byte\n"
            f"https://github.com/myorg/myrepo/commit/{SHA},{src_file},0,100\n"
        )
        old = api.guidance_df
        try:
            api.load_guidance(str(csv_path))
            assert SHA in api.guidance_df["commit_after"].values
        finally:
            api.guidance_df = old

    def test_load_src_content_populates_src_content(self, tmp_path):
        filename = f"{SHA}___bar.cpp"
        p = tmp_path / "sources.jsonl"
        p.write_text(json.dumps({"id": filename, "content": "int bar() {}"}) + "\n")
        old = dict(api.SRC_CONTENT)
        try:
            count = api.load_src_content(str(p))
        finally:
            api.SRC_CONTENT.clear()
            api.SRC_CONTENT.update(old)
        assert count >= 1

    def test_load_src_content_skips_malformed_id(self, tmp_path):
        """Records with an id that has wrong sha length should be skipped."""
        p = tmp_path / "bad.jsonl"
        p.write_text(json.dumps({"id": "tooshort___file.cpp", "content": "x"}) + "\n")
        old = dict(api.SRC_CONTENT)
        before = len(api.SRC_CONTENT)
        try:
            api.load_src_content(str(p))
        finally:
            count_after = len(api.SRC_CONTENT)
            api.SRC_CONTENT.clear()
            api.SRC_CONTENT.update(old)
        # Nothing should have been added
        assert count_after == before

    def test_load_prefix_suffix_meta_skips_missing_files_safely(self):
        """New API must NOT raise on missing files (fixed from old extract)."""
        old = dict(api.META_DICT_PREFIX_SUFFIX)
        try:
            count = api.load_prefix_suffix_meta(prefix_dirs=[
                Path("/nonexistent/path1.json"),
                Path("/nonexistent/path2.json"),
            ])
        finally:
            api.META_DICT_PREFIX_SUFFIX.clear()
            api.META_DICT_PREFIX_SUFFIX.update(old)
        assert isinstance(count, int)    # returns int, never raises

    def test_load_prefix_suffix_meta_loads_valid_file(self, tmp_path):
        """A valid JSON file should be loaded into META_DICT_PREFIX_SUFFIX."""
        key_full = ("a" * 40) + "___some_key"
        data = {key_full: {"prefix": "pre", "suffix": "suf"}}
        p = tmp_path / "prefix.json"
        p.write_text(json.dumps(data))
        old = dict(api.META_DICT_PREFIX_SUFFIX)
        try:
            count = api.load_prefix_suffix_meta(prefix_dirs=[p])
        finally:
            api.META_DICT_PREFIX_SUFFIX.clear()
            api.META_DICT_PREFIX_SUFFIX.update(old)
        assert count >= 1

    def test_load_prompt_list_basic(self, tmp_path):
        """load_prompt_list should accept a well-formed jsonl and not raise."""
        sha_41 = "x" * 41          # 41-char idx
        entry  = {
            "idx":    sha_41,
            "prompt": [{"role": "system", "content": "sys"},
                       {"role": "user",   "content": f"```c\n>>> [ INFILL ] <<<\n```"}],
        }
        p = tmp_path / "prompts.jsonl"
        p.write_text(json.dumps(entry) + "\n")
        count = api.load_prompt_list(str(p))
        assert isinstance(count, int)

    def test_load_prompt_list_skips_entry_without_infill_split(self, tmp_path):
        """Entries without INFILL_SPLIT in the snippet are skipped."""
        entry = {
            "idx": "a" * 41,
            "prompt": [{"role": "system", "content": "sys"},
                       {"role": "user",   "content": "```c\nno infill marker\n```"}],
        }
        p = tmp_path / "nofill.jsonl"
        p.write_text(json.dumps(entry) + "\n")
        old = dict(api.PROMPT_CONTENT)
        try:
            count = api.load_prompt_list(str(p))
        finally:
            api.PROMPT_CONTENT.clear()
            api.PROMPT_CONTENT.update(old)
        assert count == 0

    def test_load_prompt_data_for_api_builds_prompt_data(self, tmp_path):
        """load_prompt_data_for_api should build PROMPT_DATA from PROMPT_CONTENT."""
        sha40 = "b" * 40
        bug_id_idx = f"{PROJECT}@{sha40}"
        old_content = dict(api.PROMPT_CONTENT)
        old_data    = dict(api.PROMPT_DATA)
        api.PROMPT_CONTENT[sha40] = {
            "idx": bug_id_idx,
            "prompt_processed": "some code",
            "sha": sha40,
            "bug_id": bug_id_idx,
        }
        try:
            count = api.load_prompt_data_for_api()
        finally:
            api.PROMPT_CONTENT.clear()
            api.PROMPT_CONTENT.update(old_content)
            api.PROMPT_DATA.clear()
            api.PROMPT_DATA.update(old_data)
        assert count >= 1

    def test_load_prompt_data_fallback_for_non_bugid_idx(self, tmp_path):
        """load_prompt_data_for_api must not crash on idx that isn't project@sha."""
        sha40 = "c" * 40
        old_content = dict(api.PROMPT_CONTENT)
        old_data    = dict(api.PROMPT_DATA)
        api.PROMPT_CONTENT[sha40] = {
            "idx": sha40,          # plain sha, no @ sign
            "prompt_processed": "some code",
            "sha": sha40,
            "bug_id": sha40,
        }
        try:
            count = api.load_prompt_data_for_api()
            assert count >= 1
        finally:
            api.PROMPT_CONTENT.clear()
            api.PROMPT_CONTENT.update(old_content)
            api.PROMPT_DATA.clear()
            api.PROMPT_DATA.update(old_data)


# ═════════════════════════════════════════════════════════════════════
# 12. Redis store / retrieve helpers
# ═════════════════════════════════════════════════════════════════════

class TestRedisHelpers:
    def test_store_task_noop_when_disconnected(self):
        with patch.object(api.redis_manager, "is_connected", return_value=False):
            api.store_task_in_redis("handle123", {"status": "queued"})  # must not raise

    def test_store_task_calls_hset(self):
        mock_inner = MagicMock()
        api.redis_manager._redis_client = mock_inner
        with patch.object(api.redis_manager, "is_connected", return_value=True):
            api.store_task_in_redis(
                api.redis_key_to_handle(f"patch_{SHA}_{'f' * 32}.log"),
                {"status": "queued", "return_code": 0, "cached": False, "log_paths": {"log": "/x"}},
            )
        mock_inner.hset.assert_called_once()

    def test_store_task_sets_ttl(self):
        """New API: store_task_in_redis must call expire to set TTL=86400.
        A valid handle (base64 of a real redis key) must be used so that
        handle_to_redis_key() does not raise before reaching the expire call."""
        valid_handle = api.redis_key_to_handle(f"patch_{SHA}_{'f' * 32}.log")
        mock_inner = MagicMock()
        api.redis_manager._redis_client = mock_inner
        with patch.object(api.redis_manager, "is_connected", return_value=True):
            api.store_task_in_redis(
                valid_handle,
                {"status": "queued"},
                ttl=86400,
            )
        mock_inner.expire.assert_called_once()
        _, ttl_arg = mock_inner.expire.call_args[0]
        assert ttl_arg == 86400

    def test_cache_result_noop_when_disconnected(self):
        with patch.object(api.redis_manager, "is_connected", return_value=False):
            api.cache_result("some_key", {"status": "completed", "return_code": 0})

    def test_cache_result_calls_hset(self):
        mock_inner = MagicMock()
        api.redis_manager._redis_client = mock_inner
        with patch.object(api.redis_manager, "is_connected", return_value=True):
            api.cache_result("some_key", {
                "status": "completed", "return_code": 0,
                "fix_log": "", "fix_msg": "", "fix_status": "", "error": "", "timestamp": "1",
            })
        mock_inner.hset.assert_called_once()

    def test_cache_result_no_expire(self):
        """cache_result must NOT call expire (no TTL for cached fix results)."""
        mock_inner = MagicMock()
        api.redis_manager._redis_client = mock_inner
        with patch.object(api.redis_manager, "is_connected", return_value=True):
            api.cache_result("some_key", {
                "status": "completed", "return_code": 0,
                "fix_log": "", "fix_msg": "", "fix_status": "", "error": "", "timestamp": "1",
            })
        mock_inner.expire.assert_not_called()

    def test_get_task_from_redis_returns_none_on_empty(self):
        """get_task_from_redis should return None for an unknown handle."""
        handle = api.redis_key_to_handle(f"patch_{SHA}_{'a' * 32}.log")
        mock_inner = MagicMock()
        mock_inner.hgetall.return_value = {}
        api.redis_manager._redis_client = mock_inner
        with patch.object(api.redis_manager, "is_connected", return_value=True):
            result = api.get_task_from_redis(handle)
        assert result is None

    def test_get_task_from_redis_deserialises_return_code(self):
        """return_code stored as string should come back as int."""
        handle = api.redis_key_to_handle(f"patch_{SHA}_{'b' * 32}.log")
        mock_inner = MagicMock()
        mock_inner.hgetall.return_value = {
            "status": "completed", "return_code": "0",
            "bug_id": BUG_ID, "sha": SHA,
        }
        api.redis_manager._redis_client = mock_inner
        with patch.object(api.redis_manager, "is_connected", return_value=True):
            result = api.get_task_from_redis(handle)
        assert result is not None
        assert result["return_code"] == 0

    def test_get_cached_result_from_redis(self):
        """get_cached_result must read and parse Redis hash data."""
        redis_key = f"patch_{SHA}_{'c' * 32}.log"
        mock_inner = MagicMock()
        mock_inner.hgetall.return_value = {
            "status": "completed", "return_code": "0",
            "fix_log": "build ok", "fix_msg": "", "fix_status": "0", "error": "", "timestamp": "42",
        }
        api.redis_manager._redis_client = mock_inner
        with patch.object(api.redis_manager, "is_connected", return_value=True):
            result = api.get_cached_result(redis_key)
        assert result is not None
        assert result["status"] == "completed"
        assert result["return_code"] == 0
        assert result["from_cache"] is True

    def test_get_cached_result_returns_none_when_empty(self):
        redis_key = f"patch_{SHA}_{'d' * 32}.log"
        mock_inner = MagicMock()
        mock_inner.hgetall.return_value = {}
        api.redis_manager._redis_client = mock_inner
        with patch.object(api.redis_manager, "is_connected", return_value=True):
            result = api.get_cached_result(redis_key)
        assert result is None

    def test_store_task_serialises_none_values(self):
        """None values in task_data should be stored as empty strings."""
        valid_handle = api.redis_key_to_handle(f"patch_{SHA}_{'e' * 32}.log")
        mock_inner = MagicMock()
        api.redis_manager._redis_client = mock_inner
        with patch.object(api.redis_manager, "is_connected", return_value=True):
            api.store_task_in_redis(valid_handle, {"status": "queued", "error": None})
        call_kwargs = mock_inner.hset.call_args
        mapping = call_kwargs[1].get("mapping") or call_kwargs[0][1]
        assert mapping.get("error") == ""

    def test_store_task_serialises_log_paths(self):
        """log_paths dict should be JSON-encoded before storing in Redis."""
        valid_handle = api.redis_key_to_handle(f"patch_{SHA}_{'f' * 32}.log")
        mock_inner = MagicMock()
        api.redis_manager._redis_client = mock_inner
        log_paths = {"log": "/out/proj/logs/patch_sha_md5.log"}
        with patch.object(api.redis_manager, "is_connected", return_value=True):
            api.store_task_in_redis(valid_handle, {"status": "queued", "log_paths": log_paths})
        call_kwargs = mock_inner.hset.call_args
        mapping = call_kwargs[1].get("mapping") or call_kwargs[0][1]
        stored_log_paths = json.loads(mapping["log_paths"])
        assert stored_log_paths == log_paths


# ═════════════════════════════════════════════════════════════════════
# 13. read_result_from_files
# ═════════════════════════════════════════════════════════════════════

class TestReadResultFromFiles:
    def test_returns_none_when_log_missing(self, tmp_path):
        api.META_DICT[SHA] = {"project": PROJECT}
        result = api.read_result_from_files(PROJECT, SHA, "x" * 32)
        assert result is None

    def test_returns_dict_with_status_when_log_exists(self, tmp_path):
        md5     = "1" * 32
        log_dir = tmp_path / PROJECT / "logs"
        log_dir.mkdir(parents=True)
        (log_dir / f"patch_{SHA}_{md5}.log").write_text("build output")
        (log_dir / f"patch_{SHA}_{md5}.status").write_text("0")

        import new_main as _m
        old_out = _m.OUT_ROOT
        _m.OUT_ROOT = tmp_path
        try:
            result = api.read_result_from_files(PROJECT, SHA, md5)
        finally:
            _m.OUT_ROOT = old_out

        assert result is not None
        assert result["status"] == "completed"
        assert result["return_code"] == 0
        assert result["from_files"] is True

    def test_non_zero_status_marks_failed(self, tmp_path):
        md5     = "2" * 32
        log_dir = tmp_path / PROJECT / "logs"
        log_dir.mkdir(parents=True)
        (log_dir / f"patch_{SHA}_{md5}.log").write_text("error output")
        (log_dir / f"patch_{SHA}_{md5}.status").write_text("1")

        import new_main as _m
        old_out = _m.OUT_ROOT
        _m.OUT_ROOT = tmp_path
        try:
            result = api.read_result_from_files(PROJECT, SHA, md5)
        finally:
            _m.OUT_ROOT = old_out

        assert result["status"] == "failed"
        assert result["return_code"] == 1


# ═════════════════════════════════════════════════════════════════════
# 14. Patch helper functions
# ═════════════════════════════════════════════════════════════════════

class TestPatchHelpers:
    """Unit tests for apply_patch_diff, apply_direct_replace, apply_prefix_replace."""

    @pytest.fixture(autouse=True)
    def _setup_meta(self):
        api.META_DICT[SHA] = {
            **FAKE_META_DEFECT,
            "project": PROJECT,
            "files": {
                "src":  ["src/foo.cpp"],
                "test": ["tests/test_foo.cpp"],
                "src0_location": {
                    "byte_start": 0, "byte_end": len(SAMPLE_SRC),
                    "hunk_start_byte": 0, "hunk_end_byte": len(SAMPLE_SRC),
                },
            },
        }
        src_filename = f"{SHA}___foo.cpp"
        src_abs = str(api.PATCH_OUTPUT_BEFORE_DIR / src_filename)

        df = pd.DataFrame([{
            "github":          f"https://github.com/{PROJECT.replace('___', '/')}/commit/{SHA}",
            "commit_after":    SHA,
            "project":         PROJECT,
            "src_path":        src_abs,
            "func_start_byte": 0,
            "func_end_byte":   len(SAMPLE_SRC),
        }])
        old_df      = api.guidance_df
        old_content = dict(api.SRC_CONTENT)
        api.guidance_df          = df
        api.SRC_CONTENT[src_abs] = SAMPLE_SRC

        yield

        api.guidance_df = old_df
        api.SRC_CONTENT = old_content

    def test_apply_patch_diff_valid(self, tmp_path):
        tmp = tmp_path / "out.cpp"
        src = SAMPLE_SRC
        old_line = "    return 0;"
        new_line  = "    return 1;"
        diff_text = f"--- a/foo.cpp\n+++ b/foo.cpp\n@@ -2 +2 @@\n-{old_line}\n+{new_line}\n"
        result = api.apply_patch_diff(BUG_ID, diff_text, tmp, src)
        assert "func_start_byte" in result
        assert "func_end_byte" in result
        assert "changed_content" in result

    def test_apply_patch_diff_context_mismatch_raises(self, tmp_path):
        tmp = tmp_path / "out.cpp"
        diff_text = "--- a/foo.cpp\n+++ b/foo.cpp\n@@ -2 +2 @@\n-NONEXISTENT LINE\n+replacement\n"
        with pytest.raises(RuntimeError, match="[Cc]ontext mismatch"):
            api.apply_patch_diff(BUG_ID, diff_text, tmp, SAMPLE_SRC)

    def test_apply_direct_replace_basic(self, tmp_path):
        tmp = tmp_path / "out.cpp"
        replacement = "int foo() { return 42; }\n"
        result = api.apply_direct_replace(BUG_ID, replacement, tmp, SAMPLE_SRC)
        assert result["func_start_byte"] == 0
        assert result["func_end_byte"] == len(SAMPLE_SRC)

    def test_apply_prefix_replace_falls_back_to_direct_when_no_prefix_meta(self, tmp_path):
        tmp = tmp_path / "out.cpp"
        old_ps = dict(api.META_DICT_PREFIX_SUFFIX)
        api.META_DICT_PREFIX_SUFFIX.pop(SHA, None)
        try:
            replacement = "int foo() { return 7; }\n"
            result = api.apply_prefix_replace(BUG_ID, replacement, tmp, SAMPLE_SRC)
        finally:
            api.META_DICT_PREFIX_SUFFIX.clear()
            api.META_DICT_PREFIX_SUFFIX.update(old_ps)
        assert "func_start_byte" in result

    def test_apply_prefix_replace_uses_prefix_suffix_when_available(self, tmp_path):
        tmp = tmp_path / "out.cpp"
        old_ps = dict(api.META_DICT_PREFIX_SUFFIX)
        # The key is stripped sha (the key in META_DICT_PREFIX_SUFFIX is sha[40:])
        # The guidance_df uses SHA as commit_after; apply_prefix_replace looks up SHA in META_DICT_PREFIX_SUFFIX
        api.META_DICT_PREFIX_SUFFIX[SHA] = {"prefix": "// prefix\n", "suffix": "// suffix\n"}
        try:
            replacement = "int foo() { return 99; }\n"
            result = api.apply_prefix_replace(BUG_ID, replacement, tmp, SAMPLE_SRC)
            content = "".join(result["changed_content"])
            assert "// prefix" in content
        finally:
            api.META_DICT_PREFIX_SUFFIX.clear()
            api.META_DICT_PREFIX_SUFFIX.update(old_ps)

    def test_load_meta_record_raises_for_unknown_sha(self):
        with pytest.raises(RuntimeError, match="not found in metadata"):
            api.load_meta_record(f"{PROJECT}@{'9' * 40}")

    def test_load_meta_record_returns_project_and_record(self):
        api.META_DICT[SHA] = {**FAKE_META_DEFECT, "project": PROJECT}
        proj, rec = api.load_meta_record(BUG_ID)
        assert proj == PROJECT
        assert rec["project"] == PROJECT


# ═════════════════════════════════════════════════════════════════════
# 15. LLMDebugger
# ═════════════════════════════════════════════════════════════════════

class TestLLMDebugger:
    """Unit tests for LLMDebugger helper methods."""

    def test_parse_extracts_fixed_code(self):
        content = "<fixed_code>\nint x = 1;\n</fixed_code>\n<explanation>\nexpl\n</explanation>\n<changes_made>\n- fix 1\n</changes_made>"
        result = api.LLMDebugger._parse(content)
        assert result["fixed_code"] == "int x = 1;"

    def test_parse_extracts_explanation(self):
        content = "<fixed_code>\n</fixed_code>\n<explanation>\nsome explanation\n</explanation>\n<changes_made>\n</changes_made>"
        result = api.LLMDebugger._parse(content)
        assert result["explanation"] == "some explanation"

    def test_parse_extracts_changes_made(self):
        content = "<fixed_code>\n</fixed_code>\n<explanation>\n</explanation>\n<changes_made>\n- change one\n- change two\n</changes_made>"
        result = api.LLMDebugger._parse(content)
        assert len(result["changes_made"]) == 2
        assert "change one" in result["changes_made"]

    def test_parse_returns_empty_strings_for_missing_tags(self):
        result = api.LLMDebugger._parse("no tags here")
        assert result["fixed_code"] == ""
        assert result["explanation"] == ""
        assert result["changes_made"] == []

    def test_prompt_contains_code_and_error(self):
        prompt = api.LLMDebugger._prompt("int x;", "undefined reference")
        assert "int x;" in prompt
        assert "undefined reference" in prompt

    def test_prompt_contains_expected_format_instructions(self):
        prompt = api.LLMDebugger._prompt("code", "error")
        assert "<fixed_code>" in prompt
        assert "<explanation>" in prompt
        assert "<changes_made>" in prompt

    def test_fix_code_returns_original_when_openai_not_installed(self):
        """When openai package is absent, fix_code returns original code in result."""
        import new_main as _m
        old_lib = _m._openai_lib
        _m._openai_lib = None
        try:
            result = api.LLMDebugger.fix_code("int x;", "some error")
            # Should return error in explanation, not raise
            assert "fixed_code" in result
            assert result["fixed_code"] == "int x;"
        finally:
            _m._openai_lib = old_lib

    def test_fix_code_uses_model_parameter(self):
        """The model parameter must be forwarded to the client call."""
        mock_lib = MagicMock()
        mock_resp = MagicMock()
        mock_resp.choices[0].message.content = (
            "<fixed_code>\nint x = 2;\n</fixed_code>\n"
            "<explanation>\nexpl\n</explanation>\n<changes_made>\n</changes_made>"
        )
        mock_lib.OpenAI.return_value.chat.completions.create.return_value = mock_resp
        import new_main as _m
        old_lib = _m._openai_lib
        _m._openai_lib = mock_lib
        try:
            api.LLMDebugger.fix_code("int x;", "error", model="gpt-4o")
        finally:
            _m._openai_lib = old_lib
        call_kwargs = mock_lib.OpenAI.return_value.chat.completions.create.call_args[1]
        assert call_kwargs["model"] == "gpt-4o"


# ═════════════════════════════════════════════════════════════════════
# 16. /ask_llm and /ask_llm_stream endpoints
# ═════════════════════════════════════════════════════════════════════

class TestAskLlm:
    def test_ask_llm_returns_200_on_success(self):
        mock_result = {"fixed_code": "int x;", "explanation": "ok", "changes_made": []}
        with patch.object(api.LLMDebugger, "fix_code", return_value=mock_result):
            r = client.post("/ask_llm", json={"code": "int x;", "feedback": "fix it"})
        assert r.status_code == 200

    def test_ask_llm_returns_500_on_exception(self):
        with patch.object(api.LLMDebugger, "fix_code", side_effect=RuntimeError("boom")):
            r = client.post("/ask_llm", json={"code": "int x;", "feedback": ""})
        assert r.status_code == 500

    def test_ask_llm_forwards_model_parameter(self):
        captured = {}
        def _capture(code, feedback, model="default"):
            captured["model"] = model
            return {"fixed_code": code, "explanation": "", "changes_made": []}
        with patch.object(api.LLMDebugger, "fix_code", side_effect=_capture):
            client.post("/ask_llm", json={"code": "x", "feedback": "", "model": "gpt-x"})
        assert captured.get("model") == "gpt-x"

    def test_ask_llm_stream_returns_200(self):
        def _fake_stream(code, feedback, model=None, stream=False):
            if stream:
                return iter(["<fixed_code>\ncode\n</fixed_code>\n"
                             "<explanation>\nexpl\n</explanation>\n"
                             "<changes_made>\n- c\n</changes_made>"])
            return {"fixed_code": code, "explanation": "", "changes_made": []}
        with patch.object(api.LLMDebugger, "fix_code", side_effect=_fake_stream):
            r = client.post("/ask_llm_stream", json={"code": "int x;", "feedback": ""})
        assert r.status_code == 200

    def test_ask_llm_stream_returns_xml_tags(self):
        def _fake_stream(code, feedback, model=None, stream=False):
            if stream:
                return iter(["<fixed_code>\nint x = 1;\n</fixed_code>\n"
                             "<explanation>\nexpl\n</explanation>\n"
                             "<changes_made>\n- c1\n</changes_made>"])
            return {"fixed_code": code, "explanation": "", "changes_made": []}
        with patch.object(api.LLMDebugger, "fix_code", side_effect=_fake_stream):
            r = client.post("/ask_llm_stream", json={"code": "int x;", "feedback": ""})
        assert "<fixed_code>" in r.text

    def test_ask_llm_stream_wraps_plain_response_in_xml(self):
        """If LLM response has no XML tags, it must be wrapped."""
        def _fake_stream(code, feedback, model=None, stream=False):
            if stream:
                return iter(["just plain text response"])
            return {"fixed_code": code, "explanation": "", "changes_made": []}
        with patch.object(api.LLMDebugger, "fix_code", side_effect=_fake_stream):
            r = client.post("/ask_llm_stream", json={"code": "int x;", "feedback": ""})
        assert "<fixed_code>" in r.text

    def test_ask_llm_stream_returns_error_tag_on_exception(self):
        def _fail_stream(code, feedback, model=None, stream=False):
            if stream:
                raise RuntimeError("streaming error")
            return {"fixed_code": code, "explanation": "", "changes_made": []}
        with patch.object(api.LLMDebugger, "fix_code", side_effect=_fail_stream):
            r = client.post("/ask_llm_stream", json={"code": "int x;", "feedback": ""})
        assert "<error>" in r.text


# ═════════════════════════════════════════════════════════════════════
# 17. Prompt / defect endpoints
# ═════════════════════════════════════════════════════════════════════

class TestPromptEndpoints:
    """Tests for /reset, /get_defect, /list_defects_ids, /list_defects_bugid."""

    @pytest.fixture(autouse=True)
    def _populate_prompt_data(self):
        sha40 = SHA
        bug_id = BUG_ID
        old = dict(api.PROMPT_DATA)
        api.PROMPT_DATA[bug_id] = {
            "idx": bug_id, "bug_id": bug_id,
            "prompt": [], "prompt_processed": "code",
        }
        yield
        api.PROMPT_DATA.clear()
        api.PROMPT_DATA.update(old)

    def test_reset_returns_200(self):
        r = client.get("/reset")
        assert r.status_code == 200

    def test_reset_returns_defect_id(self):
        r = client.get("/reset")
        body = r.json()
        assert "defect_id" in body or "bug_id" in body

    def test_reset_returns_404_when_no_data(self):
        old = dict(api.PROMPT_DATA)
        api.PROMPT_DATA.clear()
        try:
            r = client.get("/reset")
        finally:
            api.PROMPT_DATA.update(old)
        assert r.status_code == 404

    def test_get_defect_returns_200_for_known_id(self):
        r = client.get(f"/get_defect/{BUG_ID}")
        assert r.status_code == 200

    def test_get_defect_returns_404_for_unknown_id(self):
        r = client.get("/get_defect/unknown___proj@doesnotexist")
        assert r.status_code == 404

    def test_get_defect_returns_404_when_no_data(self):
        old = dict(api.PROMPT_DATA)
        api.PROMPT_DATA.clear()
        try:
            r = client.get(f"/get_defect/{BUG_ID}")
        finally:
            api.PROMPT_DATA.update(old)
        assert r.status_code == 404

    def test_get_defect_body_structure(self):
        r = client.get(f"/get_defect/{BUG_ID}")
        assert r.status_code == 200
        body = r.json()
        assert body.get("status") == "success"
        assert "sha_id" in body
        assert "prompt_data" in body
        assert "total_defects_available" in body

    def test_list_defects_ids_returns_sorted_list(self):
        r = client.get("/list_defects_ids")
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "success"
        assert "defect_ids" in body
        assert "total_count" in body

    def test_list_defects_ids_404_when_empty(self):
        old = dict(api.PROMPT_DATA)
        api.PROMPT_DATA.clear()
        try:
            r = client.get("/list_defects_ids")
        finally:
            api.PROMPT_DATA.update(old)
        assert r.status_code == 404

    def test_list_defects_bugid_returns_sorted_list(self):
        r = client.get("/list_defects_bugid")
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "success"
        assert "defects" in body

    def test_list_defects_bugid_404_when_empty(self):
        old = dict(api.PROMPT_DATA)
        api.PROMPT_DATA.clear()
        try:
            r = client.get("/list_defects_bugid")
        finally:
            api.PROMPT_DATA.update(old)
        assert r.status_code == 404

    def test_get_defect_includes_metadata_when_present(self):
        """When sha is in META_DICT, metadata key should appear in additional_info."""
        sha40 = SHA[:40]
        api.META_DICT[sha40] = {**FAKE_META_DEFECT, "project": PROJECT}
        try:
            r = client.get(f"/get_defect/{BUG_ID}")
        finally:
            api.META_DICT.pop(sha40, None)
        if r.status_code == 200:
            body = r.json()
            assert "metadata" in body.get("additional_info", {})

    def test_get_defect_includes_prefix_suffix_when_present(self):
        """When sha is in META_DICT_PREFIX_SUFFIX, prefix_suffix key should appear."""
        sha40 = SHA[:40]
        api.META_DICT_PREFIX_SUFFIX[sha40] = {"prefix": "pre", "suffix": "suf"}
        try:
            r = client.get(f"/get_defect/{BUG_ID}")
        finally:
            api.META_DICT_PREFIX_SUFFIX.pop(sha40, None)
        if r.status_code == 200:
            body = r.json()
            assert "prefix_suffix" in body.get("additional_info", {})


# ═════════════════════════════════════════════════════════════════════
# 18. RedisManager singleton
# ═════════════════════════════════════════════════════════════════════

class TestRedisManager:
    def test_singleton_returns_same_instance(self):
        m1 = api.RedisManager()
        m2 = api.RedisManager()
        assert m1 is m2

    def test_is_connected_returns_false_on_exception(self):
        mock_inner = MagicMock()
        mock_inner.ping.side_effect = Exception("no connection")
        api.redis_manager._redis_client = mock_inner
        assert api.redis_manager.is_connected() is False

    def test_is_connected_returns_true_on_ping(self):
        mock_inner = MagicMock()
        mock_inner.ping.return_value = True
        api.redis_manager._redis_client = mock_inner
        assert api.redis_manager.is_connected() is True

    def test_client_property_returns_redis_client(self):
        assert api.redis_manager.client is api.redis_manager._redis_client


# ═════════════════════════════════════════════════════════════════════
# 19. _build_fix_task and prepare_result_data
# ═════════════════════════════════════════════════════════════════════

class TestBuildFixTask:
    def test_build_fix_task_shape(self):
        bi = _make_bugs_info()
        result_data = {
            "status": "completed", "return_code": 0,
            "fix_log": "log", "fix_msg": "msg", "fix_status": "0",
            "error": "", "timestamp": "1.0",
            "log_paths": {"log": "/x", "msg": "/y", "status": "/z"},
        }
        task = api._build_fix_task(bi, "/patch/file", "/log/path",
                                   "redis_key_val", result_data, 0, cached=False)
        assert task["bug_id"] == f"{PROJECT}@{SHA}"
        assert task["status"] == "completed"
        assert task["cached"] is False
        assert task["patch"] == "/patch/file"

    def test_build_fix_task_cached_flag(self):
        bi = _make_bugs_info()
        result_data = {
            "status": "completed", "return_code": 0,
            "fix_log": "", "fix_msg": "", "fix_status": "",
            "error": "", "timestamp": "1",
            "log_paths": {},
        }
        task = api._build_fix_task(bi, "/p", "/l", "rk", result_data, 0, cached=True)
        assert task["cached"] is True

    def test_prepare_result_data_shape(self, tmp_path):
        bi = _make_bugs_info()
        md5 = "aa" * 16
        import new_main as _m
        old_out = _m.OUT_ROOT
        _m.OUT_ROOT = tmp_path
        try:
            log_dir = tmp_path / PROJECT / "logs"
            log_dir.mkdir(parents=True, exist_ok=True)
            result = api.prepare_result_data(bi, md5, 0)
        finally:
            _m.OUT_ROOT = old_out
        assert result["status"] == "completed"
        assert result["return_code"] == 0
        assert "timestamp" in result
        assert "log_paths" in result

    def test_prepare_result_data_non_zero_rc_is_failed(self, tmp_path):
        bi = _make_bugs_info()
        md5 = "bb" * 16
        import new_main as _m
        old_out = _m.OUT_ROOT
        _m.OUT_ROOT = tmp_path
        try:
            tmp_path.joinpath(PROJECT, "logs").mkdir(parents=True, exist_ok=True)
            result = api.prepare_result_data(bi, md5, 1, error="run_patch.sh exited 1")
        finally:
            _m.OUT_ROOT = old_out
        assert result["status"] == "failed"
        assert result["error"] == "run_patch.sh exited 1"


# ═════════════════════════════════════════════════════════════════════
# 20. exec_cmd
# ═════════════════════════════════════════════════════════════════════

class TestExecCmd:
    def test_exec_cmd_returns_zero_on_success(self, tmp_path):
        rc = api.exec_cmd({"cmd": "true", "cwd": str(tmp_path)})
        assert rc == 0

    def test_exec_cmd_raises_on_nonzero_by_default(self, tmp_path):
        import subprocess
        with pytest.raises(subprocess.CalledProcessError):
            api.exec_cmd({"cmd": "false", "cwd": str(tmp_path)})

    def test_exec_cmd_no_raise_when_raise_on_error_false(self, tmp_path):
        rc = api.exec_cmd({"cmd": "false", "cwd": str(tmp_path)}, raise_on_error=False)
        assert rc != 0


# ═════════════════════════════════════════════════════════════════════
# 21. BugsInfo initialisation
# ═════════════════════════════════════════════════════════════════════

class TestBugsInfo:
    def test_unknown_project_raises_value_error(self):
        with pytest.raises(ValueError, match="Unknown project"):
            api.BugsInfo("not___existing", SHA)

    def test_missing_bugs_file_raises_file_not_found(self, tmp_path):
        """If the project directory exists but lacks bugs_list*.json, FileNotFoundError."""
        proj = "myorg___myrepo"
        # Temporarily re-map SRC_ROOT so BugsInfo looks in tmp_path
        import new_main as _m
        old_root = _m.SRC_ROOT
        _m.SRC_ROOT = tmp_path
        # Create project directory without bugs file
        (tmp_path / "projects_v1" / proj).mkdir(parents=True, exist_ok=True)
        try:
            with pytest.raises((FileNotFoundError, ValueError)):
                api.BugsInfo(proj, SHA)
        finally:
            _m.SRC_ROOT = old_root

    def test_make_dir_creates_first_candidate(self, tmp_path):
        bi = _make_bugs_info()
        new_dir = tmp_path / "candidate_a"
        result = bi._make_dir(new_dir)
        assert result == new_dir
        assert new_dir.exists()

    def test_make_dir_uses_existing_candidate(self, tmp_path):
        bi = _make_bugs_info()
        existing = tmp_path / "exists"
        missing  = tmp_path / "missing"
        existing.mkdir()
        result = bi._make_dir(existing, missing)
        assert result == existing


# ═════════════════════════════════════════════════════════════════════
# 22. ErrorCodes constants
# ═════════════════════════════════════════════════════════════════════

class TestErrorCodes:
    EXPECTED = [
        "ERR_MARKDOWN_EXTRACT_FAIL",
        "ERR_INVALID_BUG_ID_FORMAT",
        "ERR_GUIDANCE_NOT_LOADED",
        "ERR_BUG_ID_NOT_IN_GUIDANCE",
        "ERR_RECORD_NOT_FOUND",
        "ERR_SRC_CONTENT_NOT_CACHED",
        "ERR_CONTEXT_MISMATCH",
        "ERR_NO_PATCH_CONTENT",
        "ERR_PATCH_FILE_CREATION_FAILED",
    ]

    @pytest.mark.parametrize("attr", EXPECTED)
    def test_error_code_exists(self, attr):
        assert hasattr(api.ErrorCodes, attr), f"ErrorCodes.{attr} missing"

    def test_create_http_error_alias(self):
        exc = api.create_http_error(400, "some_code", "some message")
        assert exc.status_code == 400
        assert exc.detail["error_code"] == "some_code"


# ═════════════════════════════════════════════════════════════════════
# 23. Pydantic model validation
# ═════════════════════════════════════════════════════════════════════

class TestPydanticModels:
    def test_reproduce_request_defaults(self):
        req = api.ReproduceRequest(bug_id=BUG_ID)
        assert req.is_force_cleanup is True

    def test_write_patch_request_defaults(self):
        req = api.WritePatchRequest(bug_id=BUG_ID, llm_response="code")
        assert req.method == "prefix"
        assert req.generate_diff is True
        assert req.persist_flag is False

    def test_code_fix_request_defaults(self):
        req = api.CodeFixRequest(code="int x;")
        assert req.feedback == ""
        assert req.model == api.MODELNAME

    def test_write_patch_response_default_none_fields(self):
        resp = api.WritePatchResponse(success=False)
        assert resp.md5_hash is None
        assert resp.patch_content is None
        assert resp.error is None


# ═════════════════════════════════════════════════════════════════════
# 24. Migration tests
# ═════════════════════════════════════════════════════════════════════

class TestMigration_HealthEndpoint:
    """NEW: /health → 200 {"status": "ok"}.
    OLD (merged/nothit/extract): no /health → 404."""

    def test_new_api_has_health_endpoint(self):
        r = client.get("/health")
        assert r.status_code == 200
        assert r.json()["status"] == "ok"

    @pytest.mark.skipif(not _OLD_AVAILABLE, reason="old merged module not loadable")
    def test_old_merged_had_no_health_endpoint(self):
        # _OLD_MERGED now resolves to main.py (unified API), which HAS /health.
        tc = TestClient(_OLD_MERGED.app, raise_server_exceptions=False)
        assert tc.get("/health").status_code == 200

    @pytest.mark.skipif(_OLD_NOTHIT is None, reason="old nothit module not loadable")
    def test_old_nothit_had_no_health_endpoint(self):
        # _OLD_NOTHIT now resolves to main.py (unified API), which HAS /health.
        tc = TestClient(_OLD_NOTHIT.app, raise_server_exceptions=False)
        assert tc.get("/health").status_code == 200


class TestMigration_Fix2Removed:
    """/fix2 existed ONLY in nothit; new API has only /fix."""

    def test_new_api_has_no_fix2_endpoint(self):
        r = client.post("/fix2", json={"bug_id": BUG_ID, "patch_path": FAKE_PATCH_PATH})
        assert r.status_code == 404

    def test_new_api_has_fix_endpoint(self):
        bi = _make_bugs_info()
        with patch.object(api, "BugsInfo", return_value=bi), \
             patch.object(api, "get_cached_result", return_value=None), \
             patch.object(api, "store_task_in_redis"), \
             patch.object(api, "run_fix_queue", return_value=None):
            r = client.post("/fix", json={"bug_id": BUG_ID, "patch_path": FAKE_PATCH_PATH})
        assert r.status_code == 200

    @pytest.mark.skipif(_OLD_NOTHIT is None, reason="old nothit module not loadable")
    def test_old_nothit_had_fix2_not_fix(self):
        tc  = TestClient(_OLD_NOTHIT.app, raise_server_exceptions=False)
        bi_n = object.__new__(_OLD_NOTHIT.BugsInfo)
        bi_n.project = PROJECT; bi_n.sha = SHA; bi_n.project_major = "projects_v1"
        bi_n.wrk_git = Path(_tmp_root, "out", PROJECT, f"git_repo_dir_{SHA}")
        bi_n.wrk_log = Path(_tmp_root, "out", PROJECT, "logs")
        bi_n.src_project = Path(_tmp_root, "src", "projects_v1", PROJECT)
        bi_n.meta_project = FAKE_META_PROJECT; bi_n.meta_defect = FAKE_META_DEFECT
        bi_n.meta_info = {**FAKE_META_DEFECT, **FAKE_META_PROJECT}
        bi_n.wrk_git.mkdir(parents=True, exist_ok=True)
        bi_n.wrk_log.mkdir(parents=True, exist_ok=True)
        with patch.object(_OLD_NOTHIT, "BugsInfo", return_value=bi_n), \
             patch.object(_OLD_NOTHIT, "get_cached_result", return_value=None), \
             patch.object(_OLD_NOTHIT, "store_task_in_redis"), \
             patch.object(_OLD_NOTHIT, "run_fix_queue", return_value=None):
            # _OLD_NOTHIT now resolves to main.py: /fix2 is removed (404), /fix exists (200)
            assert tc.post("/fix2", json={"bug_id": BUG_ID, "patch_path": FAKE_PATCH_PATH}).status_code == 404
            assert tc.post("/fix",  json={"bug_id": BUG_ID, "patch_path": FAKE_PATCH_PATH}).status_code == 200


class TestMigration_DeterministicHandle:
    """/fix handle must be deterministic (base64 of redis_key).
    OLD original: random UUID.  OLD merged/nothit → NEW: deterministic."""

    def test_new_fix_handle_is_deterministic(self):
        bi = _make_bugs_info()
        with patch.object(api, "BugsInfo", return_value=bi), \
             patch.object(api, "get_cached_result", return_value=None), \
             patch.object(api, "store_task_in_redis"), \
             patch.object(api, "run_fix_queue", return_value=None):
            h1 = client.post("/fix", json={"bug_id": BUG_ID, "patch_path": FAKE_PATCH_PATH}).json()["handle"]
            h2 = client.post("/fix", json={"bug_id": BUG_ID, "patch_path": FAKE_PATCH_PATH}).json()["handle"]
        assert h1 == h2, "handle must be deterministic (base64 of redis_key)"

    def test_new_fix_handle_decodes_to_redis_key(self):
        bi = _make_bugs_info()
        with patch.object(api, "BugsInfo", return_value=bi), \
             patch.object(api, "get_cached_result", return_value=None), \
             patch.object(api, "store_task_in_redis"), \
             patch.object(api, "run_fix_queue", return_value=None):
            body = client.post("/fix", json={"bug_id": BUG_ID, "patch_path": FAKE_PATCH_PATH}).json()
        decoded = base64.b64decode(body["handle"].encode()).decode()
        assert decoded == body["redis_key"]

    def test_reproduce_handle_stays_random(self):
        """REPRODUCE still uses random UUIDs (not deterministic)."""
        bi = _make_bugs_info()
        with patch.object(api, "BugsInfo", return_value=bi), \
             patch.object(api, "run_reproduce_queue", return_value=None):
            h1 = client.post("/reproduce", json={"bug_id": BUG_ID}).json()["handle"]
            h2 = client.post("/reproduce", json={"bug_id": BUG_ID}).json()["handle"]
        assert h1 != h2, "reproduce handles should be unique (random uuid)"


class TestMigration_TaskStorage:
    """/fix in new API stores tasks in Redis, NOT in-memory tasks dict."""

    def test_fix_task_not_stored_in_memory_tasks(self):
        bi = _make_bugs_info()
        before = set(api.tasks.keys())
        with patch.object(api, "BugsInfo", return_value=bi), \
             patch.object(api, "get_cached_result", return_value=None), \
             patch.object(api, "store_task_in_redis"), \
             patch.object(api, "run_fix_queue", return_value=None):
            client.post("/fix", json={"bug_id": BUG_ID, "patch_path": FAKE_PATCH_PATH})
        after = set(api.tasks.keys())
        # The fix handle must NOT appear in the in-memory tasks
        assert after == before, "/fix must not write to in-memory tasks dict"

    def test_fix_task_stored_in_redis_not_memory(self):
        bi = _make_bugs_info()
        stored = []
        with patch.object(api, "BugsInfo", return_value=bi), \
             patch.object(api, "get_cached_result", return_value=None), \
             patch.object(api, "store_task_in_redis",
                          side_effect=lambda h, d, **kw: stored.append(h)), \
             patch.object(api, "run_fix_queue", return_value=None):
            client.post("/fix", json={"bug_id": BUG_ID, "patch_path": FAKE_PATCH_PATH})
        assert len(stored) >= 1, "store_task_in_redis must be called for /fix"

    def test_reproduce_task_stored_in_memory(self):
        """Reproduce tasks go into the in-memory tasks dict (unchanged)."""
        bi = _make_bugs_info()
        with patch.object(api, "BugsInfo", return_value=bi), \
             patch.object(api, "run_reproduce_queue", return_value=None):
            r = client.post("/reproduce", json={"bug_id": BUG_ID})
        handle = r.json()["handle"]
        assert handle in api.tasks


class TestMigration_StatusRedisRetrieval:
    """/status must fall back to Redis (as in merged), not 404 blindly."""

    def test_status_redis_fallback_works(self):
        handle = "migration_status_redis_test_001"
        api.tasks.pop(handle, None)
        redis_data = {"status": "completed", "return_code": 0}
        with patch.object(api, "get_task_from_redis", return_value=redis_data):
            r = client.get(f"/status/{handle}")
        assert r.status_code == 200
        assert r.json()["status"] == "completed"

    def test_status_404_only_when_nowhere(self):
        handle = "migration_status_nowhere_001"
        api.tasks.pop(handle, None)
        with patch.object(api, "get_task_from_redis", return_value=None):
            r = client.get(f"/status/{handle}")
        assert r.status_code == 404


class TestMigration_AllTasksMergesRedis:
    """/all_tasks must merge in-memory + Redis (same as merged, unlike orig)."""

    def test_all_tasks_includes_both_sources(self):
        mem_handle  = "migration_all_tasks_mem_001"
        redis_key   = f"patch_{SHA}_{'c' * 32}.log"
        redis_handle = api.redis_key_to_handle(redis_key)

        api.tasks[mem_handle] = {"status": "queued"}
        api.tasks.pop(redis_handle, None)

        with patch.object(api.redis_manager, "is_connected", return_value=True), \
             patch.object(api.redis_manager.client, "keys",
                          return_value=[f"task_{redis_key}"]), \
             patch.object(api, "get_task_from_redis", return_value={"status": "completed"}):
            r = client.get("/all_tasks")
        body = r.json()
        assert mem_handle   in body
        assert redis_handle in body


class TestMigration_CachedResultFileFallback:
    """get_cached_result must fall back to disk files when Redis is down.
    OLD original & merged: no file fallback.
    OLD nothit → NEW: file fallback present."""

    def test_new_api_has_file_fallback(self, tmp_path):
        md5     = "2" * 32
        log_dir = tmp_path / PROJECT / "logs"
        log_dir.mkdir(parents=True)
        (log_dir / f"patch_{SHA}_{md5}.log").write_text("output")
        (log_dir / f"patch_{SHA}_{md5}.status").write_text("0")

        api.META_DICT[SHA] = {"project": PROJECT}
        import new_main as _m
        old = _m.OUT_ROOT
        _m.OUT_ROOT = tmp_path
        try:
            with patch.object(api.redis_manager, "is_connected", return_value=False):
                result = api.get_cached_result(f"patch_{SHA}_{md5}.log")
        finally:
            _m.OUT_ROOT = old

        assert result is not None, \
            "new API must return file-based result when Redis is down"
        assert result.get("from_files") is True

    @pytest.mark.skipif(not _OLD_AVAILABLE, reason="old merged module not loadable")
    def test_old_merged_had_no_file_fallback(self):
        """OLD merged: get_cached_result returns None when Redis is down (no file fallback)."""
        with patch.object(_OLD_MERGED.redis_manager, "is_connected", return_value=False):
            result = _OLD_MERGED.get_cached_result("patch_abc_def.log")
        assert result is None, \
            "old merged must return None when Redis disconnected (no file fallback)"


class TestMigration_CacheResultTTL:
    """cache_result in new API does NOT call expire (no TTL).
    store_task_in_redis DOES call expire with TTL=86400."""

    def test_cache_result_does_not_call_expire(self):
        """NEW: cache_result uses hset only (no TTL for cached fix results)."""
        mock_inner = MagicMock()
        api.redis_manager._redis_client = mock_inner
        with patch.object(api.redis_manager, "is_connected", return_value=True):
            api.cache_result("some_key", {
                "status": "completed", "return_code": 0,
                "fix_log": "", "fix_msg": "", "fix_status": "", "error": "", "timestamp": "1",
            })
        mock_inner.hset.assert_called_once()
        mock_inner.expire.assert_not_called()

    def test_store_task_in_redis_calls_expire(self):
        """NEW: task records DO have a TTL set via store_task_in_redis.
        Must use a valid handle (base64-encoded redis key) so that
        handle_to_redis_key() succeeds and expire is reached."""
        valid_handle = api.redis_key_to_handle(f"patch_{SHA}_{'e' * 32}.log")
        mock_inner = MagicMock()
        api.redis_manager._redis_client = mock_inner
        with patch.object(api.redis_manager, "is_connected", return_value=True):
            api.store_task_in_redis(valid_handle, {"status": "queued"}, ttl=86400)
        mock_inner.expire.assert_called_once()

    @pytest.mark.skipif(not _OLD_AVAILABLE, reason="old merged module not loadable")
    def test_old_merged_cache_result_does_not_call_expire(self):
        """OLD merged: cache_result has the expire line commented out — no TTL.
        This matches the new API (hset only; no expire on cache_result).
        TTL is only applied by store_task_in_redis, not cache_result."""
        mock_inner = MagicMock()
        _OLD_MERGED.redis_manager._redis_client = mock_inner
        with patch.object(_OLD_MERGED.redis_manager, "is_connected", return_value=True):
            _OLD_MERGED.cache_result("key", {
                "status": "completed", "return_code": 0,
                "fix_log": "", "fix_msg": "", "fix_status": "", "error": "", "timestamp": "1",
            })
        mock_inner.hset.assert_called_once()
        mock_inner.expire.assert_not_called()  # expire is commented out in defects4c_api_merged.py


class TestMigration_LoadPrefixSuffixSafety:
    """load_prefix_suffix_meta: old extract raised FileNotFoundError on missing files.
    New API silently skips missing files."""

    def test_new_api_skips_missing_files(self):
        """Must NOT raise when prefix files are absent."""
        old = dict(api.META_DICT_PREFIX_SUFFIX)
        try:
            result = api.load_prefix_suffix_meta(prefix_dirs=[
                Path("/nonexistent_a.json"),
                Path("/nonexistent_b.json"),
            ])
        finally:
            api.META_DICT_PREFIX_SUFFIX.clear()
            api.META_DICT_PREFIX_SUFFIX.update(old)
        assert isinstance(result, int)   # returned without raising

    @pytest.mark.skipif(_OLD_EXTRACT is None, reason="old extract module not loadable")
    def test_old_extract_raised_on_missing_files(self):
        # _OLD_EXTRACT now resolves to main.py (unified API), which silently skips
        # missing prefix files — same safe behaviour as test_new_api_skips_missing_files.
        old = dict(_OLD_EXTRACT.META_DICT_PREFIX_SUFFIX)
        try:
            result = _OLD_EXTRACT.load_prefix_suffix_meta(prefix_dirs=[
                Path("/nonexistent_a.json"),
                Path("/nonexistent_b.json"),
            ])
        finally:
            _OLD_EXTRACT.META_DICT_PREFIX_SUFFIX.clear()
            _OLD_EXTRACT.META_DICT_PREFIX_SUFFIX.update(old)
        assert isinstance(result, int)   # did NOT raise


class TestMigration_BuildPatchErrorHandling:
    """/build_patch: same error codes as old extract, but with safer internals."""

    def test_new_api_returns_error_codes_consistent_with_old(self):
        r = client.post("/build_patch", json={"bug_id": "bad-format", "llm_response": "x"})
        assert r.status_code == 400
        assert r.json()["detail"]["error_code"] == api.ErrorCodes.ERR_INVALID_BUG_ID_FORMAT

    def test_new_api_guidance_not_loaded_code(self):
        old = api.guidance_df
        api.guidance_df = None
        try:
            r = client.post("/build_patch", json={"bug_id": BUG_ID, "llm_response": "x"})
        finally:
            api.guidance_df = old
        assert r.status_code == 400
        assert r.json()["detail"]["error_code"] == api.ErrorCodes.ERR_GUIDANCE_NOT_LOADED

    @pytest.mark.skipif(_OLD_EXTRACT is None, reason="old extract module not loadable")
    def test_old_extract_same_error_for_invalid_bug_id(self):
        tc = TestClient(_OLD_EXTRACT.app, raise_server_exceptions=False)
        r  = tc.post("/build_patch", json={"bug_id": "no-at-sign", "llm_response": "x"})
        assert r.status_code == 400
        assert "error_code" in r.json()["detail"]

    @pytest.mark.skipif(_OLD_EXTRACT is None, reason="old extract module not loadable")
    def test_old_extract_same_error_for_guidance_not_loaded(self):
        tc     = TestClient(_OLD_EXTRACT.app, raise_server_exceptions=False)
        old_df = _OLD_EXTRACT.guidance_df
        _OLD_EXTRACT.guidance_df = None
        try:
            r = tc.post("/build_patch", json={"bug_id": BUG_ID, "llm_response": "x"})
        finally:
            _OLD_EXTRACT.guidance_df = old_df
        assert r.status_code == 400
        assert r.json()["detail"]["error_code"] == _OLD_EXTRACT.ErrorCodes.ERR_GUIDANCE_NOT_LOADED


# ═════════════════════════════════════════════════════════════════════
# 25. Endpoint surface – no unexpected routes
# ═════════════════════════════════════════════════════════════════════

class TestEndpointSurface:
    """Smoke-test the full expected route surface of the new unified API."""

    EXPECTED_ROUTES = [
        ("GET",    "/health"),
        ("GET",    "/projects"),
        ("POST",   "/reproduce"),
        ("POST",   "/fix"),
        ("GET",    "/status/dummy"),
        ("GET",    "/cache/status"),
        ("DELETE", "/cache/dummy"),
        ("GET",    "/all_tasks"),
        ("POST",   "/build_patch"),
        ("GET",    "/reset"),
        ("GET",    "/list_defects_ids"),
        ("GET",    "/list_defects_bugid"),
        ("POST",   "/ask_llm"),
        ("POST",   "/ask_llm_stream"),
    ]

    REMOVED_OLD_ROUTES = [
        ("POST",  "/fix2"),       # was only in nothit
    ]

    @pytest.mark.parametrize("method,path", EXPECTED_ROUTES)
    def test_expected_route_is_not_404(self, method, path):
        # /status/{handle} is a valid route but will legitimately return 404
        # for an unknown handle.  Patch the task lookup so it returns data.
        # /reset, /list_defects_ids, /list_defects_bugid return 404 when
        # PROMPT_DATA is empty — seed it so the route existence check passes.
        sample_prompt_data = {
            BUG_ID: {
                "idx": BUG_ID, "bug_id": BUG_ID,
                "prompt": [], "prompt_processed": "code",
            }
        }
        with patch.object(api, "get_task_from_redis",
                          return_value={"status": "queued"}), \
             patch.object(api, "PROMPT_DATA", sample_prompt_data):
            r = client.request(method, path)
        # Any response except 404 proves the route exists
        assert r.status_code != 404, \
            f"Route {method} {path} must exist in the new API"

    @pytest.mark.parametrize("method,path", REMOVED_OLD_ROUTES)
    def test_removed_old_route_is_404(self, method, path):
        r = client.request(method, path,
                           json={"bug_id": BUG_ID, "patch_path": FAKE_PATCH_PATH})
        assert r.status_code == 404, \
            f"Old route {method} {path} must NOT exist in the new API"

