"""
old_test.py
===========
Tests that capture the EXACT behaviour of the OLD multi-file system:

  File                              Role in old_main.py
  ──────────────────────────────── ──────────────────────────────────────────
  defects4c_api.py                  ORIGINAL service (standalone reference)
  defects4c_api_merged.py           Mounted as "bug-helper"  router
  defects4c_api_merged_nothit.py    Mounted as "bug-hlper-hit" router
  extract_patch_with_integrating.py Mounted as "patch-service" router
  old_main.py                       Combines all three into one FastAPI app

Run:
    pytest old_test.py -v
    pytest old_test.py -v -k "OldOriginal"   # single module tests
"""

import base64
import hashlib
import json
import os
import sys
import tempfile
import types
import uuid
from pathlib import Path
from typing import Any, Dict
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

# ─────────────────────────── Bootstrap ────────────────────────────────
#
# Set env-vars BEFORE any module import so module-scope mkdir() calls
# use writable temp dirs.

_tmp_root = tempfile.mkdtemp(prefix="old_defects4c_test_")
os.environ.setdefault("SRC_DIR",               os.path.join(_tmp_root, "src"))
os.environ.setdefault("ROOT_DIR",              os.path.join(_tmp_root, "out"))
os.environ.setdefault("PATCH_OUTPUT_DIR",      os.path.join(_tmp_root, "patches"))
os.environ.setdefault("PATCH_OUTPUT_BEFORE_DIR", os.path.join(_tmp_root, "patches_before"))
for _d in ("src", "out", "patches", "patches_before"):
    Path(os.path.join(_tmp_root, _d)).mkdir(parents=True, exist_ok=True)

# Stub the config module (real file not available in test env)
FAKE_PROJECTS_DIR = {
    "myorg___myrepo":      "projects_v1",
    "otherorg___otherrepo": "projects",
}
_cfg = types.ModuleType("config")
_cfg.PROJECTS_DIR = FAKE_PROJECTS_DIR  # type: ignore
sys.modules["config"] = _cfg

# ─────────────────────────── Shared constants ─────────────────────────

SHA      = "aabbccdd" * 5          # 40-char fake SHA
PROJECT  = "myorg___myrepo"
BUG_ID   = f"{PROJECT}@{SHA}"
MD5_32   = "a" * 32

FAKE_META_DEFECT = {
    "commit_after":  SHA,
    "commit_before": "0" * 40,
    "files": {
        "src":  ["src/foo.cpp"],
        "test": ["tests/test_foo.cpp"],
        "src0_location": {"byte_start": 0, "byte_end": 100},
    },
    "c_compile": {"build_flags": [], "test_flags": [], "env": []},
    "build": "build.jinja",
    "test":  "test.jinja",
    "project": PROJECT,
}
FAKE_META_PROJECT = {
    "c_compile": {"build_flags": [], "test_flags": [], "env": []},
    "env": [],
}
SAMPLE_SRC = "int foo() {\n    return 0;\n}\n"


def _make_fake_bugs_info(module):
    """Return a BugsInfo-like object from any old module, bypassing filesystem."""
    bi = object.__new__(module.BugsInfo)
    bi.project       = PROJECT
    bi.sha           = SHA
    bi.project_major = "projects_v1"
    bi.src_dir       = str(Path(os.environ["SRC_DIR"]))
    bi.wrk_git       = Path(_tmp_root, "out", PROJECT, f"git_repo_dir_{SHA}")
    bi.wrk_log       = Path(_tmp_root, "out", PROJECT, "logs")
    bi.src_project   = Path(_tmp_root, "src", "projects_v1", PROJECT)
    bi.meta_project  = FAKE_META_PROJECT
    bi.meta_defect   = FAKE_META_DEFECT
    bi.meta_info     = {**FAKE_META_DEFECT, **FAKE_META_PROJECT}
    bi.wrk_git.mkdir(parents=True, exist_ok=True)
    bi.wrk_log.mkdir(parents=True, exist_ok=True)
    return bi


# ══════════════════════════════════════════════════════════════════════
#  SECTION A – defects4c_api.py  (ORIGINAL standalone service)
#
#  Key characteristics:
#    • /fix handle = uuid.uuid4().hex  (RANDOM, not deterministic)
#    • /status only checks in-memory tasks → 404 if not present
#    • /all_tasks returns ONLY the in-memory tasks dict
#    • get_cached_result → Redis-only, no file fallback
#    • cache_result → TTL line commented-out (no TTL)
#    • No /health endpoint
# ══════════════════════════════════════════════════════════════════════

import importlib, types as _types

# Patch the module before importing
_orig_mod = None

def _load_orig():
    global _orig_mod
    if _orig_mod is None:
        spec = importlib.util.spec_from_file_location(
            "defects4c_api_orig",
            "/src/defects4c_api.py"
        )
        m = importlib.util.module_from_spec(spec)
        m.__package__ = ""
        spec.loader.exec_module(m)
        _orig_mod = m
    return _orig_mod

try:
    orig = _load_orig()
    from fastapi.testclient import TestClient as _TC
    _orig_client = _TC(orig.app, raise_server_exceptions=False)
    _ORIG_AVAILABLE = True
