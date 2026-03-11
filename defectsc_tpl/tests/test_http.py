"""
test_defects4c_api.py
=====================
Unit tests for defects4c_api.py using FastAPI's TestClient.

Run with:
    pytest test_defects4c_api.py -v
    pytest test_defects4c_api.py -v -k "health"       # single group
    pytest test_defects4c_api.py -v --tb=short
"""

import base64
import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any, Dict
from unittest.mock import MagicMock, patch, PropertyMock

import pandas as pd
import pytest
from fastapi.testclient import TestClient

# ─────────────────────────────────────────────────────────────────────
# Bootstrap: set env-vars BEFORE importing the module so that the
# mkdir() calls in module-scope use writable temp directories.
# ─────────────────────────────────────────────────────────────────────
import sys

_tmp_root = tempfile.mkdtemp(prefix="defects4c_test_")
os.environ.setdefault("SRC_DIR",               os.path.join(_tmp_root, "src"))
os.environ.setdefault("ROOT_DIR",              os.path.join(_tmp_root, "out"))
os.environ.setdefault("PATCH_OUTPUT_DIR",      os.path.join(_tmp_root, "patches"))
os.environ.setdefault("PATCH_OUTPUT_BEFORE_DIR", os.path.join(_tmp_root, "patches_before"))
for d in ("src", "out", "patches", "patches_before"):
    Path(os.path.join(_tmp_root, d)).mkdir(parents=True, exist_ok=True)

# Stub out the config module so we don't need the real file
FAKE_PROJECTS_DIR = {
    "myorg___myrepo": "projects_v1",
    "otherorg___otherrepo": "projects",
}
sys.modules["config"] = type(sys)("config")
sys.modules["config"].PROJECTS_DIR = FAKE_PROJECTS_DIR  # type: ignore

import defects4c_api as api  # noqa: E402  (must come after env + stub)

client = TestClient(api.app, raise_server_exceptions=False)

# ─────────────────────────────────────────────────────────────────────
# Shared test fixtures / helpers
# ─────────────────────────────────────────────────────────────────────

SHA   = "aabbccdd" * 5          # 40-char fake SHA
SHA2  = "11223344" * 5
PROJECT = "myorg___myrepo"
BUG_ID  = f"{PROJECT}@{SHA}"

FAKE_PATCH_PATH = f"/patches/{PROJECT}/{hashlib.md5(b'x').hexdigest()}@{SHA}___foo.cpp"

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

SAMPLE_SRC = "int foo() {\n    return 0;\n}\n"


def _redis_key(sha: str, patch_path: str) -> str:
    md5 = api.extract_patch_md5(patch_path)
    return f"patch_{sha}_{md5}.log"


def _handle(redis_key: str) -> str:
    return base64.b64encode(redis_key.encode()).decode()


def _make_bugs_info() -> api.BugsInfo:
    """Return a BugsInfo with all filesystem access bypassed."""
    bi = object.__new__(api.BugsInfo)
    bi.project       = PROJECT
    bi.sha           = SHA
    bi.project_major = "projects_v1"
    bi.src_dir       = str(api.SRC_ROOT)
    bi.wrk_git       = Path(os.path.join(_tmp_root, "out", PROJECT, f"git_repo_dir_{SHA}"))
    bi.wrk_log       = Path(os.path.join(_tmp_root, "out", PROJECT, "logs"))
    bi.src_project   = Path(os.path.join(_tmp_root, "src", "projects_v1", PROJECT))
    bi.meta_project  = FAKE_META_PROJECT
    bi.meta_defect   = FAKE_META_DEFECT
    bi.meta_info     = {**FAKE_META_DEFECT, **FAKE_META_PROJECT}
    bi.wrk_git.mkdir(parents=True, exist_ok=True)
    bi.wrk_log.mkdir(parents=True, exist_ok=True)
    return bi


# ═════════════════════════════════════════════════════════════════════
# 1.  /health
# ═════════════════════════════════════════════════════════════════════

