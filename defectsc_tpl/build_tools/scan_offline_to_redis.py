#!/usr/bin/env python3
"""
Load offline patch results from disk files into Redis cache.

This script scans for patch_<sha>_<md5>.{log,msg,status} files on disk
and loads them into Redis with the same key format used by the bug helper service.
Uses multiprocessing/threading for performance optimization.
"""

import os
import re
import json
import argparse
import time
import threading
from pathlib import Path
from typing import Dict, List, Tuple, Optional
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, ProcessPoolExecutor, as_completed
from functools import partial
import multiprocessing as mp

import redis


def read_file_limited(path: Path, max_lines: int = 100, max_tokens: int = 512, keep_tail: bool = True) -> str:
    """Read file with token/line limits (same as bug helper service)"""
    from collections import deque
    
    if not path.exists():
        return ""
    
    try:
        with path.open("r", encoding="utf-8", errors="ignore") as fh:
            lines = deque(fh, maxlen=max_lines)
        
        # Collapse to a single string and split on whitespace
        tokens = " ".join(line.rstrip("\n") for line in lines).split()
        
        if len(tokens) > max_tokens:
            tokens = tokens[-max_tokens:] if keep_tail else tokens[:max_tokens]
        
        return " ".join(tokens)
    except Exception as e:
        print(f"Error reading {path}: {e}")
        return ""


def parse_patch_filename(filename: str) -> Optional[Tuple[str, str]]:
    """
    Parse patch filename to extract SHA and MD5.
    Expected format: patch_<sha>_<md5>.<ext>
    Returns: (sha, md5) or None if not a patch file
    """
    match = re.match(r'^patch_([a-f0-9]+)_([a-f0-9]{32})\.(log|msg|status)$', filename)
    if match:
        return match.group(1), match.group(2)  # sha, md5
    return None


def scan_directory_chunk(log_dir: Path) -> Dict[str, Dict[str, Path]]:
    """
    Scan a single directory for patch files and group by redis_key.
    This function is designed to be called in parallel.
    """
    patch_groups = defaultdict(dict)
    
    if not log_dir.exists():
        return {}
    
    try:
        for file_path in log_dir.iterdir():
            if not file_path.is_file():
                continue
                
            parsed = parse_patch_filename(file_path.name)
            if not parsed:
                continue
                
            sha, md5 = parsed
            redis_key = f"patch_{sha}_{md5}.log"
            
            # Determine file type
            if file_path.suffix == '.log':
                patch_groups[redis_key]['log'] = file_path
            elif file_path.suffix == '.msg':
                patch_groups[redis_key]['msg'] = file_path
            elif file_path.suffix == '.status':
                patch_groups[redis_key]['status'] = file_path
        
        return dict(patch_groups)
    except Exception as e:
        print(f"Error scanning {log_dir}: {e}")
        return {}


def scan_patch_files_parallel(log_dirs: List[Path], max_workers: int = None) -> Dict[str, Dict[str, Path]]:
    """
    Scan multiple directories in parallel for patch files.
    """
    if max_workers is None:
        max_workers = min(len(log_dirs), mp.cpu_count())
    
    all_patch_groups = {}
    
    print(f"Scanning {len(log_dirs)} directories with {max_workers} workers...")
    
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        # Submit all directory scanning tasks
        future_to_dir = {
            executor.submit(scan_directory_chunk, log_dir): log_dir 
            for log_dir in log_dirs
        }
        
        # Collect results as they complete
        for future in as_completed(future_to_dir):
            log_dir = future_to_dir[future]
            try:
                patch_groups = future.result()
                all_patch_groups.update(patch_groups)
                
                file_count = sum(len(files) for files in patch_groups.values())
                print(f"✓ {log_dir}: {len(patch_groups)} groups ({file_count} files)")
                
            except Exception as e:
                print(f"✗ Error processing {log_dir}: {e}")
    
    return all_patch_groups


