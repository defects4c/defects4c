# Defects4C API Usage Guide (gened via AI )

**Service:** `new_main.py` — Defects4C Service v2.0.0  
**Base URL (default):** `http://127.0.0.1:11111 (https://defects4c.wj2ai.com for limited support )`

---

## Bug ID Format

Every endpoint that refers to a specific defect uses a **bug ID** in the form:

```
project___owner@sha40
```

For example: `danmar___cppcheck@f5dbfce8ffb3132bb49a155527a620c98e61b4a1`

Always obtain the bug ID from `/list_defects_bugid` or from the `bug_id` field in a `/get_defect` response — never construct it manually from a bare SHA.

---

## Typical Workflow

```
/list_defects_bugid          ← pick a bug
       │
/get_defect/{bug_id}         ← get prompts + metadata
       │
  LLM call (your code)       ← generate a fix
       │
/build_patch                 ← write patch file to disk
       │
/fix                         ← run test suite, get handle
       │
/status/{handle}  (poll)     ← wait for completed / failed
```

---

## Endpoints

### Health

#### `GET /health`

Returns service liveness. No authentication required.

**Response**
```json
{ "status": "ok" }
```

---

### Defect Discovery

#### `GET /list_defects_bugid`

Lists every available defect in `project@sha` format, suitable for direct use as a bug ID. Filters out llvm defects if they are too CPU-heavy for your environment.

**Response**
```json
{
  "status": "success",
  "total_count": 1234,
  "defects": ["danmar___cppcheck@f5dbfce8...", "..."],
  "sample_defects": ["..."]
}
```

#### `GET /list_defects_ids`

Lists all defect `idx` keys (internal identifiers, may be bare SHAs). Prefer `/list_defects_bugid` for user-facing use.

**Response**
```json
{
  "status": "success",
  "total_count": 1234,
  "defect_ids": ["f5dbfce8...", "..."],
  "sample_ids": ["..."]
}
```

---

### Defect Detail

#### `GET /get_defect/{bug_id}`

Returns full prompt data and metadata for a single defect. The `bug_id` path parameter must be in `project@sha` format.

**Example**
```
GET /get_defect/danmar___cppcheck@f5dbfce8ffb3132bb49a155527a620c98e61b4a1
```

**Response**
```json
{
  "status": "success",
  "defect_id": "danmar___cppcheck@f5dbfce8...",
  "sha_id": "f5dbfce8ffb3132bb49a155527a620c98e61b4a1",
  "bug_id": "danmar___cppcheck@f5dbfce8...",
  "prompt_data": {
    "idx": "danmar___cppcheck@f5dbfce8...",
    "bug_id": "danmar___cppcheck@f5dbfce8...",
    "prompt": [
      { "role": "system", "content": "You are a C/CPP code program repair expert" },
      { "role": "user",   "content": "The following code contains a buggy line..." }
    ],
    "temperature": 0.8
  },
  "additional_info": {
    "metadata": { "...": "..." },
    "guidance": { "src_path": "/path/to/file.cpp", "...": "..." },
    "prefix_suffix": { "prefix": "...", "suffix": "..." },
    "has_source_content": true,
    "source_content_length": 8192
  },
  "total_defects_available": 1234
}
```

**Key fields to use downstream:**
- `bug_id` — pass this to `/build_patch` and `/fix`; always authoritative `project@sha`
- `prompt_data.prompt` — ready-made message list for any OpenAI-compatible API
- `prompt_data.temperature` — recommended sampling temperature

**Error responses**

| Status | Meaning |
|--------|---------|
| 404 | `bug_id` not found in loaded data |
| 500 | Internal error retrieving record |

#### `GET /reset`

Returns a **randomly selected** defect. Same response shape as `/get_defect`. Useful for exploration or batch sampling.

---

### Patch Building

#### `POST /build_patch`

Converts an LLM response into a patch file on disk and returns the patch path needed by `/fix`.

**Request body**
```json
{
  "bug_id":        "danmar___cppcheck@f5dbfce8...",
  "llm_response":  "<full LLM output string>",
  "method":        "direct",
  "generate_diff": true,
  "persist_flag":  true
}
```

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `bug_id` | string | **required** | Must be `project@sha` format |
| `llm_response` | string | **required** | Raw LLM output (code block, diff, or inline) |
| `method` | string | `"prefix"` | Patch extraction strategy — see below |
| `generate_diff` | bool | `true` | Also write a `.diff` file alongside the patch |
| `persist_flag` | bool | `false` | Persist patch to the canonical patch output directory |