class TestHealth:
    def test_returns_200(self):
        r = client.get("/health")
        assert r.status_code == 200

    def test_returns_ok(self):
        r = client.get("/health")
        assert r.json() == {"status": "ok"}


# ═════════════════════════════════════════════════════════════════════
# 2.  /projects
# ═════════════════════════════════════════════════════════════════════

class TestProjects:
    def test_returns_200(self):
        r = client.get("/projects")
        assert r.status_code == 200

    def test_lists_all_projects(self):
        r = client.get("/projects")
        body = r.json()
        assert "projects" in body
        assert set(body["projects"]) == set(FAKE_PROJECTS_DIR.keys())


# ═════════════════════════════════════════════════════════════════════
# 3.  /reproduce
# ═════════════════════════════════════════════════════════════════════

class TestReproduce:
    def test_bad_bug_id_format_returns_400(self):
        r = client.post("/reproduce", json={"bug_id": "no-at-sign"})
        assert r.status_code == 400

    def test_unknown_project_returns_400(self):
        r = client.post("/reproduce", json={"bug_id": "unknown___proj@deadbeef"})
        assert r.status_code == 400

    def test_queues_task_and_returns_handle(self):
        bi = _make_bugs_info()
        with patch.object(api, "BugsInfo", return_value=bi), \
             patch.object(api, "run_reproduce_queue", return_value=None):
            r = client.post("/reproduce", json={"bug_id": BUG_ID})
        assert r.status_code == 200
        body = r.json()
        assert "handle" in body
        handle = body["handle"]
        assert handle in api.tasks
        assert api.tasks[handle]["status"] == "queued"
        assert api.tasks[handle]["bug_id"] == BUG_ID

    def test_force_cleanup_default_true(self):
        bi = _make_bugs_info()
        with patch.object(api, "BugsInfo", return_value=bi), \
             patch.object(api, "run_reproduce_queue", return_value=None):
            r = client.post("/reproduce", json={"bug_id": BUG_ID})
        handle = r.json()["handle"]
        assert api.tasks[handle]["force_cleanup"] is True

    def test_force_cleanup_can_be_false(self):
        bi = _make_bugs_info()
        with patch.object(api, "BugsInfo", return_value=bi), \
             patch.object(api, "run_reproduce_queue", return_value=None):
            r = client.post("/reproduce", json={"bug_id": BUG_ID, "is_force_cleanup": False})
        handle = r.json()["handle"]
        assert api.tasks[handle]["force_cleanup"] is False


# ═════════════════════════════════════════════════════════════════════
# 4.  /fix
# ═════════════════════════════════════════════════════════════════════

class TestFix:
    PATCH_PATH = f"/patches/{PROJECT}/{'a' * 32}@sha___file.cpp"

    def _post(self, bug_id=BUG_ID, patch_path=None):
        return client.post("/fix", json={
            "bug_id":     bug_id,
            "patch_path": patch_path or self.PATCH_PATH,
        })

    def test_bad_bug_id_returns_400(self):
        r = self._post(bug_id="no-at-sign")
        assert r.status_code == 400

    def test_unknown_project_returns_400(self):
        r = self._post(bug_id="unknown___proj@" + SHA)
        assert r.status_code == 400

    def test_cache_hit_returns_handle_immediately(self):
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
        body = r.json()
        assert "handle" in body
        assert "redis_key" in body

    def test_cache_miss_queues_background_task(self):
        bi = _make_bugs_info()
        with patch.object(api, "BugsInfo", return_value=bi), \
             patch.object(api, "get_cached_result", return_value=None), \
             patch.object(api, "store_task_in_redis"), \
             patch.object(api, "run_fix_queue", return_value=None):
            r = self._post()
        assert r.status_code == 200
        body = r.json()
        assert "handle" in body
        assert "redis_key" in body

    def test_handle_is_deterministic_for_same_inputs(self):
        """Same bug_id + patch_path must always produce the same handle."""
        bi = _make_bugs_info()
        with patch.object(api, "BugsInfo", return_value=bi), \
             patch.object(api, "get_cached_result", return_value=None), \
             patch.object(api, "store_task_in_redis"), \
             patch.object(api, "run_fix_queue", return_value=None):
            r1 = self._post()
            r2 = self._post()
        assert r1.json()["handle"] == r2.json()["handle"]