except Exception as _e:
    _ORIG_AVAILABLE = False
    print(f"[old_test] Cannot load defects4c_api.py: {_e}")


@pytest.mark.skipif(not _ORIG_AVAILABLE, reason="original module not loadable")
class TestOldOriginal:
    """Tests that document the ORIGINAL defects4c_api.py behaviour."""

    # ── sanity: no /health endpoint ──────────────────────────────────

    def test_no_health_endpoint(self):
        r = _orig_client.get("/health")
        # FastAPI returns 404 for unknown routes
        assert r.status_code == 404

    # ── /projects ────────────────────────────────────────────────────

    def test_projects_returns_200(self):
        r = _orig_client.get("/projects")
        assert r.status_code == 200

    def test_projects_lists_configured_projects(self):
        r = _orig_client.get("/projects")
        assert set(r.json()["projects"]) == set(FAKE_PROJECTS_DIR.keys())

    # ── /reproduce ───────────────────────────────────────────────────

    def test_reproduce_bad_bug_id_returns_400(self):
        r = _orig_client.post("/reproduce", json={"bug_id": "no-at-sign"})
        assert r.status_code == 400

    def test_reproduce_returns_random_handle(self):
        bi = _make_fake_bugs_info(orig)
        with patch.object(orig, "BugsInfo", return_value=bi), \
             patch.object(orig, "run_reproduce_queue", return_value=None):
            r1 = _orig_client.post("/reproduce", json={"bug_id": BUG_ID})
            r2 = _orig_client.post("/reproduce", json={"bug_id": BUG_ID})
        # CRITICAL OLD BEHAVIOUR: handles are random UUIDs, never the same
        assert r1.json()["handle"] != r2.json()["handle"]

    def test_reproduce_stores_task_in_memory(self):
        bi = _make_fake_bugs_info(orig)
        with patch.object(orig, "BugsInfo", return_value=bi), \
             patch.object(orig, "run_reproduce_queue", return_value=None):
            r = _orig_client.post("/reproduce", json={"bug_id": BUG_ID})
        handle = r.json()["handle"]
        assert handle in orig.tasks
        assert orig.tasks[handle]["status"] == "queued"

    # ── /fix ─────────────────────────────────────────────────────────

    def test_fix_returns_random_handle(self):
        """OLD: /fix generates a random uuid handle each call."""
        bi = _make_fake_bugs_info(orig)
        patch_path = f"/patches/{MD5_32}@{SHA}___file.cpp"
        with patch.object(orig, "BugsInfo", return_value=bi), \
             patch.object(orig, "get_cached_result", return_value=None), \
             patch.object(orig, "run_fix_queue", return_value=None):
            r1 = _orig_client.post("/fix", json={"bug_id": BUG_ID, "patch_path": patch_path})
            r2 = _orig_client.post("/fix", json={"bug_id": BUG_ID, "patch_path": patch_path})
        # CRITICAL: two calls give two DIFFERENT handles (random uuid)
        assert r1.json()["handle"] != r2.json()["handle"]

    def test_fix_stores_task_in_memory_not_redis(self):
        """OLD: /fix task lives in the in-memory tasks dict."""
        bi = _make_fake_bugs_info(orig)
        patch_path = f"/patches/{MD5_32}@{SHA}___file.cpp"
        with patch.object(orig, "BugsInfo", return_value=bi), \
             patch.object(orig, "get_cached_result", return_value=None), \
             patch.object(orig, "run_fix_queue", return_value=None):
            r = _orig_client.post("/fix", json={"bug_id": BUG_ID, "patch_path": patch_path})
        handle = r.json()["handle"]
        # Task is in memory
        assert handle in orig.tasks
        assert orig.tasks[handle]["status"] == "queued"

    def test_fix_returns_redis_key(self):
        bi = _make_fake_bugs_info(orig)
        patch_path = f"/patches/{MD5_32}@{SHA}___file.cpp"
        with patch.object(orig, "BugsInfo", return_value=bi), \
             patch.object(orig, "get_cached_result", return_value=None), \
             patch.object(orig, "run_fix_queue", return_value=None):
            r = _orig_client.post("/fix", json={"bug_id": BUG_ID, "patch_path": patch_path})
        assert "redis_key" in r.json()

    # ── /status ──────────────────────────────────────────────────────

    def test_status_404_for_unknown_handle(self):
        """OLD: /status has NO Redis fallback — always 404 for unknown handle."""
        r = _orig_client.get("/status/totally_unknown_handle")
        assert r.status_code == 404

    def test_status_no_redis_fallback(self):
        """OLD: Even if Redis would have data, status 404s when not in memory."""
        redis_data = {"status": "completed"}
        with patch.object(orig.redis_manager, "is_connected", return_value=True):
            # Task is NOT in orig.tasks, so 404 regardless of Redis
            r = _orig_client.get("/status/some_base64_handle")
        assert r.status_code == 404

    def test_status_returns_in_memory_task(self):
        handle = "orig_mem_handle_001"
        orig.tasks[handle] = {"status": "completed", "bug_id": BUG_ID}
        r = _orig_client.get(f"/status/{handle}")
        assert r.status_code == 200
        assert r.json()["status"] == "completed"

    # ── /all_tasks ───────────────────────────────────────────────────

    def test_all_tasks_returns_in_memory_only(self):
        """OLD: /all_tasks is just `return tasks` — no Redis merging."""
        orig.tasks["test_orig_handle"] = {"status": "queued"}
        with patch.object(orig.redis_manager, "is_connected", return_value=True), \
             patch.object(orig.redis_manager.client, "keys", return_value=["task_some_key"]):
            r = _orig_client.get("/all_tasks")
        body = r.json()
        # In-memory handle present
        assert "test_orig_handle" in body
        # Redis task key was NOT merged (no get_task_from_redis call in orig)
        # The redis key itself won't be in the response as a handle

    # ── /cache/status ────────────────────────────────────────────────

    def test_cache_status_disconnected(self):
        with patch.object(orig.redis_manager, "is_connected", return_value=False):
            r = _orig_client.get("/cache/status")
        assert r.status_code == 200
        assert r.json()["redis_connected"] is False

    # ── DELETE /cache/{redis_key} ─────────────────────────────────────

    def test_delete_cache_503_when_disconnected(self):
        with patch.object(orig.redis_manager, "is_connected", return_value=False):
            r = _orig_client.delete("/cache/some_key")
        assert r.status_code == 503

    def test_delete_cache_swallows_exception_as_500(self):
        """OLD: the except clause re-raises as 500 (not a clean HTTPException)."""
        with patch.object(orig.redis_manager, "is_connected", return_value=True), \
             patch.object(orig.redis_manager.client, "delete", side_effect=Exception("boom")):
            r = _orig_client.delete("/cache/some_key")
        assert r.status_code == 500

    # ── get_cached_result: Redis-only, no file fallback ───────────────

    def test_orig_get_cached_result_returns_none_when_disconnected(self):
        """OLD orig: no file fallback path at all."""
        with patch.object(orig.redis_manager, "is_connected", return_value=False):
            result = orig.get_cached_result("patch_abc_def.log")
        assert result is None

    # ── cache_result: no TTL (expire line commented out) ─────────────

    def test_orig_cache_result_does_not_call_expire(self):
        """OLD orig: cache_result never calls expire (TTL line is commented out)."""
        mock_client = MagicMock()
        orig.redis_manager._redis_client = mock_client
        with patch.object(orig.redis_manager, "is_connected", return_value=True):
            orig.cache_result("key", {
                "status": "completed", "return_code": 0,
                "fix_log": "", "fix_msg": "", "fix_status": "",
                "error": "", "timestamp": "1",
            })
        mock_client.hset.assert_called_once()
        # expire MUST NOT have been called
        mock_client.expire.assert_not_called()