**`method` values**

| Value | When to use |
|-------|-------------|
| `"direct"` | LLM returned a fenced code block (` ```cpp ... ``` `) |
| `"diff"` | LLM returned a unified diff (`--- / +++ / @@`) |
| `"inline"` | LLM returned the modified file inline |
| `"inline+meta"` | LLM returned a unified diff; use context-aware meta patching |
| `"prefix"` | LLM returned a prefix/suffix snippet (default) |
| _(auto)_ | Omit or pass empty string — service auto-detects `diff` vs `direct` |

**Successful response**
```json
{
  "success":         true,
  "bug_id":          "danmar___cppcheck@f5dbfce8...",
  "sha":             "f5dbfce8ffb3132bb49a155527a620c98e61b4a1",
  "fix_p":           "/patches/danmar___cppcheck/abc123@f5dbfce8.patch",
  "fix_p_diff":      "/patches/danmar___cppcheck/abc123@f5dbfce8.diff",
  "md5_hash":        "abc123def456...",
  "patch_content":   "--- a/file.cpp\n+++ b/file.cpp\n...",
  "content":         "<full patched file text>",
  "func_start_byte": 1024,
  "func_end_byte":   2048
}
```

**The `fix_p` field is the patch path you pass to `/fix`.**

**Error response**
```json
{
  "success":    false,
  "error":      "Human-readable description",
  "error_code": "err_invalid_bug_id_format"
}
```

**Error codes**

| Code | Meaning |
|------|---------|
| `err_invalid_bug_id_format` | `bug_id` is not `project@sha` |
| `err_guidance_not_loaded` | Server data not initialised |
| `err_bug_id_not_in_guidance` | SHA not in guidance CSV |
| `err_record_not_found` | No metadata record for this bug |
| `err_src_content_not_cached` | Source file not in server cache |
| `err_extract_code_fail` | Could not extract code from LLM response |
| `err_context_mismatch_byte_range` | Patch context does not match source |
| `err_no_patch_content_identified` | Patch text is empty after processing |
| `err_patch_file_creation_failed` | Disk write error |

---

### Fix Verification

#### `POST /fix`

Submits a patch for test-suite verification. Returns immediately with a `handle`; use `/status/{handle}` to poll for results.

Results are cached in Redis (TTL 24 h). Submitting the same `bug_id` + `patch_path` twice returns the cached handle immediately without re-running the tests.

**Request body**
```json
{
  "bug_id":     "danmar___cppcheck@f5dbfce8...",
  "patch_path": "/patches/danmar___cppcheck/abc123@f5dbfce8.patch"
}
```

**Response**
```json
{
  "handle":    "cGF0Y2hfZjVkYmZjZTh...",
  "redis_key": "patch_f5dbfce8_abc123def456.log"
}
```

The handle is a **deterministic** base64 encoding of the redis key — submitting the same patch twice returns the same handle.

#### `GET /status/{handle}`

Polls the status of a `/fix` or `/reproduce` job.

**Response (in progress)**
```json
{
  "bug_id":      "danmar___cppcheck@f5dbfce8...",
  "sha":         "f5dbfce8ffb3132bb49a155527a620c98e61b4a1",
  "status":      "queued",
  "patch":       "/patches/.../abc123@f5dbfce8.patch",
  "redis_key":   "patch_f5dbfce8_abc123def456.log",
  "cached":      false
}
```

**Response (completed)**
```json
{
  "status":      "completed",
  "return_code": 0,
  "fix_status":  "0",
  "fix_log":     "...last 100 lines of test output...",
  "fix_msg":     "...summary message...",
  "error":       "",
  "timestamp":   "1710000000.0",
  "cached":      false
}
```

**Status values**

| `status` | Meaning |
|----------|---------|
| `"queued"` | Job accepted, not yet started |
| `"running"` | Tests executing |
| `"completed"` | Tests finished — check `return_code` |
| `"failed"` | Runner error (not a test failure) |

**Success vs failure:** `return_code == 0` means all tests passed. `return_code != 0` means the patch did not fix the bug.

**Polling recommendation:** check every 10–30 seconds; most jobs finish within 5 minutes. Stop polling when `status` is `"completed"` or `"failed"`.

**Error responses**

| Status | Meaning |
|--------|---------|
| 404 | Handle not found in memory or Redis |

---

### Reproduction

#### `POST /reproduce`

Reproduces the original bug (no patch applied) in a background job. Useful to verify the baseline failure before testing a fix.