# ═════════════════════════════════════════════════════════════════════
# 5.  /status/{handle}
# ═════════════════════════════════════════════════════════════════════

class TestStatus:
    def test_404_for_unknown_handle(self):
        with patch.object(api, "get_task_from_redis", return_value=None):
            r = client.get("/status/nonexistent_handle_xyz")
        assert r.status_code == 404

    def test_returns_in_memory_task(self):
        handle = "mem_handle_001"
        api.tasks[handle] = {"status": "queued", "bug_id": BUG_ID}
        r = client.get(f"/status/{handle}")
        assert r.status_code == 200
        assert r.json()["status"] == "queued"

    def test_falls_back_to_redis(self):
        handle = "redis_handle_abc"
        redis_data = {"status": "completed", "return_code": 0, "fix_log": "passed"}
        # Make sure it's NOT in the in-memory tasks dict
        api.tasks.pop(handle, None)
        with patch.object(api, "get_task_from_redis", return_value=redis_data):
            r = client.get(f"/status/{handle}")
        assert r.status_code == 200
        assert r.json()["status"] == "completed"

    def test_in_memory_takes_priority_over_redis(self):
        handle = "priority_test_handle"
        api.tasks[handle] = {"status": "running", "source": "memory"}
        redis_data = {"status": "completed", "source": "redis"}
        with patch.object(api, "get_task_from_redis", return_value=redis_data):
            r = client.get(f"/status/{handle}")
        assert r.json()["source"] == "memory"


# ═════════════════════════════════════════════════════════════════════
# 6.  /cache/status
# ═════════════════════════════════════════════════════════════════════

class TestCacheStatus:
    def test_redis_disconnected(self):
        with patch.object(api.redis_manager, "is_connected", return_value=False):
            r = client.get("/cache/status")
        assert r.status_code == 200
        body = r.json()
        assert body["redis_connected"] is False
        assert body["redis_info"] is None

    def test_redis_connected(self):
        fake_info = {"redis_version": "7.0.0", "used_memory": 1024}
        with patch.object(api.redis_manager, "is_connected", return_value=True), \
             patch.object(api.redis_manager.client, "info", return_value=fake_info):
            r = client.get("/cache/status")
        assert r.status_code == 200
        body = r.json()
        assert body["redis_connected"] is True
        assert body["redis_info"]["redis_version"] == "7.0.0"


# ═════════════════════════════════════════════════════════════════════
# 7.  DELETE /cache/{redis_key}
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
        body = r.json()
        assert body["deleted"] is True
        assert body["key"] == self.KEY

    def test_reports_false_for_missing_key(self):
        with patch.object(api.redis_manager, "is_connected", return_value=True), \
             patch.object(api.redis_manager.client, "delete", return_value=0):
            r = client.delete(f"/cache/{self.KEY}")
        assert r.status_code == 200
        assert r.json()["deleted"] is False

    def test_500_on_redis_error(self):
        with patch.object(api.redis_manager, "is_connected", return_value=True), \
             patch.object(api.redis_manager.client, "delete", side_effect=Exception("boom")):
            r = client.delete(f"/cache/{self.KEY}")
        assert r.status_code == 500


# ═════════════════════════════════════════════════════════════════════
# 8.  /all_tasks
# ═════════════════════════════════════════════════════════════════════