def determine_status_and_return_code(log_content: str, msg_content: str, status_content: str) -> Tuple[str, int]:
    """
    Determine the overall status and return code based on file contents.
    This mimics the logic from the bug helper service.
    """
    if not status_content:
        return "failed", 1
        
    # Look for obvious success indicators
    if "PASS" in status_content.upper() or "SUCCESS" in status_content.upper():
        return "completed", 0
    
    # Look for obvious failure indicators
    if "FAIL" in status_content.upper() or "ERROR" in status_content.upper():
        return "failed", 1
    
    # Check log content for error patterns
    error_patterns = [
        "compilation terminated",
        "error:",
        "fatal error:",
        "build failed",
        "make: *** [",
        "cmake error",
        "compilation failed"
    ]
    
    log_lower = log_content.lower()
    for pattern in error_patterns:
        if pattern in log_lower:
            return "failed", 1
    
    # If we have substantial content but no clear indicators, assume success
    # if len(log_content.strip()) > 50 or len(status_content.strip()) > 10:
    #     return "completed", 0
    
    # Default to failed if we can't determine
    return "failed", -1


def process_patch_group(redis_key: str, files: Dict[str, Path]) -> Tuple[str, Dict[str, str]]:
    """
    Process a single patch group to create cache entry.
    This function is designed to be called in parallel.
    """
    try:
        # Read file contents
        fix_log = read_file_limited(files.get('log')) if files.get('log') else ""
        fix_msg = read_file_limited(files.get('msg')) if files.get('msg') else ""
        fix_status = read_file_limited(files.get('status')) if files.get('status') else ""
        
        # Determine status and return code
        status, return_code = determine_status_and_return_code(fix_log, fix_msg, fix_status)
        
        # Create timestamp from file modification time (use most recent file)
        timestamp = 0
        for path in files.values():
            if path and path.exists():
                timestamp = max(timestamp, path.stat().st_mtime)
        
        cache_data = {
            "status": status,
            "return_code": str(return_code),
            "fix_log": fix_log,
            "fix_msg": fix_msg,
            "fix_status": fix_status,
            "error": "",
            "timestamp": str(timestamp)
        }
        
        return redis_key, cache_data
        
    except Exception as e:
        print(f"Error processing {redis_key}: {e}")
        return redis_key, None


def process_patch_groups_parallel(patch_groups: Dict[str, Dict[str, Path]], 
                                max_workers: int = None) -> Dict[str, Dict[str, str]]:
    """
    Process patch groups in parallel to create cache entries.
    """
    if max_workers is None:
        max_workers = min(len(patch_groups), mp.cpu_count() * 2)
    
    processed_data = {}
    
    print(f"Processing {len(patch_groups)} patch groups with {max_workers} workers...")
    
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        # Submit all processing tasks
        future_to_key = {
            executor.submit(process_patch_group, redis_key, files): redis_key
            for redis_key, files in patch_groups.items()
        }
        
        # Collect results with progress
        completed = 0
        for future in as_completed(future_to_key):
            try:
                redis_key, cache_data = future.result()
                if cache_data is not None:
                    processed_data[redis_key] = cache_data
                
                completed += 1
                if completed % 100 == 0:
                    print(f"  Processed {completed}/{len(patch_groups)} groups...")
                    
            except Exception as e:
                print(f"Error in parallel processing: {e}")
    
    return processed_data


def connect_redis(host: str = "localhost", port: int = 6379, db: int = 0, password: str = None) -> redis.Redis:
    """Connect to Redis server"""
    client = redis.Redis(
        host=host,
        port=port,
        db=db,
        password=password,
        decode_responses=True,
        socket_connect_timeout=5,
        socket_timeout=5
    )
    
    # Test connection
    try:
        client.ping()
        print(f"✓ Connected to Redis at {host}:{port}/{db}")
        return client
    except Exception as e:
        raise ConnectionError(f"Failed to connect to Redis: {e}")


