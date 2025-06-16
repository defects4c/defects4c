#!/usr/bin/env python3
"""
Load processed JSONL data into Redis cache using a streaming, parallel loader.

This script reads entries from a large JSONL file (with fields `redis_key` and `cache_data`),
streams them in batches, and loads into Redis via a thread pool without exceeding a specified worker count.
"""
import json
import time
import argparse
from pathlib import Path
from typing import Dict, Tuple, List, Iterator

import redis
from concurrent.futures import ThreadPoolExecutor


def connect_redis(host: str, port: int, db: int, password: str = None) -> redis.Redis:
    """Connect to Redis server and verify the connection."""
    client = redis.Redis(
        host=host,
        port=port,
        db=db,
        password=password,
        decode_responses=True,
        socket_connect_timeout=5,
        socket_timeout=5,
    )
    client.ping()
    print(f"✓ Connected to Redis at {host}:{port}/{db}")
    return client


def load_batch_to_redis(
    client: redis.Redis,
    batch: List[Tuple[str, Dict[str, str]]],
    ttl: int,
    force: bool,
) -> Tuple[int, int]:
    """Load a single batch of entries into Redis."""
    loaded = skipped = 0
    pipe = client.pipeline()
    for key, data in batch:
        if not force and client.exists(key):
            skipped += 1
            continue
        pipe.hset(key, mapping=data)
        if ttl > 0:
            pipe.expire(key, ttl)
        loaded += 1
    if loaded:
        pipe.execute()
    return loaded, skipped


def stream_jsonl_batches(
    file_path: Path,
    batch_size: int
) -> Iterator[List[Tuple[str, Dict[str, str]]]]:
    """
    Stream JSONL file and yield batches of parsed entries:
    each entry is a tuple (redis_key, cache_data).
    """
    batch: List[Tuple[str, Dict[str, str]]] = []
    with file_path.open('r', encoding='utf-8') as fh:
        for line in fh:
            try:
                obj = json.loads(line)
                key = obj.get('redis_key')
                data = obj.get('cache_data')
                if key and data:
                    batch.append((key, data))
            except json.JSONDecodeError:
                continue
            if len(batch) >= batch_size:
                yield batch
                batch = []
    if batch:
        yield batch


def main():
    parser = argparse.ArgumentParser(
        description="Stream a large JSONL file into Redis with parallel batches"
    )
    parser.add_argument(
        "jsonl_file", help="Path to JSONL file (e.g. jsonl_output.jsonl)"
    )
    parser.add_argument("--redis-host", default="localhost", help="Redis host")
    parser.add_argument("--redis-port", type=int, default=6379, help="Redis port")
    parser.add_argument("--redis-db", type=int, default=0, help="Redis DB number")
    parser.add_argument("--redis-password", default=None, help="Redis password")
    parser.add_argument(
        "--ttl", type=int, default=0,
        help="TTL for keys in seconds (0 = no expiry)",
    )
    parser.add_argument(
        "--force", action="store_true",
        help="Overwrite existing keys in Redis"
    )
    parser.add_argument(
        "--batch-size", type=int, default=1000,
        help="Number of entries per batch"
    )
    parser.add_argument(
        "--workers", type=int, default= min(4, ( __import__('multiprocessing').cpu_count())),
        help="Max number of parallel workers"
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Show first few entries without loading to Redis"
    )
    args = parser.parse_args()

    file_path = Path(args.jsonl_file)
    if not file_path.is_file():
        print(f"Error: file not found: {file_path}")
        return 1

    if args.dry_run:
        # Show only first 10 entries
        print("[DRY RUN] Sample entries:")
        count = 0
        for batch in stream_jsonl_batches(file_path, args.batch_size):
            for key, data in batch:
                print(f"[DRY RUN] {key}: status={data.get('status')}, return_code={data.get('return_code')}")
                count += 1
                if count >= 10:
                    return 0
        return 0

    client = connect_redis(
        host=args.redis_host,
        port=args.redis_port,
        db=args.redis_db,
        password=args.redis_password,
    )
    start = time.time()
    total_loaded = total_skipped = 0
    batch_index = 0

    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        # submit tasks as batches stream in
        futures = []
        for batch in stream_jsonl_batches(file_path, args.batch_size):
            batch_index += 1
            futures.append(
                executor.submit(
                    load_batch_to_redis,
                    client,
                    batch,
                    args.ttl,
                    args.force
                )
            )
        # collect results
        for idx, future in enumerate(futures, start=1):
            try:
                loaded, skipped = future.result()
                total_loaded += loaded
                total_skipped += skipped
                if idx % 10 == 0 or idx == len(futures):
                    print(
                        f"Batch {idx}/{len(futures)}: {loaded} loaded, {skipped} skipped"
                    )
            except Exception as e:
                print(f"Error in batch {idx}: {e}")

    elapsed = time.time() - start
    print(f"\n✓ All done: {total_loaded} loaded, {total_skipped} skipped in {elapsed:.2f}s")
    return 0


if __name__ == "__main__":
    exit(main())