class TestAllTasks:
    def test_returns_200(self):
        with patch.object(api.redis_manager, "is_connected", return_value=False):
            r = client.get("/all_tasks")
        assert r.status_code == 200

    def test_includes_in_memory_tasks(self):
        handle = "all_tasks_mem_handle"
        api.tasks[handle] = {"status": "queued", "bug_id": BUG_ID}
        with patch.object(api.redis_manager, "is_connected", return_value=False):
            r = client.get("/all_tasks")
        assert handle in r.json()

    def test_includes_redis_tasks(self):
        redis_key   = f"patch_{SHA}_{'b' * 32}.log"
        redis_handle = api.redis_key_to_handle(redis_key)
        redis_task   = {"status": "completed", "return_code": 0}

        # Clear in-memory so no collision
        api.tasks.pop(redis_handle, None)

        with patch.object(api.redis_manager, "is_connected", return_value=True), \
             patch.object(api.redis_manager.client, "keys", return_value=[f"task_{redis_key}"]), \
             patch.object(api, "get_task_from_redis", return_value=redis_task):
            r = client.get("/all_tasks")
        assert redis_handle in r.json()

    def test_redis_error_does_not_crash(self):
        with patch.object(api.redis_manager, "is_connected", return_value=True), \
             patch.object(api.redis_manager.client, "keys", side_effect=Exception("conn err")):
            r = client.get("/all_tasks")
        assert r.status_code == 200    # still returns the in-memory portion


# ═════════════════════════════════════════════════════════════════════
# 9.  /build_patch
# ═════════════════════════════════════════════════════════════════════

