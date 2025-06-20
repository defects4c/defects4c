## Defects4C: Benchmarking Large Language Model Repair Capability with C/C++ Bugs 👋

### ⚠️⚠️⚠️ We are updating the online platform within this week (by July 1, 2025). You do not need to install and deploy docker-container locally—just call the API(like https://e2b.dev/) to test your LLM results. So far, it supports pass@1 for each defect. If you prefer pass@k>1, you will have to deploy locally as our computation budget is limited. ⚠️⚠️⚠️

Most existing Automated Program Repair (APR) research focuses on Java programs, primarily through Defects4J. Despite the significant prevalence of C/C++ vulnerabilities, extensive research on the automated repair of such vulnerabilities is lacking.

To fill this critical gap, we introduce Defects4C, a high-quality executable benchmark for C/C++ defects. It consists of **248** buggy functions and **102** vulnerable functions, paired with test cases for reproduction.




## Scenario

To assess the effectiveness of existing state-of-the-art APR techniques in repairing C/C++ faults, we conduct a comprehensive empirical study using 24 state-of-the-art LLMs with Defects4C in two different scenarios:

  - Single-round repair
  - Conversation-based repair for evaluation. 


# FastAPI Services Documentation

## API Overview

### Bug Helper Service API (`http://localhost:8000`)
| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/projects` | Retrieve all available projects |
| `POST` | `/reproduce` | Initiate bug reproduction |
| `POST` | `/fix` | Apply patch and test fix |
| `GET` | `/status/{handle}` | Get task status and results |
| `GET` | `/cache/status` | Check Redis cache status |
| `DELETE` | `/cache/{redis_key}` | Clear specific cache entry |
| `GET` | `/all_tasks` | Retrieve all active tasks |

### Unified Patch Service API (`http://localhost:8000`)
| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/health` | Service health check |
| `POST` | `/build_patch` | Generate and apply patches |

---

<details>
<summary><h2>📋 Overview</h2></summary>

This document covers two complementary FastAPI services designed for comprehensive software bug workflows:

1. **Bug Helper Service** - Bug reproduction and fixing service with Redis caching
2. **Unified Patch Service** - Advanced patch generation and application service

Both services provide REST APIs for managing complete software bug workflows, from initial reproduction through patch generation and application.

</details>

---

<details>
<summary><h2>🔧 Bug Helper Service API</h2></summary>

The Bug Helper Service is a FastAPI-based service for reproducing and fixing software bugs with Redis-based caching support for improved performance and reliability.

**Base URL:** `http://localhost:8000`  
**Version:** 1.0.0

### Core Endpoints

<details>
<summary><h3>GET /projects</h3></summary>

```python
def get_projects():
    """
    Retrieve all available projects for bug reproduction.
    
    Returns:
        dict: Dictionary containing list of available project names
    
    Raises:
        HTTPException: 500 if projects cannot be loaded
    """
```

**Description:**
Retrieves a list of all available projects that can be used for bug reproduction and fixing. This endpoint requires no authentication and provides the foundation for other operations by listing valid project names.

**Input Parameters:**
- None required

**Output Format:**
- Type: `dict`
- Structure: `{"projects": List[str]}`

**Example:**

```bash
# Request
GET /projects
```

```json
{
  "projects": [
    "libxml2",
    "openssl", 
    "curl",
    "nginx",
    "apache"
  ]
}
```

</details>

<details>
<summary><h3>POST /reproduce</h3></summary>

```python
def reproduce_bug(bug_id: str, is_force_cleanup: bool = True):
    """
    Initiate bug reproduction for a specific bug ID.
    
    Args:
        bug_id (str): Bug identifier in format "project@commit_sha"
        is_force_cleanup (bool, optional): Force cleanup before reproduction. Defaults to True.
    
    Returns:
        dict: Dictionary containing task handle for status tracking
        
    Raises:
        HTTPException: 400 if bug_id format is invalid
        HTTPException: 404 if project not found
        HTTPException: 500 if reproduction fails to start
    """
```