def load_batch_to_redis(redis_client: redis.Redis, batch_data: List[Tuple[str, Dict[str, str]]], 
                       ttl: int = 86400, force: bool = False) -> Tuple[int, int]:
    """
    Load a batch of data to Redis.
    Returns: (loaded_count, skipped_count)
    """
    loaded_count = 0
    skipped_count = 0
    
    # Use pipeline for better performance
    pipe = redis_client.pipeline()
    
    for redis_key, cache_data in batch_data:
        try:
            # Check if key already exists (unless forcing)
            if not force and redis_client.exists(redis_key):
                skipped_count += 1
                continue
            
            # Add to pipeline
            pipe.hset(redis_key, mapping=cache_data)
            if ttl > 0:
                pipe.expire(redis_key, ttl)
            
            loaded_count += 1
            
        except Exception as e:
            print(f"Error preparing {redis_key}: {e}")
            continue
    
    # Execute pipeline
    if loaded_count > 0:
        pipe.execute()
    
    return loaded_count, skipped_count


def load_to_redis_parallel(redis_client: redis.Redis, processed_data: Dict[str, Dict[str, str]], 
                         ttl: int = 86400, dry_run: bool = False, force: bool = False,
                         batch_size: int = 100) -> Tuple[int, int]:
    """
    Load processed data to Redis in parallel batches.
    """
    total_loaded = 0
    total_skipped = 0
    
    # Convert to list for batching
    data_items = list(processed_data.items())
    
    if dry_run:
        for redis_key, cache_data in data_items[:10]:  # Show first 10 for dry run
            print(f"[DRY RUN] Would load {redis_key}: status={cache_data['status']}, return_code={cache_data['return_code']}")
        if len(data_items) > 10:
            print(f"[DRY RUN] ... and {len(data_items) - 10} more entries")
        return len(data_items), 0
    
    # Process in batches
    print(f"Loading {len(data_items)} entries to Redis in batches of {batch_size}...")
    
    for i in range(0, len(data_items), batch_size):
        batch = data_items[i:i + batch_size]
        
        try:
            loaded, skipped = load_batch_to_redis(redis_client, batch, ttl, force)
            total_loaded += loaded
            total_skipped += skipped
            
            print(f"  Batch {i//batch_size + 1}: {loaded} loaded, {skipped} skipped")
            
        except Exception as e:
            print(f"Error loading batch {i//batch_size + 1}: {e}")
    
    return total_loaded, total_skipped


def save_to_jsonl_parallel(processed_data: Dict[str, Dict[str, str]], 
                          patch_groups: Dict[str, Dict[str, Path]], 
                          output_file: Path, max_workers: int = None):
    """Save processed data to JSONL file"""
    
    if max_workers is None:
        max_workers = min(4, mp.cpu_count())  # IO bound, don't need too many workers
    
    def create_jsonl_entry(redis_key: str) -> str:
        try:
            cache_data = processed_data.get(redis_key)
            files = patch_groups.get(redis_key, {})
            
            if not cache_data:
                return None
            
            entry = {
                "redis_key": redis_key,
                "files": {k: str(v) for k, v in files.items() if v},
                "cache_data": cache_data
            }
            
            return json.dumps(entry)
            
        except Exception as e:
            print(f"Error creating JSONL entry for {redis_key}: {e}")
            return None
    
    print(f"Saving {len(processed_data)} entries to JSONL with {max_workers} workers...")
    
    with output_file.open('a') as f:
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            # Submit all tasks
            futures = [executor.submit(create_jsonl_entry, redis_key) 
                      for redis_key in processed_data.keys()]
            
            # Write results as they complete
            written = 0
            for future in as_completed(futures):
                try:
                    jsonl_line = future.result()
                    if jsonl_line:
                        f.write(jsonl_line + '\n')
                        written += 1
                        
                        if written % 1000 == 0:
                            print(f"  Written {written} entries...")
                            
                except Exception as e:
                    print(f"Error writing JSONL entry: {e}")
    
    print(f"✓ Saved {written} entries to {output_file}")