class TestBuildPatch:
    """Tests for POST /build_patch."""

    # ── shared fixtures ──────────────────────────────────────────────

    @pytest.fixture(autouse=True)
    def _inject_guidance(self):
        """Inject a minimal guidance_df and SRC_CONTENT for every test."""
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
        # Replicate the normalisation done by load_guidance
        df["src_path"] = df["src_path"].apply(
            lambda x: str(api.PATCH_OUTPUT_BEFORE_DIR / os.path.basename(x))
        )

        # Write the source file to PATCH_OUTPUT_BEFORE_DIR
        (api.PATCH_OUTPUT_BEFORE_DIR / src_filename).write_text(SAMPLE_SRC)

        old_df       = api.guidance_df
        old_content  = dict(api.SRC_CONTENT)
        old_meta     = dict(api.META_DICT)

        api.guidance_df              = df
        api.SRC_CONTENT[src_abs]     = SAMPLE_SRC
        api.META_DICT[SHA]           = {**FAKE_META_DEFECT, "project": PROJECT}

        yield {"src_abs": src_abs, "src_filename": src_filename}

        api.guidance_df  = old_df
        api.SRC_CONTENT  = old_content
        api.META_DICT    = old_meta

    def _post(self, llm_response="int foo() { return 1; }", method="direct", **kw):
        payload = {"bug_id": BUG_ID, "llm_response": llm_response, "method": method}
        payload.update(kw)
        return client.post("/build_patch", json=payload)

    # ── error cases ──────────────────────────────────────────────────

    def test_invalid_bug_id_returns_400(self):
        r = client.post("/build_patch", json={
            "bug_id": "bad-format", "llm_response": "x"
        })
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

    def test_unknown_sha_in_guidance_returns_400(self):
        r = client.post("/build_patch", json={
            "bug_id": f"{PROJECT}@{'f' * 40}", "llm_response": "x"
        })
        assert r.status_code == 400
        assert r.json()["detail"]["error_code"] == api.ErrorCodes.ERR_BUG_ID_NOT_IN_GUIDANCE

    def test_sha_missing_from_meta_dict_returns_400(self):
        old = api.META_DICT.pop(SHA)
        try:
            r = self._post()
        finally:
            api.META_DICT[SHA] = old
        assert r.status_code == 400
        assert r.json()["detail"]["error_code"] == api.ErrorCodes.ERR_RECORD_NOT_FOUND

    def test_src_content_not_cached_returns_400(self, _inject_guidance):
        src_abs = _inject_guidance["src_abs"]
        old = api.SRC_CONTENT.pop(src_abs, None)
        try:
            r = self._post()
        finally:
            if old is not None:
                api.SRC_CONTENT[src_abs] = old
        assert r.status_code == 400
        assert r.json()["detail"]["error_code"] == api.ErrorCodes.ERR_SRC_CONTENT_NOT_CACHED

    def test_direct_method_missing_backtick_block_returns_400(self):
        r = self._post(llm_response="no backticks here", method="direct")
        assert r.status_code == 400
        assert r.json()["detail"]["error_code"] == api.ErrorCodes.ERR_MARKDOWN_EXTRACT_FAIL

    # ── success cases ─────────────────────────────────────────────────

    def test_direct_method_success(self):
        snippet = "```c\nint foo() { return 42; }\n```"
        with patch.object(api, "create_patch_file") as mock_cpf:
            mock_cpf.return_value = (
                {"bug_id": BUG_ID, "sha": SHA, "fix_p": "/tmp/f", "fix_p_diff": "/tmp/f.patch",
                 "patch": "--- a/foo\n+++ b/foo\n@@ -1 +1 @@\n-old\n+new\n"},
                None,
            )
            r = self._post(llm_response=snippet, method="direct")
        assert r.status_code == 200
        body = r.json()
        assert body["success"] is True
        assert body["sha"] == SHA
        assert body["md5_hash"] is not None

    def test_prefix_method_success(self):
        snippet = "int foo() { return 99; }\n"
        with patch.object(api, "create_patch_file") as mock_cpf:
            mock_cpf.return_value = (
                {"bug_id": BUG_ID, "sha": SHA, "fix_p": "/tmp/f", "fix_p_diff": None,
                 "patch": "--- a/foo\n+++ b/foo\n@@ -1 +1 @@\n-old\n+new\n"},
                None,
            )
            r = self._post(llm_response=snippet, method="prefix")
        assert r.status_code == 200
        assert r.json()["success"] is True

    def test_create_patch_file_failure_returns_error_response(self):
        snippet = "```c\nint foo() { return 1; }\n```"
        with patch.object(api, "create_patch_file", return_value=(None, "Source file not found: /x")):
            r = self._post(llm_response=snippet, method="direct")
        assert r.status_code == 200          # 200 with success=False per the response model
        body = r.json()
        assert body["success"] is False
        assert body["error"] is not None

    def test_md5_hash_is_stable(self):
        """Same patch text must produce the same md5_hash."""
        snippet = "```c\nint foo() { return 7; }\n```"
        # Use side_effect so each call gets a fresh dict (avoids mutation by meta.pop())
        def _fresh_meta(*args, **kwargs):
            return (
                {"bug_id": BUG_ID, "sha": SHA, "fix_p": "/tmp/f", "fix_p_diff": None,
                 "patch": "diff content"},
                None,
            )
        with patch.object(api, "create_patch_file", side_effect=_fresh_meta):
            r1 = self._post(llm_response=snippet, method="direct")
            r2 = self._post(llm_response=snippet, method="direct")
        assert r1.json()["md5_hash"] == r2.json()["md5_hash"]

    def test_func_start_end_bytes_are_integers(self):
        snippet = "```c\nint foo() { return 5; }\n```"
        with patch.object(api, "create_patch_file") as mock_cpf:
            mock_cpf.return_value = (
                {"bug_id": BUG_ID, "sha": SHA, "fix_p": "/tmp/f", "fix_p_diff": None,
                 "patch": "--- a/x\n+++ b/x\n"},
                None,
            )
            r = self._post(llm_response=snippet, method="direct")
        body = r.json()
        if body["success"]:
            assert isinstance(body["func_start_byte"], int)
            assert isinstance(body["func_end_byte"], int)


# ═════════════════════════════════════════════════════════════════════
# 10. Unit tests for pure helper functions (no HTTP)
# ═════════════════════════════════════════════════════════════════════