**Description:**
Initiates bug reproduction for a specific bug ID. This endpoint queues a background task to reproduce the bug environment and run tests. The bug reproduction process includes environment setup, dependency installation, and test execution.

**Input Parameters:**
- `bug_id` (str, required): Bug identifier following "project@commit_sha" format
- `is_force_cleanup` (bool, optional): Whether to force cleanup before reproduction (default: true)

**Output Format:**
- Type: `dict`
- Structure: `{"handle": str}`

**Example:**

```bash
# Request
POST /reproduce
Content-Type: application/json
```

```json
{
  "bug_id": "libxml2@a1b2c3d4e5f6789012345678901234567890abcd",
  "is_force_cleanup": true
}
```

```json
{
  "handle": "abc123def456789012345678901234567890uvwx"
}
```

</details>

<details>
<summary><h3>POST /fix</h3></summary>

```python
def fix_bug(bug_id: str, patch_path: str):
    """
    Apply a patch to fix a bug and test the fix.
    
    Args:
        bug_id (str): Bug identifier in format "project@commit_sha"
        patch_path (str): File system path to the patch file
    
    Returns:
        dict: Dictionary containing task handle and Redis key for status tracking
        
    Raises:
        HTTPException: 400 if bug_id format is invalid or patch_path doesn't exist
        HTTPException: 500 if patch application fails
    """
```

**Description:**
Applies a patch to fix a bug and tests the fix. This endpoint uses Redis caching to avoid redundant processing of the same patch. Results are cached based on the combination of bug_id and patch_path, making subsequent requests with identical parameters return immediately.

**Input Parameters:**
- `bug_id` (str, required): Bug identifier in "project@commit_sha" format
- `patch_path` (str, required): File system path to the patch file

**Output Format:**
- Type: `dict`
- Structure: `{"handle": str, "redis_key": str}`

**Example:**

```bash
# Request
POST /fix
Content-Type: application/json
```

```json
{
  "bug_id": "openssl@f1e2d3c4b5a6789012345678901234567890cdef",
  "patch_path": "/patches/openssl_security_fix_20241215.patch"
}
```

```json
{
  "handle": "cGF0Y2hfZjFlMmQzYzRiNWE2XzEyMzQ1Njc4LmxvZw==",
  "redis_key": "patch_f1e2d3c4b5a6_12345678.log"
}
```

</details>

<details>
<summary><h3>GET /status/{handle}</h3></summary>

```python
def get_task_status(handle: str):
    """
    Retrieve current status and results of a task.
    
    Args:
        handle (str): Task handle from /reproduce or /fix response
    
    Returns:
        dict: Task status information varying by operation type
        
    Raises:
        HTTPException: 404 if handle not found
        HTTPException: 500 if status retrieval fails
    """
```

**Description:**
Retrieves the current status and results of a task identified by its handle. Works for both reproduce and fix operations. The response format varies depending on the operation type and current status.

**Input Parameters:**
- `handle` (str, path parameter, required): Task handle from /reproduce or /fix response

**Output Format:**
- Type: `dict`
- Structure varies by operation type:
  - **Reproduce operations:** `{"bug_id": str, "sha": str, "status": str, "log_file": str, "result": dict}`
  - **Fix operations:** `{"bug_id": str, "status": str, "return_code": int, "fix_log": str, "fix_msg": str, "fix_status": str, "cached": bool}`

**Example:**

```bash
# Request
GET /status/cGF0Y2hfZjFlMmQzYzRiNWE2XzEyMzQ1Njc4LmxvZw==
```

```json
{
  "bug_id": "openssl@f1e2d3c4b5a6789012345678901234567890cdef",
  "sha": "f1e2d3c4b5a6789012345678901234567890cdef",
  "status": "completed",
  "return_code": 0,
  "fix_log": "Building project...\nApplying patch...\nRunning tests...\nAll tests passed.",
  "fix_msg": "Patch applied successfully",
  "fix_status": "All tests passed",
  "cached": false,
  "patch": "/patches/openssl_security_fix_20241215.patch",
  "redis_key": "patch_f1e2d3c4b5a6_12345678.log"
}
```

</details>

### Management Endpoints