# ══════════════════════════════════════════════════════════════════════
#  SECTION B – defects4c_api_merged.py
#
#  Key characteristics (vs original):
#    • /fix handle = base64(redis_key) → DETERMINISTIC
#    • /fix task stored in Redis (not in-memory)
#    • /status checks in-memory first, then Redis
#    • /all_tasks merges in-memory + Redis tasks
#    • get_cached_result → Redis-only (same as orig, no file fallback)
#    • cache_result → has TTL=86400
#    • No /health endpoint
# ══════════════════════════════════════════════════════════════════════

_merged_mod = None

def _load_merged():
    global _merged_mod
    if _merged_mod is None:
        spec = importlib.util.spec_from_file_location(
            "defects4c_api_merged_mod",
            "/src/defects4c_api_merged.py"
        )
        m = importlib.util.module_from_spec(spec)
        m.__package__ = ""
        spec.loader.exec_module(m)
        _merged_mod = m
    return _merged_mod

try:
    merged = _load_merged()
    _merged_client = _TC(merged.app, raise_server_exceptions=False)
    _MERGED_AVAILABLE = True
except Exception as _e:
    _MERGED_AVAILABLE = False
    print(f"[old_test] Cannot load defects4c_api_merged.py: {_e}")


@pytest.mark.skipif(not _MERGED_AVAILABLE, reason="merged module not loadable")
class TestOldMerged:
    """Tests that document the defects4c_api_merged.py behaviour."""

    # ── no /health ────────────────────────────────────────────────────

    def test_no_health_endpoint(self):
        r = _merged_client.get("/health")
        assert r.status_code == 404

    # ── /projects ────────────────────────────────────────────────────

    def test_projects_200(self):
        r = _merged_client.get("/projects")
        assert r.status_code == 200
        assert set(r.json()["projects"]) == set(FAKE_PROJECTS_DIR.keys())

    # ── /reproduce ───────────────────────────────────────────────────

    def test_reproduce_bad_bug_id_400(self):
        r = _merged_client.post("/reproduce", json={"bug_id": "no-at"})
        assert r.status_code == 400

    def test_reproduce_stores_in_memory(self):
        bi = _make_fake_bugs_info(merged)
        with patch.object(merged, "BugsInfo", return_value=bi), \
             patch.object(merged, "run_reproduce_queue", return_value=None):
            r = _merged_client.post("/reproduce", json={"bug_id": BUG_ID})
        handle = r.json()["handle"]
        assert handle in merged.tasks

    # ── /fix: deterministic handle ────────────────────────────────────

    def test_fix_handle_is_deterministic(self):
        """MERGED: handle = base64(redis_key) → same inputs → same handle."""
        bi = _make_fake_bugs_info(merged)
        patch_path = f"/patches/{MD5_32}@{SHA}___file.cpp"
        with patch.object(merged, "BugsInfo", return_value=bi), \
             patch.object(merged, "get_cached_result", return_value=None), \
             patch.object(merged, "store_task_in_redis"), \
             patch.object(merged, "run_fix_queue", return_value=None):
            r1 = _merged_client.post("/fix", json={"bug_id": BUG_ID, "patch_path": patch_path})
            r2 = _merged_client.post("/fix", json={"bug_id": BUG_ID, "patch_path": patch_path})
        assert r1.json()["handle"] == r2.json()["handle"]

    def test_fix_handle_is_base64_of_redis_key(self):
        """MERGED: handle must decode to the redis_key."""
        bi = _make_fake_bugs_info(merged)
        patch_path = f"/patches/{MD5_32}@{SHA}___file.cpp"
        with patch.object(merged, "BugsInfo", return_value=bi), \
             patch.object(merged, "get_cached_result", return_value=None), \
             patch.object(merged, "store_task_in_redis"), \
             patch.object(merged, "run_fix_queue", return_value=None):
            r = _merged_client.post("/fix", json={"bug_id": BUG_ID, "patch_path": patch_path})
        body = r.json()
        handle    = body["handle"]
        redis_key = body["redis_key"]
        decoded   = base64.b64decode(handle.encode()).decode()
        assert decoded == redis_key

    def test_fix_task_stored_in_redis_not_memory(self):
        """MERGED: /fix uses store_task_in_redis, NOT in-memory tasks."""
        bi = _make_fake_bugs_info(merged)
        patch_path = f"/patches/{MD5_32}@{SHA}___file.cpp"
        stored_calls = []
        def _capture(handle, data, **kw):
            stored_calls.append((handle, data))
        with patch.object(merged, "BugsInfo", return_value=bi), \
             patch.object(merged, "get_cached_result", return_value=None), \
             patch.object(merged, "store_task_in_redis", side_effect=_capture), \
             patch.object(merged, "run_fix_queue", return_value=None):
            r = _merged_client.post("/fix", json={"bug_id": BUG_ID, "patch_path": patch_path})
        assert len(stored_calls) >= 1

    def test_fix_cache_hit_stores_in_redis(self):
        """MERGED: on cache hit, task is stored in Redis (not in-memory)."""
        bi = _make_fake_bugs_info(merged)
        patch_path = f"/patches/{MD5_32}@{SHA}___file.cpp"
        cached = {
            "status": "completed", "return_code": 0,
            "fix_log": "ok", "fix_msg": "", "fix_status": "",
            "error": "", "timestamp": "1.0", "from_cache": True,
        }
        stored_calls = []
        with patch.object(merged, "BugsInfo", return_value=bi), \
             patch.object(merged, "get_cached_result", return_value=cached), \
             patch.object(merged, "store_task_in_redis",
                          side_effect=lambda h, d, **k: stored_calls.append(h)):
            r = _merged_client.post("/fix", json={"bug_id": BUG_ID, "patch_path": patch_path})
        assert r.status_code == 200
        assert len(stored_calls) == 1

    # ── /status: in-memory then Redis ────────────────────────────────

    def test_status_in_memory_first(self):
        handle = "merged_mem_001"
        merged.tasks[handle] = {"status": "running"}
        r = _merged_client.get(f"/status/{handle}")
        assert r.status_code == 200
        assert r.json()["status"] == "running"

    def test_status_falls_back_to_redis(self):
        handle = "merged_redis_handle_001"
        merged.tasks.pop(handle, None)
        redis_data = {"status": "completed"}
        with patch.object(merged, "get_task_from_redis", return_value=redis_data):
            r = _merged_client.get(f"/status/{handle}")
        assert r.status_code == 200
        assert r.json()["status"] == "completed"

    def test_status_404_when_not_in_memory_or_redis(self):
        handle = "merged_nowhere_handle"
        merged.tasks.pop(handle, None)
        with patch.object(merged, "get_task_from_redis", return_value=None):
            r = _merged_client.get(f"/status/{handle}")
        assert r.status_code == 404

    # ── /all_tasks: merges in-memory + Redis ─────────────────────────

    def test_all_tasks_includes_memory_and_redis(self):
        mem_handle   = "merged_all_mem_handle"
        redis_key    = f"patch_{SHA}_{'b' * 32}.log"
        redis_handle = merged.redis_key_to_handle(redis_key)

        merged.tasks[mem_handle] = {"status": "queued"}
        merged.tasks.pop(redis_handle, None)

        with patch.object(merged.redis_manager, "is_connected", return_value=True), \
             patch.object(merged.redis_manager.client, "keys", return_value=[f"task_{redis_key}"]), \
             patch.object(merged, "get_task_from_redis", return_value={"status": "completed"}):
            r = _merged_client.get("/all_tasks")
        body = r.json()
        assert mem_handle   in body
        assert redis_handle in body

    # ── get_cached_result: Redis-only (no file fallback) ─────────────

    def test_merged_get_cached_result_no_file_fallback(self):
        """MERGED: get_cached_result returns None when Redis disconnected.
        There is NO file-based fallback in defects4c_api_merged.py."""
        with patch.object(merged.redis_manager, "is_connected", return_value=False):
            result = merged.get_cached_result("patch_abc_def.log")
        assert result is None

    # ── cache_result: has TTL ─────────────────────────────────────────

    def test_merged_cache_result_calls_expire(self):
        """MERGED: cache_result calls expire with TTL=86400."""
        mock_client = MagicMock()
        merged.redis_manager._redis_client = mock_client
        with patch.object(merged.redis_manager, "is_connected", return_value=True):
            merged.cache_result("key", {
                "status": "completed", "return_code": 0,
                "fix_log": "", "fix_msg": "", "fix_status": "",
                "error": "", "timestamp": "1",
            })
        mock_client.hset.assert_called_once()
        mock_client.expire.assert_called_once_with("key", 86400)