class TestHelpers:
    # ── parse_bug_id ─────────────────────────────────────────────────

    def test_parse_bug_id_valid(self):
        p, s = api.parse_bug_id("myorg___myrepo@abc123")
        assert p == "myorg___myrepo"
        assert s == "abc123"

    def test_parse_bug_id_missing_at(self):
        with pytest.raises(ValueError, match="format"):
            api.parse_bug_id("no-at-sign")

    def test_parse_bug_id_empty_sha(self):
        with pytest.raises(ValueError):
            api.parse_bug_id("proj@")

    # ── extract_patch_md5 ────────────────────────────────────────────

    def test_extract_md5_from_filename_prefix(self):
        md5 = "a" * 32
        path = f"/patches/{md5}@{SHA}___file.cpp"
        assert api.extract_patch_md5(path) == md5

    def test_extract_md5_hex_in_name(self):
        md5 = "b" * 32
        path = f"/patches/some_{md5}_file.cpp"
        assert api.extract_patch_md5(path) == md5

    def test_extract_md5_falls_back_to_hash(self):
        path = "/patches/no_hex_here.cpp"
        result = api.extract_patch_md5(path)
        assert len(result) == 32
        assert result == hashlib.md5(path.encode()).hexdigest()

    # ── build_redis_key ──────────────────────────────────────────────

    def test_redis_key_format(self):
        md5 = "c" * 32
        patch_path = f"/patches/{md5}@sha___file.cpp"
        key = api.build_redis_key(BUG_ID, patch_path)
        assert key.startswith(f"patch_{SHA}_")
        assert key.endswith(".log")

    # ── handle <-> redis_key round-trip ──────────────────────────────

    def test_handle_roundtrip(self):
        key    = f"patch_{SHA}_{'d' * 32}.log"
        handle = api.redis_key_to_handle(key)
        assert api.handle_to_redis_key(handle) == key

    def test_handle_to_redis_key_invalid(self):
        with pytest.raises(ValueError):
            api.handle_to_redis_key("!!!not-base64!!!")

    # ── is_unified_diff ──────────────────────────────────────────────

    def test_recognises_unified_diff(self):
        assert api.is_unified_diff("--- a/foo\n+++ b/foo\n")

    def test_recognises_diff_header(self):
        assert api.is_unified_diff("diff --git a/foo b/foo\n")

    def test_rejects_plain_code(self):
        assert not api.is_unified_diff("int main() { return 0; }")

    # ── extract_inline_snippet ────────────────────────────────────────

    def test_extracts_from_backtick_block(self):
        s = "```c\nint x = 1;\n```"
        assert api.extract_inline_snippet(s) == "int x = 1;"

    def test_returns_none_when_no_block(self):
        assert api.extract_inline_snippet("no backticks") is None

    # ── md5 ──────────────────────────────────────────────────────────

    def test_md5_is_lowercase_hex(self):
        result = api.md5("hello world")
        assert len(result) == 32
        assert result == result.lower()

    def test_md5_strips_and_lowercases_input(self):
        assert api.md5("  HELLO  ") == api.md5("hello")

    # ── read_file_limited ────────────────────────────────────────────

    def test_read_missing_file_returns_empty(self):
        assert api.read_file_limited("/nonexistent/path/xyz.log") == ""

    def test_read_real_file(self, tmp_path):
        f = tmp_path / "sample.log"
        f.write_text("line one\nline two\n")
        result = api.read_file_limited(f)
        assert "line one" in result
        assert "line two" in result

    def test_max_tokens_truncation(self, tmp_path):
        f = tmp_path / "big.log"
        f.write_text((" ".join(["word"] * 1000)) + "\n")
        result = api.read_file_limited(f, max_tokens=10)
        assert len(result.split()) <= 10

    # ── get_log_file_paths ───────────────────────────────────────────

    def test_log_paths_contain_sha_and_md5(self):
        patch_md5 = "e" * 32
        paths = api.get_log_file_paths(PROJECT, SHA, patch_md5)
        for ext in ("log", "msg", "status"):
            assert ext in paths
            assert SHA in paths[ext]
            assert patch_md5 in paths[ext]

    # ── get_cached_result (no Redis) ─────────────────────────────────

    def test_get_cached_result_returns_none_when_disconnected(self):
        with patch.object(api.redis_manager, "is_connected", return_value=False), \
             patch.object(api, "parse_redis_key", side_effect=ValueError("bad")):
            result = api.get_cached_result("patch_abc_def.log")
        assert result is None

    def test_get_cached_result_returns_data_from_redis(self):
        fake_data = {
            "status": "completed", "return_code": "0",
            "fix_log": "passed", "fix_msg": "", "fix_status": "",
            "error": "", "timestamp": "123",
        }
        with patch.object(api.redis_manager, "is_connected", return_value=True), \
             patch.object(api.redis_manager.client, "hgetall", return_value=fake_data):
            result = api.get_cached_result("some_key")
        assert result is not None
        assert result["status"] == "completed"
        assert result["return_code"] == 0        # must be int
        assert result["from_cache"] is True