<details>
<summary><h3>GET /cache/status</h3></summary>

```python
def get_cache_status():
    """
    Get Redis cache connection status and information.
    
    Returns:
        dict: Cache status information including connection state and Redis info
        
    Raises:
        HTTPException: 500 if cache status check fails
    """
```

**Description:**
Provides information about the Redis cache connection and status. Useful for monitoring and debugging cache-related issues. Returns connection state and Redis server information when available.

**Input Parameters:**
- None required

**Output Format:**
- Type: `dict`
- Structure: `{"redis_connected": bool, "redis_info": dict|null}`

**Example:**

```bash
# Request
GET /cache/status
```

```json
{
  "redis_connected": true,
  "redis_info": {
    "redis_version": "6.2.6",
    "used_memory": "2097152",
    "connected_clients": "3",
    "uptime_in_seconds": "7200",
    "total_commands_processed": "156"
  }
}
```

</details>

<details>
<summary><h3>DELETE /cache/{redis_key}</h3></summary>

```python
def clear_cache_entry(redis_key: str):
    """
    Remove a specific cache entry from Redis.
    
    Args:
        redis_key (str): Redis key to delete (from /fix response)
    
    Returns:
        dict: Deletion status and key information
        
    Raises:
        HTTPException: 404 if Redis key not found
        HTTPException: 500 if Redis not connected or deletion fails
    """
```

**Description:**
Removes a specific cache entry from Redis. This forces the next request with the same parameters to recalculate the result. Use with caution as this will trigger full recomputation on subsequent requests.

**Input Parameters:**
- `redis_key` (str, path parameter, required): Redis key to delete (obtained from /fix response)

**Output Format:**
- Type: `dict`
- Structure: `{"deleted": bool, "key": str}`

**Example:**

```bash
# Request
DELETE /cache/patch_f1e2d3c4b5a6_12345678.log
```

```json
{
  "deleted": true,
  "key": "patch_f1e2d3c4b5a6_12345678.log"
}
```

</details>

<details>
<summary><h3>GET /all_tasks</h3></summary>

```python
def get_all_tasks():
    """
    Retrieve all active tasks from memory and Redis.
    
    Returns:
        dict: All active tasks keyed by handle
        
    Raises:
        HTTPException: 500 if task retrieval fails
    """
```

**Description:**
Retrieves all active tasks from both in-memory storage (reproduce operations) and Redis (fix operations). Useful for monitoring and debugging. Each task object contains the same fields as returned by `/status/{handle}`.

**Input Parameters:**
- None required

**Output Format:**
- Type: `dict`
- Structure: `{handle: task_object, ...}`

**Example:**

```bash
# Request
GET /all_tasks
```

```json
{
  "abc123def456": {
    "bug_id": "libxml2@a1b2c3d4e5f6789012345678901234567890abcd",
    "sha": "a1b2c3d4e5f6789012345678901234567890abcd",
    "status": "completed",
    "log_file": "/logs/a1b2c3d4e5f6_reproduce_abc123def456.log",
    "result": {
      "log_file": "/logs/a1b2c3d4e5f6_reproduce_abc123def456.log",
      "return_code": 0
    }
  },
  "xyz789uvw012": {
    "bug_id": "openssl@f1e2d3c4b5a6789012345678901234567890cdef",
    "status": "running",
    "patch": "/patches/openssl_security_fix_20241215.patch",
    "cached": false
  }
}
```

</details>

</details>

---

<details>
<summary><h2>🛠️ Unified Patch Service API</h2></summary>

The Unified Patch Service provides advanced patch generation and application capabilities with support for multiple patch formats, strategies, and intelligent code extraction from LLM responses.

**Base URL:** `http://localhost:8000`  
**Version:** 1.0.0

### Core Endpoints

<details>
<summary><h3>GET /health</h3></summary>

```python
def health_check():
    """
    Health check endpoint for service monitoring.
    
    Returns:
        dict: Service health status and version information
    """
```

**Description:**
Health check endpoint to verify service availability and provide basic service information. Returns service status for monitoring and load balancing purposes.

**Input Parameters:**
- None required