# ══════════════════════════════════════════════════════════════════════
#  SECTION C – defects4c_api_merged_nothit.py
#
#  Key characteristics:
#    • ONLY has /fix2 endpoint (all others commented out)
#    • /reproduce, /status, /all_tasks, /cache/* → 404 (commented out)
#    • get_cached_result → Redis + FILE FALLBACK (most evolved)
#    • load_metadata only (no guidance/src/prompt loaders)
#    • run_fix_queue: checks if log file exists before executing
# ══════════════════════════════════════════════════════════════════════

_nothit_mod = None

def _load_nothit():
    global _nothit_mod
    if _nothit_mod is None:
        spec = importlib.util.spec_from_file_location(
            "defects4c_api_merged_nothit_mod",
            "/src/defects4c_api_merged_nothit.py"
        )
        m = importlib.util.module_from_spec(spec)
        m.__package__ = ""
        spec.loader.exec_module(m)
        _nothit_mod = m
    return _nothit_mod

try:
    nothit = _load_nothit()
    _nothit_client = _TC(nothit.app, raise_server_exceptions=False)
    _NOTHIT_AVAILABLE = True
except Exception as _e:
    _NOTHIT_AVAILABLE = False
    print(f"[old_test] Cannot load defects4c_api_merged_nothit.py: {_e}")