def main():
    parser = argparse.ArgumentParser(description="Load offline patch results into Redis cache (parallel version)")
    parser.add_argument("log_dirs", nargs="+", help="Directories containing patch files")
    parser.add_argument("--redis-host", default="localhost", help="Redis host")
    parser.add_argument("--redis-port", type=int, default=6379, help="Redis port")
    parser.add_argument("--redis-db", type=int, default=0, help="Redis database")
    parser.add_argument("--redis-password", help="Redis password")
    parser.add_argument("--ttl", type=int, default=0, help="TTL for cache entries (seconds, 0=no expiry)")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be loaded without actually loading")
    parser.add_argument("--force", action="store_true", help="Overwrite existing keys")
    parser.add_argument("--jsonl-output",  default="jsonl_output.jsonl", help="Save data to JSONL file")
    parser.add_argument("--scan-workers", type=int, default=os.cpu_count()-1, help="Number of workers for directory scanning")
    parser.add_argument("--process-workers", type=int,default=os.cpu_count()-1, help="Number of workers for file processing")
    parser.add_argument("--batch-size", type=int, default=100, help="Batch size for Redis operations")
    
    args = parser.parse_args()
    
    start_time = time.time()
    
    # Convert string paths to Path objects
    log_dirs = [Path(d) for d in args.log_dirs]
    
    # Step 1: Scan directories in parallel
    print("=== Phase 1: Scanning directories ===")
    scan_start = time.time()
    all_patch_groups = scan_patch_files_parallel(log_dirs, args.scan_workers)
    scan_time = time.time() - scan_start
    
    total_files = sum(len(files) for files in all_patch_groups.values())
    print(f"✓ Scan complete: {len(all_patch_groups)} unique patch groups, {total_files} files ({scan_time:.2f}s)")
    #
    
    if not all_patch_groups:
        print("No patch files found!")
        return 1
    
    # Step 2: Process files in parallel
    print("\n=== Phase 2: Processing files ===")
    process_start = time.time()
    processed_data = process_patch_groups_parallel(all_patch_groups, args.process_workers)
    process_time = time.time() - process_start
    
    
    print(f"✓ Processing complete: {len(processed_data)} entries ready ({process_time:.2f}s)")
    
    # Step 3: Save to JSONL if requested
    if args.jsonl_output:
        print("\n=== Phase 3: Saving to JSONL ===")
        jsonl_start = time.time()
        save_to_jsonl_parallel(processed_data, all_patch_groups, Path(args.jsonl_output))
        jsonl_time = time.time() - jsonl_start
    #     print(f"✓ JSONL save complete ({jsonl_time:.2f}s)")
    
    # Step 4: Load to Redis
    # print("\n=== Phase 4: Loading to Redis ===")
    # try:
    #     redis_client = connect_redis(
    #         host=args.redis_host,
    #         port=args.redis_port,
    #         db=args.redis_db,
    #         password=args.redis_password
    #     )
    #
    #     redis_start = time.time()
    #     loaded_count, skipped_count = load_to_redis_parallel(
    #         redis_client, 
    #         processed_data, 
    #         ttl=args.ttl,
    #         dry_run=args.dry_run,
    #         force=args.force,
    #         batch_size=args.batch_size
    #     )
    #     redis_time = time.time() - redis_start
    #
    #     print(f"✓ Redis load complete: {loaded_count} loaded, {skipped_count} skipped ({redis_time:.2f}s)")
    #
    # except Exception as e:
    #     print(f"Error with Redis operations: {e}")
    #     return 1
    
    total_time = time.time() - start_time
    print(f"\n=== Summary ===")
    print(f"Total time: {total_time:.2f}s")
    print(f"  Scanning: {scan_time:.2f}s")
    print(f"  Processing: {process_time:.2f}s")
    # print(f"  Redis: {redis_time:.2f}s")
    if args.jsonl_output:
        print(f"  JSONL: {jsonl_time:.2f}s")
    print(f"Performance: {len(processed_data)/total_time:.1f} entries/sec")
    
    return 0


if __name__ == "__main__":
    exit(main())