**Output Format:**
- Type: `dict`
- Structure: `{"status": str, "service": str, "version": str}`

**Example:**

```bash
# Request
GET /health
```

```json
{
  "status": "healthy",
  "service": "Patch Service",
  "version": "1.0.0"
}
```

</details>

<details>
<summary><h3>POST /build_patch</h3></summary>

```python
def write_patch(bug_id: str, llm_response: str, method: str = "prefix", generate_diff: bool = True, persist_flag: bool = False):
    """
    Generate and apply patches using various strategies.
    
    Args:
        bug_id (str): Bug identifier in format "project@commit_sha"
        llm_response (str): LLM-generated patch content (inline code or unified diff)
        method (str, optional): Patch application method. Defaults to "prefix".
        generate_diff (bool, optional): Whether to generate diff files. Defaults to True.
        persist_flag (bool, optional): Whether to save files persistently. Defaults to False.
    
    Returns:
        WritePatchResponse: Comprehensive patch generation results
        
    Raises:
        HTTPException: 400 for various validation and processing errors
    """
```

**Description:**
Core endpoint for processing LLM responses and generating patches. Supports multiple patch application methods including direct replacement, unified diff application, and prefix-based patching. The service automatically detects the input format and selects appropriate processing strategies. This endpoint extracts code from markdown responses, applies the patch using the specified method, and generates both the patched file and a git diff.

**Input Parameters:**

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `bug_id` | `string` | ✅ Yes | - | Bug identifier in format "project@sha" |
| `llm_response` | `string` | ✅ Yes | - | LLM response containing code or diff |
| `method` | `string` | ❌ No | `"prefix"` | Patch application method |
| `generate_diff` | `boolean` | ❌ No | `true` | Whether to generate git diff patch file |
| `persist_flag` | `boolean` | ❌ No | `false` | Save files persistently vs temporary files |

**Patch Methods:**
- **`diff`**: Apply unified diff format patches
- **`inline`**: Extract code from markdown and apply directly
- **`inline+meta`**: Apply unified diff with metadata context
- **`direct`**: Direct replacement of function body
- **`prefix`**: Prefix-based replacement with context

**Output Format:**
- Type: `WritePatchResponse`
- Structure: Complex object with patch results, file paths, and metadata

**Response Fields:**

| Field | Type | Description |
|-------|------|-------------|
| `success` | `boolean` | Whether patch operation succeeded |
| `md5_hash` | `string` | MD5 hash of patch content |
| `patch_content` | `string` | Generated git diff content |
| `bug_id` | `string` | Original bug identifier |
| `sha` | `string` | Git commit SHA |
| `fix_p` | `string` | Path to generated fix file |
| `fix_p_diff` | `string` | Path to generated patch file |
| `func_start_byte` | `integer` | Start byte position of modified function |
| `func_end_byte` | `integer` | End byte position of modified function |
| `content` | `string` | Raw patch content applied |
| `error` | `string` | Error message (if success=false) |
| `error_code` | `string` | Structured error code (if success=false) |

**Example:**

```bash
# Request
POST /build_patch
Content-Type: application/json
```