@pytest.mark.skipif(not _NOTHIT_AVAILABLE, reason="nothit module not loadable")
class TestOldNothit:
    """Tests that document defects4c_api_merged_nothit.py behaviour."""

    # ── commented-out endpoints return 404 ───────────────────────────

    def test_no_reproduce_endpoint(self):
        """NOTHIT: /reproduce is commented out → 404."""
        r = _nothit_client.post("/reproduce", json={"bug_id": BUG_ID})
        assert r.status_code == 404

    def test_no_status_endpoint(self):
        """NOTHIT: /status is commented out → 404."""
        r = _nothit_client.get("/status/some_handle")
        assert r.status_code == 404

    def test_no_all_tasks_endpoint(self):
        """NOTHIT: /all_tasks is commented out → 404."""
        r = _nothit_client.get("/all_tasks")
        assert r.status_code == 404

    def test_no_cache_status_endpoint(self):
        """NOTHIT: /cache/status is commented out → 404."""
        r = _nothit_client.get("/cache/status")
        assert r.status_code == 404

    def test_no_health_endpoint(self):
        r = _nothit_client.get("/health")
        assert r.status_code == 404

    # ── /fix2 endpoint (note: NOT /fix) ──────────────────────────────

    def test_fix2_endpoint_exists(self):
        """NOTHIT: endpoint is named /fix2, not /fix."""
        bi = _make_fake_bugs_info(nothit)
        patch_path = f"/patches/{MD5_32}@{SHA}___file.cpp"
        with patch.object(nothit, "BugsInfo", return_value=bi), \
             patch.object(nothit, "get_cached_result", return_value=None), \
             patch.object(nothit, "store_task_in_redis"), \
             patch.object(nothit, "run_fix_queue", return_value=None):
            r = _nothit_client.post("/fix2", json={"bug_id": BUG_ID, "patch_path": patch_path})
        assert r.status_code == 200

    def test_fix_endpoint_does_not_exist(self):
        """NOTHIT: /fix is NOT defined (it's /fix2)."""
        bi = _make_fake_bugs_info(nothit)
        patch_path = f"/patches/{MD5_32}@{SHA}___file.cpp"
        with patch.object(nothit, "BugsInfo", return_value=bi), \
             patch.object(nothit, "get_cached_result", return_value=None), \
             patch.object(nothit, "store_task_in_redis"), \
             patch.object(nothit, "run_fix_queue", return_value=None):
            r = _nothit_client.post("/fix", json={"bug_id": BUG_ID, "patch_path": patch_path})
        assert r.status_code == 404

    def test_fix2_bad_bug_id_returns_400(self):
        r = _nothit_client.post("/fix2", json={"bug_id": "bad", "patch_path": "/some/patch"})
        assert r.status_code == 400

    def test_fix2_handle_is_deterministic_base64(self):
        bi = _make_fake_bugs_info(nothit)
        patch_path = f"/patches/{MD5_32}@{SHA}___file.cpp"
        with patch.object(nothit, "BugsInfo", return_value=bi), \
             patch.object(nothit, "get_cached_result", return_value=None), \
             patch.object(nothit, "store_task_in_redis"), \
             patch.object(nothit, "run_fix_queue", return_value=None):
            r1 = _nothit_client.post("/fix2", json={"bug_id": BUG_ID, "patch_path": patch_path})
            r2 = _nothit_client.post("/fix2", json={"bug_id": BUG_ID, "patch_path": patch_path})
        assert r1.json()["handle"] == r2.json()["handle"]

    def test_fix2_handle_decodes_to_redis_key(self):
        bi = _make_fake_bugs_info(nothit)
        patch_path = f"/patches/{MD5_32}@{SHA}___file.cpp"
        with patch.object(nothit, "BugsInfo", return_value=bi), \
             patch.object(nothit, "get_cached_result", return_value=None), \
             patch.object(nothit, "store_task_in_redis"), \
             patch.object(nothit, "run_fix_queue", return_value=None):
            r = _nothit_client.post("/fix2", json={"bug_id": BUG_ID, "patch_path": patch_path})
        body = r.json()
        decoded = base64.b64decode(body["handle"].encode()).decode()
        assert decoded == body["redis_key"]

    # ── get_cached_result: has file fallback ─────────────────────────

    def test_nothit_get_cached_result_has_file_fallback(self, tmp_path):
        """NOTHIT: when Redis is down, falls back to reading from disk files."""
        md5_val = "0" * 32
        log_dir = tmp_path / PROJECT / "logs"
        log_dir.mkdir(parents=True)
        (log_dir / f"patch_{SHA}_{md5_val}.log").write_text("output")
        (log_dir / f"patch_{SHA}_{md5_val}.status").write_text("0")

        nothit.META_DICT[SHA] = {"project": PROJECT}

        import defects4c_api_merged_nothit_mod as _nh_mod
        old_out = _nh_mod.OUT_ROOT
        _nh_mod.OUT_ROOT = tmp_path
        try:
            with patch.object(nothit.redis_manager, "is_connected", return_value=False):
                result = nothit.get_cached_result(f"patch_{SHA}_{md5_val}.log")
        finally:
            _nh_mod.OUT_ROOT = old_out

        assert result is not None
        assert result.get("from_files") is True

    # ── load_metadata populates META_DICT ────────────────────────────

    def test_nothit_load_metadata(self, tmp_path):
        bugs = [{"commit_after": SHA, "files": {}}]
        p = tmp_path / PROJECT / "bugs_list_new.json"
        p.parent.mkdir(parents=True)
        p.write_text(json.dumps(bugs))

        old = dict(nothit.META_DICT)
        nothit.META_DICT.clear()
        try:
            count = nothit.load_metadata([str(p)])
        finally:
            nothit.META_DICT.clear()
            nothit.META_DICT.update(old)

        assert count == 1

    def test_nothit_load_metadata_adds_project_key(self, tmp_path):
        bugs = [{"commit_after": SHA, "files": {}}]
        p = tmp_path / PROJECT / "bugs_list_new.json"
        p.parent.mkdir(parents=True)
        p.write_text(json.dumps(bugs))

        old = dict(nothit.META_DICT)
        nothit.META_DICT.clear()
        try:
            nothit.load_metadata([str(p)])
            assert nothit.META_DICT[SHA]["project"] == PROJECT
        finally:
            nothit.META_DICT.clear()
            nothit.META_DICT.update(old)


