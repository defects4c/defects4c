"""
test_migration_complete.py
==========================
Comprehensive test suite for defects4c_api.py (the NEW unified service).

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
from unittest.mock import MagicMock, patch, call

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
import defects4c_api as api  # noqa: E402

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
_OLD_ORIG    = _load_old_module("defects4c_api_orig_mod",
                                "/src/defects4c_api_orig.py")  # may not exist

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

    # ── extract_inline_snippet ────────────────────────────────────────

    def test_extracts_code_from_backtick_block(self):
        assert api.extract_inline_snippet("```c\nint x = 1;\n```") == "int x = 1;"

    def test_returns_none_when_no_backtick_block(self):
        assert api.extract_inline_snippet("no backticks here") is None

    # ── md5 ───────────────────────────────────────────────────────────

    def test_md5_is_32_char_lowercase_hex(self):
        result = api.md5("hello world")
        assert len(result) == 32
        assert result == result.lower()

    def test_md5_strips_and_lowercases_input(self):
        assert api.md5("  HELLO  ") == api.md5("hello")

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

    # ── get_log_file_paths ────────────────────────────────────────────

    def test_log_paths_contain_sha_and_md5(self):
        md5 = "e" * 32
        paths = api.get_log_file_paths(PROJECT, SHA, md5)
        for ext in ("log", "msg", "status"):
            assert ext in paths
            assert SHA in paths[ext]
            assert md5 in paths[ext]


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

    def test_parse_redis_key_valid(self):
        md5 = "a" * 32
        api.META_DICT[SHA] = {"project": PROJECT}
        project, sha, patch_md5 = api.parse_redis_key(f"patch_{SHA}_{md5}.log")
        assert project == PROJECT and sha == SHA and patch_md5 == md5

    def test_parse_redis_key_invalid_format_raises(self):
        with pytest.raises(ValueError):
            api.parse_redis_key("wrong_format")

    def test_parse_redis_key_unknown_sha_raises(self):
        with pytest.raises(ValueError, match="Cannot find project"):
            api.parse_redis_key(f"patch_{'z' * 40}_{'a' * 32}.log")

    def test_get_cached_result_returns_none_when_disconnected(self):
        with patch.object(api.redis_manager, "is_connected", return_value=False), \
             patch.object(api, "parse_redis_key", side_effect=ValueError("bad")):
            result = api.get_cached_result("patch_abc_def.log")
        assert result is None

    def test_get_cached_result_returns_typed_data_from_redis(self):
        fake_data = {
            "status": "completed", "return_code": "0",
            "fix_log": "passed", "fix_msg": "", "fix_status": "",
            "error": "", "timestamp": "123",
        }
        with patch.object(api.redis_manager, "is_connected", return_value=True), \
             patch.object(api.redis_manager.client, "hgetall", return_value=fake_data):
            result = api.get_cached_result("some_key")
        assert result is not None
        assert result["return_code"] == 0         # stored as str, returned as int
        assert result["from_cache"] is True


# ═════════════════════════════════════════════════════════════════════
# 13. File-fallback path
# ═════════════════════════════════════════════════════════════════════

class TestFileFallback:
    def test_cached_result_falls_back_to_disk_files(self, tmp_path):
        md5     = "0" * 32
        log_dir = tmp_path / PROJECT / "logs"
        log_dir.mkdir(parents=True)
        (log_dir / f"patch_{SHA}_{md5}.log").write_text("test output")
        (log_dir / f"patch_{SHA}_{md5}.status").write_text("0")

        api.META_DICT[SHA] = {"project": PROJECT}
        old_out    = api.OUT_ROOT
        import defects4c_api as _m
        _m.OUT_ROOT = tmp_path
        try:
            with patch.object(api.redis_manager, "is_connected", return_value=False):
                result = api.get_cached_result(f"patch_{SHA}_{md5}.log")
        finally:
            _m.OUT_ROOT = old_out

        assert result is not None
        assert result["status"] == "completed"
        assert result["return_code"] == 0

    def test_read_result_from_files_returns_none_for_missing_log(self):
        assert api.read_result_from_files(PROJECT, "nonexistent_sha", "nonexistent_md5") is None

    def test_read_result_status_1_gives_failed(self, tmp_path):
        md5     = "1" * 32
        log_dir = tmp_path / PROJECT / "logs"
        log_dir.mkdir(parents=True)
        (log_dir / f"patch_{SHA}_{md5}.log").write_text("output")
        (log_dir / f"patch_{SHA}_{md5}.status").write_text("1")
        (log_dir / f"patch_{SHA}_{md5}.msg").write_text("")

        import defects4c_api as _m
        old = _m.OUT_ROOT
        _m.OUT_ROOT = tmp_path
        try:
            result = api.read_result_from_files(PROJECT, SHA, md5)
        finally:
            _m.OUT_ROOT = old

        assert result is not None
        assert result["return_code"] == 1
        assert result["status"] == "failed"


# ═════════════════════════════════════════════════════════════════════
# 14. Migration-correctness tests
#     These tests explicitly verify how the new API differs from
#     the old multi-file system.  Old modules are loaded when
#     available; otherwise the test is an assertion on the new API.
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
        tc = TestClient(_OLD_MERGED.app, raise_server_exceptions=False)
        assert tc.get("/health").status_code == 404

    @pytest.mark.skipif(_OLD_NOTHIT is None, reason="old nothit module not loadable")
    def test_old_nothit_had_no_health_endpoint(self):
        tc = TestClient(_OLD_NOTHIT.app, raise_server_exceptions=False)
        assert tc.get("/health").status_code == 404


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
            assert tc.post("/fix2", json={"bug_id": BUG_ID, "patch_path": FAKE_PATCH_PATH}).status_code == 200
            assert tc.post("/fix",  json={"bug_id": BUG_ID, "patch_path": FAKE_PATCH_PATH}).status_code == 404


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
        import defects4c_api as _m
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
        """OLD extract: load_prefix_suffix_meta raises on missing files."""
        with pytest.raises((FileNotFoundError, OSError, Exception)):
            _OLD_EXTRACT.load_prefix_suffix_meta(prefix_dirs=[
                Path("/nonexistent_a.json"),
                Path("/nonexistent_b.json"),
            ])


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
# 15. Endpoint surface – no unexpected routes
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
    ]

    REMOVED_OLD_ROUTES = [
        ("POST",  "/fix2"),       # was only in nothit
    ]

    @pytest.mark.parametrize("method,path", EXPECTED_ROUTES)
    def test_expected_route_is_not_404(self, method, path):
        # /status/{handle} is a valid route but will legitimately return 404
        # for an unknown handle.  Patch the task lookup so it returns data.
        with patch.object(api, "get_task_from_redis",
                          return_value={"status": "queued"}):
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