```json
{
  "bug_id": "libxml2@a1b2c3d4e5f6789012345678901234567890abcd",
  "llm_response": "```cpp\nint validateInput(const char* input) {\n    if (!input || strlen(input) == 0) {\n        return 0;\n    }\n    \n    // Additional validation logic\n    for (size_t i = 0; i < strlen(input); i++) {\n        if (!isalnum(input[i]) && input[i] != '_') {\n            return 0;\n        }\n    }\n    \n    return 1;\n}\n```",
  "method": "direct",
  "generate_diff": true,
  "persist_flag": false
}
```

**Success Response:**
```json
{
  "success": true,
  "md5_hash": "5d41402abc4b2a76b9719d911017c592",
  "patch_content": "diff --git a/src/validation.cpp b/src/validation.cpp\nindex 1234567..abcdefg 100644\n--- a/src/validation.cpp\n+++ b/src/validation.cpp\n@@ -15,8 +15,18 @@ int validateInput(const char* input) {\n-    return input != NULL;\n+    if (!input || strlen(input) == 0) {\n+        return 0;\n+    }\n+    \n+    // Additional validation logic\n+    for (size_t i = 0; i < strlen(input); i++) {\n+        if (!isalnum(input[i]) && input[i] != '_') {\n+            return 0;\n+        }\n+    }\n+    \n+    return 1;\n }",
  "bug_id": "libxml2@a1b2c3d4e5f6789012345678901234567890abcd",
  "sha": "a1b2c3d4e5f6789012345678901234567890abcd",
  "fix_p": "/tmp/patches/tmp_xyz123.cpp",
  "fix_p_diff": "/tmp/patches/tmp_xyz123.patch",
  "func_start_byte": 450,
  "func_end_byte": 485,
  "content": "int validateInput(const char* input) {\n    if (!input || strlen(input) == 0) {\n        return 0;\n    }\n    \n    // Additional validation logic\n    for (size_t i = 0; i < strlen(input); i++) {\n        if (!isalnum(input[i]) && input[i] != '_') {\n            return 0;\n        }\n    }\n    \n    return 1;\n}\n"
}
```

**Error Response:**
```json
{
  "success": false,
  "error": "Bug ID libxml2@invalid not found in guidance data",
  "error_code": "err_bug_id_not_in_guidance",
  "md5_hash": null,
  "patch_content": null,
  "bug_id": null,
  "sha": null,
  "fix_p": null,
  "fix_p_diff": null,
  "func_start_byte": null,
  "func_end_byte": null,
  "content": null
}
```

</details>

</details>

---

<details>
<summary><h2>⚠️ Error Handling & Codes</h2></summary>

Both services implement comprehensive error handling with structured error responses for better debugging and integration.

### Bug Helper Service Error Codes

- **400**: Invalid input parameters
  - Invalid bug_id format
  - Missing or invalid patch_path
- **404**: Resource not found
  - Handle not found
  - Redis key not found
  - Project not found
- **500**: Internal server errors
  - Redis connection issues
  - Process execution failures
  - Task management errors

### Unified Patch Service Error Codes

| Error Code | Description |
|------------|-------------|
| `err_extract_code_fail` | Failed to extract code from markdown |
| `err_invalid_bug_id_format` | Bug ID format is invalid (should be "project@sha") |
| `err_guidance_not_loaded` | Guidance data not loaded at startup |
| `err_bug_id_not_in_guidance` | Bug ID not found in guidance database |
| `err_record_not_found` | Metadata record not found |
| `err_src_content_not_cached` | Source file content not available in cache |
| `err_context_mismatch_byte_range` | Patch context doesn't match source file |
| `err_no_patch_content_identified` | Unable to identify patch content |
| `err_patch_file_creation_failed` | Failed to create patch file |

### Error Response Format

**Bug Helper Service:**
```json
{
  "detail": "Error message describing the issue"
}
```

**Unified Patch Service:**
```json
{
  "detail": {
    "error_code": "err_invalid_bug_id_format",
    "message": "bug_id must be 'project@sha', got: invalid_format"
  }
}
```

</details>

---

<details>
<summary><h2>⚙️ Configuration & Environment</h2></summary>

### Bug Helper Service Configuration

Environment variables and settings:
- Redis connection parameters
- Task timeout settings
- Logging configuration
- Project directory paths

### Unified Patch Service Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `SRC_DIR` | `/src` | Source directory for input data |
| `SRC_OUT` | `/out` | Output directory for results |
| `META_DIR` | `/src/projects` | Metadata directory |
| `PATCH_OUTPUT_DIR` | `/patches/` | Persistent patch output directory |
| `PATCH_OUTPUT_BEFORE_DIR` | `/tmp/patches_before` | Temporary patch directory |

### Data Loading (Patch Service)

The service loads several data sources at startup:

1. **Metadata**: Bug information from JSON files in `/src/projects/**`
2. **Guidance**: CSV file with function locations and metadata
3. **Source Content**: Source file contents from JSONL format
4. **Prompt Content**: LLM prompt templates with infill markers

</details>

---

<details>