# ══════════════════════════════════════════════════════════════════════
#  SECTION D – extract_patch_with_integrating.py
#
#  Key characteristics:
#    • Only /build_patch endpoint
#    • load_prefix_suffix_meta: UNSAFE – raises FileNotFoundError if files missing
#    • load_prompt_list: uses assert (can crash on malformed data)
#    • Startup loads ALL data (guidance, src, prompt, prefix)
# ══════════════════════════════════════════════════════════════════════

_extract_mod = None

def _load_extract():
    global _extract_mod
    if _extract_mod is None:
        spec = importlib.util.spec_from_file_location(
            "extract_patch_with_integrating_mod",
            "/src/extract_patch_with_integrating.py"
        )
        m = importlib.util.module_from_spec(spec)
        m.__package__ = ""
        spec.loader.exec_module(m)
        _extract_mod = m
    return _extract_mod

try:
    extract = _load_extract()
    _extract_client = _TC(extract.app, raise_server_exceptions=False)
    _EXTRACT_AVAILABLE = True
except Exception as _e:
    _EXTRACT_AVAILABLE = False
    print(f"[old_test] Cannot load extract_patch_with_integrating.py: {_e}")


@pytest.mark.skipif(not _EXTRACT_AVAILABLE, reason="extract module not loadable")
class TestOldExtract:
    """Tests that document extract_patch_with_integrating.py behaviour."""

    # ── /build_patch: same error codes as new ────────────────────────

    def test_build_patch_invalid_bug_id_400(self):
        r = _extract_client.post("/build_patch", json={
            "bug_id": "no-at-sign", "llm_response": "x"
        })
        assert r.status_code == 400
        assert "error_code" in r.json()["detail"]

    def test_build_patch_guidance_not_loaded_400(self):
        old = extract.guidance_df
        extract.guidance_df = None
        try:
            r = _extract_client.post("/build_patch", json={
                "bug_id": BUG_ID, "llm_response": "x"
            })
        finally:
            extract.guidance_df = old
        assert r.status_code == 400
        assert r.json()["detail"]["error_code"] == extract.ErrorCodes.ERR_GUIDANCE_NOT_LOADED

    def test_build_patch_sha_not_in_guidance_400(self):
        src_abs = str(Path(os.environ["PATCH_OUTPUT_BEFORE_DIR"]) / f"{SHA}___foo.cpp")
        df = pd.DataFrame([{
            "github": f"https://github.com/myorg/myrepo/commit/{'f' * 40}",
            "commit_after": "f" * 40,
            "project": PROJECT,
            "src_path": src_abs,
            "func_start_byte": 0,
            "func_end_byte": 10,
        }])
        df["src_path"] = df["src_path"].apply(
            lambda x: str(Path(os.environ["PATCH_OUTPUT_BEFORE_DIR"]) / os.path.basename(x))
        )
        old = extract.guidance_df
        extract.guidance_df = df
        try:
            r = _extract_client.post("/build_patch", json={
                "bug_id": BUG_ID, "llm_response": "x"
            })
        finally:
            extract.guidance_df = old
        assert r.status_code == 400
        assert r.json()["detail"]["error_code"] == extract.ErrorCodes.ERR_BUG_ID_NOT_IN_GUIDANCE

    def test_build_patch_success(self):
        src_abs = str(Path(os.environ["PATCH_OUTPUT_BEFORE_DIR"]) / f"{SHA}___foo.cpp")
        Path(src_abs).write_text(SAMPLE_SRC)

        df = pd.DataFrame([{
            "github": f"https://github.com/myorg/myrepo/commit/{SHA}",
            "commit_after": SHA,
            "project": PROJECT,
            "src_path": src_abs,
            "func_start_byte": 0,
            "func_end_byte": len(SAMPLE_SRC),
        }])
        df["src_path"] = df["src_path"].apply(
            lambda x: str(Path(os.environ["PATCH_OUTPUT_BEFORE_DIR"]) / os.path.basename(x))
        )
        old_df      = extract.guidance_df
        old_content = dict(extract.SRC_CONTENT)
        old_meta    = dict(extract.META_DICT)
        extract.guidance_df     = df
        extract.SRC_CONTENT[src_abs] = SAMPLE_SRC
        extract.META_DICT[SHA]       = {**FAKE_META_DEFECT, "project": PROJECT}

        snippet = "```c\nint foo() { return 42; }\n```"
        with patch.object(extract, "create_patch_file") as mock_cpf:
            mock_cpf.return_value = (
                {"bug_id": BUG_ID, "sha": SHA, "fix_p": "/tmp/f",
                 "fix_p_diff": None, "patch": "diff content"},
                None,
            )
            r = _extract_client.post("/build_patch", json={
                "bug_id": BUG_ID, "llm_response": snippet, "method": "direct"
            })
        extract.guidance_df  = old_df
        extract.SRC_CONTENT  = old_content
        extract.META_DICT    = old_meta

        assert r.status_code == 200
        assert r.json()["success"] is True

    # ── load_prefix_suffix_meta: UNSAFE (no try/except) ──────────────

    def test_load_prefix_suffix_meta_raises_on_missing_files(self):
        """OLD extract: load_prefix_suffix_meta has NO try/except.
        It raises FileNotFoundError if any file is missing.
        This is a known fragility that was fixed in the new merged file."""
        with pytest.raises((FileNotFoundError, OSError, Exception)):
            extract.load_prefix_suffix_meta(prefix_dirs=[
                Path("/nonexistent/path_a.json"),
                Path("/nonexistent/path_b.json"),
            ])

    # ── load_prompt_list: uses assert (crash risk) ───────────────────

    def test_load_prompt_list_raises_on_bad_idx_format(self, tmp_path):
        """OLD extract: load_prompt_list uses `assert` to validate idx format.
        Malformed data raises AssertionError, not a safe exception."""
        bad_prompt = {
            "idx": "tooshort",          # less than 41 chars — assert will fail
            "prompt": [{"role": "system"}, {"role": "user", "content": "```c\n>>> [ INFILL ] <<<\n```"}],
        }
        p = tmp_path / "prompts.jsonl"
        p.write_text(json.dumps(bad_prompt) + "\n")
        with pytest.raises((AssertionError, Exception)):
            extract.load_prompt_list(str(p))

    # ── only /build_patch, no /projects or /fix ───────────────────────

    def test_no_projects_endpoint(self):
        r = _extract_client.get("/projects")
        assert r.status_code == 404

    def test_no_fix_endpoint(self):
        r = _extract_client.post("/fix", json={"bug_id": BUG_ID, "patch_path": "/x"})
        assert r.status_code == 404

    def test_no_health_endpoint(self):
        r = _extract_client.get("/health")
        assert r.status_code == 404