# ═════════════════════════════════════════════════════════════════════
# 11. load_metadata / load_guidance helpers
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
        jsonl_path = tmp_path / "sources.jsonl"
        jsonl_path.write_text(
            json.dumps({"id": filename, "content": "int bar() {}"}) + "\n"
        )
        old = dict(api.SRC_CONTENT)
        try:
            count = api.load_src_content(str(jsonl_path))
        finally:
            api.SRC_CONTENT.clear()
            api.SRC_CONTENT.update(old)

        assert count >= 1

    def test_load_prefix_suffix_meta_skips_missing_files(self):
        old = dict(api.META_DICT_PREFIX_SUFFIX)
        try:
            count = api.load_prefix_suffix_meta(prefix_dirs=[
                Path("/nonexistent/path1.json"),
                Path("/nonexistent/path2.json"),
            ])
        finally:
            api.META_DICT_PREFIX_SUFFIX.clear()
            api.META_DICT_PREFIX_SUFFIX.update(old)
        # Should not raise; count = 0 (or whatever was already there)
        assert isinstance(count, int)


# ═════════════════════════════════════════════════════════════════════
# 12. Redis store/retrieve helpers
# ═════════════════════════════════════════════════════════════════════

class TestRedisHelpers:
    def test_store_task_noop_when_disconnected(self):
        with patch.object(api.redis_manager, "is_connected", return_value=False):
            # Should not raise
            api.store_task_in_redis("handle123", {"status": "queued"})

    def test_store_task_calls_hset(self):
        mock_inner = MagicMock()
        api.redis_manager._redis_client = mock_inner
        with patch.object(api.redis_manager, "is_connected", return_value=True):
            api.store_task_in_redis(
                api.redis_key_to_handle(f"patch_{SHA}_{'f' * 32}.log"),
                {"status": "queued", "return_code": 0, "cached": False, "log_paths": {"log": "/x"}},
            )
        mock_inner.hset.assert_called_once()

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
        assert project  == PROJECT
        assert sha      == SHA
        assert patch_md5 == md5

    def test_parse_redis_key_invalid_format(self):
        with pytest.raises(ValueError):
            api.parse_redis_key("wrong_format")

    def test_parse_redis_key_unknown_sha(self):
        with pytest.raises(ValueError, match="Cannot find project"):
            api.parse_redis_key(f"patch_{'z' * 40}_{'a' * 32}.log")


# ═════════════════════════════════════════════════════════════════════
# 13. File-fallback path (get_cached_result / get_task_from_redis)
# ═════════════════════════════════════════════════════════════════════

class TestFileFallback:
    def test_cached_result_falls_back_to_files(self, tmp_path):
        md5 = "0" * 32
        log_dir = tmp_path / PROJECT / "logs"
        log_dir.mkdir(parents=True)
        (log_dir / f"patch_{SHA}_{md5}.log").write_text("test output")
        (log_dir / f"patch_{SHA}_{md5}.status").write_text("0")

        api.META_DICT[SHA] = {"project": PROJECT}
        old_out = api.OUT_ROOT

        # Temporarily redirect OUT_ROOT
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

    def test_read_result_from_files_missing_log(self):
        result = api.read_result_from_files(PROJECT, "nonexistent_sha", "nonexistent_md5")
        assert result is None

    def test_read_result_status_file_sets_return_code(self, tmp_path):
        md5 = "1" * 32
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