**Request body**
```json
{
  "bug_id":           "danmar___cppcheck@f5dbfce8...",
  "is_force_cleanup": true
}
```

**Response**
```json
{ "handle": "9f4a2b1c..." }
```

The handle is a **random UUID** (unlike `/fix` handles). Poll `/status/{handle}` the same way.

---

### LLM Endpoints (Internal Debugger)

These endpoints use the server's own OpenAI-compatible client (configured via `OPENAI_API_KEY` and `LLM_MODEL` env vars). They are provided as a convenience; most integrations supply their own LLM client.

#### `POST /ask_llm`

Non-streaming C/C++ code fix. Returns JSON.

**Request body**
```json
{
  "code":     "bool isOppositeExpression(...) { ... }",
  "feedback": "<compiler or test error message>",
  "model":    "deepseek-chat"
}
```

**Response**
```json
{
  "fixed_code":   "bool isOppositeExpression(...) { ... }",
  "explanation":  "The condition used tok1 instead of tok2.",
  "changes_made": ["Changed tok1->astOperand2() to tok2->astOperand2()"]
}
```

#### `POST /ask_llm_stream`

Streaming version of `/ask_llm`. Returns `text/plain` with XML-tagged chunks:

```
<fixed_code>
bool isOppositeExpression(...) { ... }
</fixed_code>

<explanation>
The condition used tok1 instead of tok2.
</explanation>

<changes_made>
- Changed tok1->astOperand2() to tok2->astOperand2()
</changes_made>
```

On error, the stream contains `<error>{message}</error>`.

---

### Cache & Task Management

#### `GET /cache/status`

Returns Redis connection state.

```json
{
  "redis_connected": true,
  "redis_info": { "...": "..." }
}
```

#### `DELETE /cache/{redis_key}`

Evicts a specific result from Redis so the patch will be re-run next time. Requires Redis to be connected.

```
DELETE /cache/patch_f5dbfce8_abc123def456.log
```

#### `GET /all_tasks`

Returns all in-memory tasks plus all `task_*` keys from Redis. Useful for monitoring.

#### `GET /projects`

Lists all known project identifiers loaded at startup.

---

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `SRC_DIR` | `/src/` | Root source directory |
| `ROOT_DIR` | `/out/` | Root output directory |
| `PATCH_OUTPUT_DIR` | `/patches/` | Where patch files are written |
| `OPENAI_API_KEY` | — | API key for `/ask_llm*` endpoints |
| `LLM_MODEL` | `deepseek-chat` | Default model for `/ask_llm*` |

---

## Error Handling Patterns

All 4xx errors return JSON:
```json
{
  "detail": {
    "error_code": "err_invalid_bug_id_format",
    "message":    "Bug ID must be in format 'project@sha'"
  }
}
```

Generic 4xx/5xx errors return:
```json
{ "detail": "<string description>" }
```

---

## Complete Python Example

```python
import requests, time, random
from openai import OpenAI

BASE = "http://127.0.0.1:11111"
llm  = OpenAI(api_key="sk-...", base_url="https://api.deepseek.com")

# 1. Pick a defect
defects = requests.get(f"{BASE}/list_defects_bugid").json()["defects"]
defects = [d for d in defects if "llvm___llvm" not in d]   # skip CPU-heavy
selected = random.choice(defects)

# 2. Get prompts — use bug_id from the response, not the listing entry
defect   = requests.get(f"{BASE}/get_defect/{selected}").json()
bug_id   = defect["bug_id"]                               # authoritative project@sha
prompts  = defect["prompt_data"]["prompt"]
temp     = defect["prompt_data"].get("temperature", 0.8)

# 3. Ask the LLM
llm_out  = llm.chat.completions.create(
    model="deepseek-chat", messages=prompts,
    temperature=temp, max_tokens=4096,
).choices[0].message.content

# 4. Build patch
patch = requests.post(f"{BASE}/build_patch", json={
    "bug_id": bug_id, "llm_response": llm_out,
    "method": "direct", "generate_diff": True, "persist_flag": True,
}).json()
assert patch["success"], patch.get("error")
patch_path = patch["fix_p"]

# 5. Submit for verification
handle = requests.post(f"{BASE}/fix", json={
    "bug_id": bug_id, "patch_path": patch_path,
}).json()["handle"]

# 6. Poll for result
for _ in range(30):
    s = requests.get(f"{BASE}/status/{handle}").json()
    if s["status"] in ("completed", "failed"):
        print("✅ Pass" if s.get("return_code") == 0 else f"❌ Fail rc={s.get('return_code')}")
        break
    time.sleep(10)
```