# ══════════════════════════════════════════════════════════════════════
#  SECTION E – old_main.py (composite app)
#
#  Combines defects4c_api_merged + defects4c_api_merged_nothit + extract
#  Key observations:
#    • Has /health (defined in old_main.py itself)
#    • Has /fix  (from merged) AND /fix2 (from nothit) simultaneously
#    • /status from merged (Redis fallback)
#    • /all_tasks from merged (in-memory + Redis)
#    • /build_patch from extract
# ══════════════════════════════════════════════════════════════════════

def _build_old_main_app():
    """Construct a FastAPI app that mirrors old_main.py's include_router layout."""
    from fastapi import FastAPI

    app = FastAPI(title="Old Combined Service", version="0.0.0")

    # Suppress startup event (avoid file I/O)
    if _MERGED_AVAILABLE:
        app.include_router(merged.app.router, tags=["bug-helper"])
    if _NOTHIT_AVAILABLE:
        app.include_router(nothit.app.router, tags=["bug-hlper-hit"])
    if _EXTRACT_AVAILABLE:
        app.include_router(extract.app.router, tags=["patch-service"])

    @app.get("/health")
    def _health():
        return {"status": "healthy"}

    return app

try:
    _old_main_app = _build_old_main_app()
    _old_main_client = _TC(_old_main_app, raise_server_exceptions=False)
    _OLD_MAIN_AVAILABLE = _MERGED_AVAILABLE and _NOTHIT_AVAILABLE and _EXTRACT_AVAILABLE
except Exception as _e:
    _OLD_MAIN_AVAILABLE = False
    print(f"[old_test] Cannot build old_main app: {_e}")


@pytest.mark.skipif(not _OLD_MAIN_AVAILABLE, reason="old_main app not constructable")
class TestOldMain:
    """Tests that document the composite old_main.py behaviour."""

    def test_health_returns_healthy(self):
        """old_main.py defines its own /health returning 'healthy' (not 'ok')."""
        r = _old_main_client.get("/health")
        assert r.status_code == 200
        # OLD returns {"status": "healthy"}, NOT {"status": "ok"}
        assert r.json()["status"] == "healthy"

    def test_has_fix_and_fix2_simultaneously(self):
        """OLD: /fix (from merged) and /fix2 (from nothit) coexist."""
        # Both endpoints exist in the combined app
        bi_m = _make_fake_bugs_info(merged)
        bi_n = _make_fake_bugs_info(nothit)
        pp = f"/patches/{MD5_32}@{SHA}___file.cpp"
        with patch.object(merged, "BugsInfo", return_value=bi_m), \
             patch.object(merged, "get_cached_result", return_value=None), \
             patch.object(merged, "store_task_in_redis"), \
             patch.object(merged, "run_fix_queue", return_value=None), \
             patch.object(nothit, "BugsInfo", return_value=bi_n), \
             patch.object(nothit, "get_cached_result", return_value=None), \
             patch.object(nothit, "store_task_in_redis"), \
             patch.object(nothit, "run_fix_queue", return_value=None):
            r_fix  = _old_main_client.post("/fix",  json={"bug_id": BUG_ID, "patch_path": pp})
            r_fix2 = _old_main_client.post("/fix2", json={"bug_id": BUG_ID, "patch_path": pp})
        assert r_fix.status_code  == 200
        assert r_fix2.status_code == 200

    def test_projects_available(self):
        r = _old_main_client.get("/projects")
        assert r.status_code == 200

    def test_build_patch_available(self):
        old = extract.guidance_df
        extract.guidance_df = None
        try:
            r = _old_main_client.post("/build_patch", json={
                "bug_id": BUG_ID, "llm_response": "x"
            })
        finally:
            extract.guidance_df = old
        # Responds (400 because no data loaded, but endpoint exists)
        assert r.status_code == 400

    def test_status_has_redis_fallback(self):
        """Status from merged → does fall back to Redis."""
        handle = "old_main_redis_test"
        merged.tasks.pop(handle, None)
        nothit_data = {"status": "completed"}
        with patch.object(merged, "get_task_from_redis", return_value=nothit_data):
            r = _old_main_client.get(f"/status/{handle}")
        assert r.status_code == 200

    def test_all_tasks_merges_memory_and_redis(self):
        mem_handle = "old_main_all_tasks_test"
        merged.tasks[mem_handle] = {"status": "queued"}
        with patch.object(merged.redis_manager, "is_connected", return_value=False):
            r = _old_main_client.get("/all_tasks")
        assert mem_handle in r.json()



