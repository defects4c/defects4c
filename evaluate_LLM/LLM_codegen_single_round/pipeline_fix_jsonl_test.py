import os 
import json
import asyncio
import aiohttp
import time
from pathlib import Path
from typing import Dict, Any, Optional, List
import logging
from pathlib import Path
import re
import pandas as pd
from tqdm import tqdm 
import hashlib
import traceback

from collections import defaultdict

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


URL_RE = re.compile(r"repos/(?P<owner>[^/]+)/(?P<repo>[^/]+)/commits/(?P<sha>[0-9a-f]{7,40})",
                    re.I)

SHA_META_DICT = {}
def load_meta_sha_with_project(  ):
    global SHA_META_DICT 
    def parse_url(url: str):
        m = URL_RE.search(url or "")
        if not m:
            return None, None
        return f"{m.group('owner')}___{m.group('repo')}", m.group('sha')
    def load_raw_info_pandas(csv_path: str | Path = "../data/raw_info_step1.csv"):
        csv_path = Path(csv_path).expanduser()
        if not csv_path.is_file():
            raise FileNotFoundError(csv_path)
        df = pd.read_csv(csv_path)
        df["url_src"] = df["api_url"].fillna(df["github"])
        df[["project", "sha"]] = df["url_src"].apply(
            lambda u: pd.Series(parse_url(u))
        )
        # df.loc[df["project"] == "llvm___llvm-project", "project"] = "llvm___llvm-project.git"
        df = df.dropna(subset=["sha"])
        sha_to_project = pd.Series(df.project.values, index=df.sha).to_dict()
        return sha_to_project 
    sha_to_row =  load_raw_info_pandas()
    SHA_META_DICT.update(  sha_to_row )
    return  len( SHA_META_DICT )
 

    
class BugFixPipeline:
    def __init__(self, base_url: str, max_concurrent: int = 10):
        self.base_url = base_url.rstrip('/')
        self.max_concurrent = max_concurrent
        self.semaphore = asyncio.Semaphore(max_concurrent)
        self.result_lock = asyncio.Lock()  # For thread-safe file writing
        
    
    async def build_patch(
        self,
        session: aiohttp.ClientSession,
        bug_id: str,
        llm_response: str,
        retries: int = 4,
        poll_interval: int = 5,
    ) -> Dict[str, Any]:
        """Build patch from LLM response"""
        payload = {
            "bug_id": bug_id,
            "llm_response": llm_response,
            "method": "direct",
            "generate_diff": True,
            "persist_flag": True,
        }

        try:
            for attempt in range(retries):
                async with session.post(f"{self.base_url}/build_patch", json=payload) as response:
                    # Immediate failure on markdown extraction errors
                    if response.status == 400:
                        error_text = await response.text()
                        if "markdown extract fail" in error_text:
                            return {"success": False, "error": f"HTTP {response.status}: {error_text}"}

                    # Any non-200 status: retry if we have attempts left
                    if response.status != 200:
                        if attempt + 1 < retries:
                            await asyncio.sleep(poll_interval)
                            continue
                        # no retries left
                        error_text = await response.text()
                        return {"success": False, "error": f"HTTP {response.status}: {error_text}"}

                    # Success!
                    return await response.json()

            # Shouldn't get here, but just in case
            return {"success": False, "error": "Exceeded retry limit without response"}

        except Exception:
            return {"success": False, "error": traceback.format_exc()}



    

    async def submit_fix(self, session: aiohttp.ClientSession, bug_id: str, patch_path: str) -> Dict[str, Any]:
        """Submit fix request and get handle, retrying up to 3 times on non-200/400 statuses."""
        payload = {
            "bug_id": bug_id,
            "patch_path": patch_path
        }

        last_error: str = ""
        for attempt in range(1, 4):  # attempts 1, 2, 3
            try:
                async with session.post(f"{self.base_url}/fix2", json=payload) as response:
                    if response.status == 200:
                        data = await response.json()
                        return {"success": True, "handle": data.get("handle")}
                    if response.status == 400:
                        error_text = await response.text()
                        return {"success": False, "error": f"HTTP 400: {error_text}"}
                    # otherwise, record and retry
                    last_error = f"HTTP {response.status}"
            except Exception:
                last_error = traceback.format_exc()
                break  # don't retry on exceptions

        # if we get here, all retries failed
        return {
            "success": False,
            "error": f"{last_error} after {attempt} attempt{'s' if attempt > 1 else ''}"
        }




    async def poll_status(self, session: aiohttp.ClientSession, handle: str, 
                         max_wait_time: int = 3600, poll_interval: int = 10) -> Dict[str, Any]:
        """Poll status until completion or timeout"""
        start_time = time.time()
        
        while time.time() - start_time < max_wait_time:
            try:
                async with session.get(f"{self.base_url}/status/{handle}") as response:
                    if response.status != 200:
                        error_text = await response.text()
                        return {"success": False, "error": f"HTTP {response.status}: {error_text}"}
                    
                    status_data = await response.json()
                    # print("status_data  ", status_data )
                    
                    current_status = status_data.get("status", "unknown")
                    
                    # logger.info(f"Handle {handle}: Status = {current_status}")
                    
                    if current_status == "completed":
                        return {"success": True, "status_data": status_data}
                    elif current_status in ["failed", "error"]:
                        return {"success": False, "status_data":status_data} # ,"error": f"Fix failed with status: {current_status}", "status_data": status_data}
                    
                    await asyncio.sleep(poll_interval)
                    
            except Exception as e:
                logger.error(f"Error polling status for handle {handle}: {e}, retrying...")
                await asyncio.sleep(poll_interval)
        
        return {"success": False, "error": "Timeout waiting for completion"}
    
    async def write_result_to_file(self, output_file: Path, result: Dict[str, Any]):
        """Thread-safe writing of results to file"""
        async with self.result_lock:
            with open(output_file, 'a') as f:  # Use append mode
                f.write(json.dumps(result) + '\n')
                f.flush()  # Ensure data is written immediately
    
    async def process_single_task(self, session: aiohttp.ClientSession, task: Dict[str, Any], 
                                 output_file: Path, task_index: int, total_tasks: int) -> Dict[str, Any]:
        """Process a single task through the entire pipeline"""
        async with self.semaphore:
            task_id = task.get("task_id", "unknown")
            bug_id = task.get("bug_id", "")
            llm_response = task.get("llm_response", "")
            
            # logger.info(f"Processing task {task_index + 1}/{total_tasks}: {task_id} for bug {bug_id}")
            
            result = {
                "task_id": task_id,
                "llm_md5": task.get("llm_md5", None),
                "patch_status": "failed",
                "patch_msg": "Unknown error"
            }
            
            try:
                # Step 1: Build patch
                # logger.info(f"Task {task_id}: Building patch...")
                patch_result = await self.build_patch(session, bug_id, llm_response)
                
                if not patch_result.get("success", False):
                    result["patch_msg"] = f"Patch build failed: {patch_result.get('error', 'Unknown error')}"
                    await self.write_result_to_file(output_file, {**task,**result})
                    return result
                
                fix_p = patch_result.get("fix_p")
                if not fix_p:
                    result["patch_msg"] = "Patch build succeeded but no fix_p returned"
                    await self.write_result_to_file(output_file, {**task, **result} )
                    return result
                
                # logger.info(f"Task {task_id}: Patch built successfully, fix_p: {fix_p}")
                
                # Step 2: Submit fix
                # logger.info(f"Task {task_id}: Submitting fix...")
                fix_result = await self.submit_fix(session, bug_id, fix_p)
                if "handle" in fix_result :
                
                    handle = fix_result["handle"]
                    # logger.info(f"Task {task_id}: Fix submitted, handle: {handle}")
                    
                    # Step 3: Poll status
                    # logger.info(f"Task {task_id}: Polling status...")
                    status_result = await self.poll_status(session, handle)
                    
                    # Update result with final status
                    result["patch_status"] = "completed"
                    result["handle"] = handle
                    result["status_data"] = status_result.get("status_data", {})
                    result["status_err"] = status_result.get("error", None)
                    # logger.info(f"Task {task_id}: Completed successfully")

            except Exception as e:
                e= traceback.format_exc()
                result["patch_msg"] = f"internal Error, Unexpected error: {str(e)}"
                logger.error(f"Task {task_id}: Unexpected error - {e}")
            
            # Write result immediately after completion
            await self.write_result_to_file(output_file, {**task,**result} )
            # logger.info(f"Task {task_index + 1}/{total_tasks} completed and saved: {task_id}")
            
            return result
    
    async def process_jsonl_file(self, input_file: str, output_file: str, 
                                timeout_per_request: int = 3600) -> None:
        """Process entire JSONL file through the pipeline"""
        output_path = Path(output_file)
        
        # Clear the output file at the start
        # with open(output_path, 'a') as f:
        #     pass  # Just create/clear the file
        
        if type(input_file)==str and input_file.endswith(".jsonl"):
            input_path = Path(input_file)
            
            if not input_path.exists():
                raise FileNotFoundError(f"Input file not found: {input_file}")
            
            # Read all tasks
            tasks = defaultdict(list)
            with open(input_path, 'r') as f:
                for line_num, line in enumerate(f, 1):
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        task = json.loads(line)
                        # if "task_id" not in task:
                        #     task["task_id"] = f"task_{line_num}"
                        task_id = task["task_id"]
                        sha = task_id[:40]
                        if  sha not in SHA_META_DICT :
                            continue 
                        project_name = SHA_META_DICT[sha]
                        bug_id = f"{project_name}@{sha}"
                        
                        content = task["completion"]
                        if task.get("stop_reason","stop")=="stop" :
                            if  "```" in content and content.count("```")==1:
                                content = content+"\n```\n"
                            elif content.count("```")==0 and content :
                                content = "```cpp\n{}\n```\n".format( content )
                        # 9497680067cc5a2e7d4e0bf657b23d57c06e5e97___ConstraintSystem.h@41@686
                        task = {"task_id":task_id , #os.path.abspath(path_name),
                                "bug_id":bug_id,
                                "llm_response":content, #open()
                                "llm_md5":task.get("llm_md5", md5(content) ),
                            }
                        if task_id not in tasks :
                            tasks[task_id] = []
                        tasks[task_id].append(task)
                        if len(tasks[task_id]) > MAX_TASK_LEN:
                            tasks[task_id].pop()
                    except json.JSONDecodeError as e:
                        logger.error(f"Error parsing line {line_num}: {e}")
                        continue
        else:
            assert type(input_file) == list 
            assert all ( [os.path.isfile(x) for x in input_file])
            # Read all tasks
            tasks = []
            invalid_sha_list= set()
            for line_num, path_name in tqdm( enumerate(input_file, 1)) :
                path_name_base = os.path.basename(path_name)
                assert path_name_base.count("@")==2 , path_name_base
                sha = path_name_base[:40]
                assert path_name_base[41] == "_", path_name_base 
                
                if not (sha  in SHA_META_DICT and   os.path.isfile(path_name) ):
                    invalid_sha_list.add(sha)
                    # print ("{}: invalide_sha: {}, SHA_META_DICT.len {} , sha is SHA_META_DICT= {} and os.path.isfile(path_name) {}".format(path_name,len(invalid_sha_list), len(SHA_META_DICT),  sha  in SHA_META_DICT, os.path.isfile(path_name) ))
                    continue 
                project_name = SHA_META_DICT[sha]
                bug_id = f"{project_name}@{sha}"
                # 9497680067cc5a2e7d4e0bf657b23d57c06e5e97___ConstraintSystem.h@41@686
                content =open(path_name).read()
                task = {"task_id":path_name , #os.path.abspath(path_name),
                        "bug_id":bug_id,
                        "llm_response":content, #open()
                        "llm_md5":md5(content),
                    }
                task_id = task["task_id"]
                if task_id not in tasks :
                    tasks[task_id] = []
                tasks[task_id].append(task)
                if len(tasks[task_id]) > MAX_TASK_LEN:
                    tasks[task_id].pop()
                #tasks.append(task)

        tasks = [
            t
            for task_list in tasks.values()
            for t in task_list
        ]
        logger.info (f"loading total {len(tasks)}")
        tasks =  [x for x in tasks if get_key(x) not  in valid_llm_md5 ]
        logger.info(f"after filter out exist valid_llm_md5, the remain is {len(tasks)} tasks from {input_file}")

        tasks =  [x for x in tasks if x["task_id"]   in valid_task_id  ]
        task_id_uniq = set([x["task_id"] for x in tasks])
        logger.info(f"valid task_id[{len(valid_task_id)} ], Loaded {len(tasks)} tasks(uniq {len(task_id_uniq)}) from {input_file}")
        
        # Process tasks
        connector = aiohttp.TCPConnector(limit=self.max_concurrent * 2)
        timeout = aiohttp.ClientTimeout(total=timeout_per_request)
        
        async with aiohttp.ClientSession(connector=connector, timeout=timeout) as session:
            # Create tasks with immediate result saving
            task_coroutines = [
                self.process_single_task(session, task, output_path, i, len(tasks)) 
                for i, task in enumerate(tasks)
            ]
            
            # Process all tasks concurrently with exception handling
            completed_count = 0
            failed_count = 0
            
            for coro in asyncio.as_completed(task_coroutines):
                try:
                    result = await coro
                    if result.get("patch_status") == "completed" and "status_data" in result and "fix_status" in result["status_data"] and "success" in str(result["status_data"]).lower():
                        completed_count += 1
                    else:
                        failed_count += 1
                    # Log progress
                    total_processed = completed_count + failed_count
                    logger.info(f"Progress: {total_processed}/{len(tasks)} tasks processed "
                              f"(Completed: {completed_count}, Failed: {failed_count})")
                    
                except Exception as e:
                    failed_count += 1
                    logger.error(f"Unhandled exception in task processing: {e}")
                    
                    # Write error result for unhandled exceptions
                    error_result = {
                        "task_id": "unknown",
                        "patch_status": "failed",
                        "patch_msg": f"Unhandled exception: {str(e)}"
                    }
                    await self.write_result_to_file(output_path, {**task, **error_result} )
        
        logger.info(f"Processing complete. Results saved to {output_file}")
        logger.info(f"Final stats - Completed: {completed_count}, Failed: {failed_count}, Total: {len(tasks)}")

def run_pipeline(base_url: str, input_file: str, output_file: str, 
                max_concurrent: int = 10, timeout_per_request: int = 3600):
    """Main function to run the pipeline"""
    pipeline = BugFixPipeline(base_url, max_concurrent)
    
    try:
        asyncio.run(pipeline.process_jsonl_file(input_file, output_file, timeout_per_request))
    except KeyboardInterrupt:
        logger.info("Pipeline interrupted by user")
    except Exception as e:
        logger.error(f"Pipeline failed: {e}")
        raise


def md5(text: str) -> str:
    return hashlib.md5(text.strip().lower().encode()).hexdigest()


def identify_item_pass_status( result ):
    x_pass = False 
    msg_code = 0 
    if  "status_data" in result and "fix_status" in result["status_data"] :
        if "success" in str(result["status_data"]["fix_status"]).lower():
            return {"pass" : True ,"code":"pass"}
        elif "fail" in str(result["status_data"]["fix_status"]).lower():
            return {"pass" : False ,"code":"test_fail"}

    if "patch_msg" in result and ("HTTP 400:" in  result["patch_msg"]  and "markdown extract fail" in  result["patch_msg"]  ):
        return  {"pass" : False ,"code":"markdown_fail"}
    if "status_data" in result and "fix_status" in result["status_data"] and (result["status_data"]["fix_status"] =="" or result["status_data"]["fix_status"] is None ) :
        fix_log = result["status_data"].get("fix_log","")
        return {"pass":False , "code": "compile_fail"}

    if "status_data" in result and  "error" in result["status_data"] and "fix_status" not in result["status_data"]:
        err_str = result["status_data"] ["error"]
        if "/src/defects4c_api_" in err_str and "timed out after" in err_str :
            return {"pass":False , "code": "timeout_api"}

get_key =lambda x: "{}__{}".format(x["task_id"],x["llm_md5"] )

# Example usage
if __name__ == "__main__":
    from glob2 import glob 
    import random 
    import sys
    # random.seed(10)
    MAX_TASK_LEN = 100 
    
    load_meta_sha_with_project()
    
    # Example configuration
    # exit()
    BASE_URL = "http://10.96.177.54:43210"

    scan_dir="./outputs"
    #INPUT_FILE_list = glob(os.path.join(scan_dir,"*.jsonl"))
    #print ("total_scan", len(INPUT_FILE_list) )
    # INPUT_FILE = "input_tasks.jsonl"    # Input file with task_id, bug_id, llm_response
    MAX_CONCURRENT = os.cpu_count()-1                  # Maximum concurrent requests
    TIMEOUT_PER_REQUEST = 60*5         # Timeout per request in seconds (1 hour)

    
    # Run the pipeline
    INPUT_FILE  = sys.argv[-1]
    assert os.path.isfile( INPUT_FILE ), INPUT_FILE
    assert INPUT_FILE.endswith(".jsonl"), INPUT_FILE
    OUTPUT_FILE =os.path.join( "local_results", os.path.basename(INPUT_FILE)+".result.jsonl")       # Output file with task_id, patch_status, patch_msg


    ## if exist :
    valid_task_id = set()
    with open("../data/prompts/buggy_errmsg/single_function_allinone.saved.jsonl") as fr :
        lines =  [json.loads(x)["idx"] for x in fr.readlines()]
        valid_task_id = set(lines)

    valid_llm_md5 = set()
    if os.path.isfile(OUTPUT_FILE ):
        with open(OUTPUT_FILE) as fr:
            exist_lines = [json.loads(x) for x in fr.readlines()]
            #valid_llm_md5 = [x["llm_md5"] for x in exist_lines if "status_data" in x or ("patch_msg" in x and ("Patch build failed: HTTP 400" in x["patch_msg"] and "markdown extract fail" in x["patch_msg"] )  ) ]
            valid_llm_md5= [get_key(x) for x in  exist_lines  if identify_item_pass_status(x) is not None ]

            valid_llm_md5 = set(valid_llm_md5 )

    print ("exist... ", len(valid_llm_md5) )
    print ("reading ", INPUT_FILE)
    run_pipeline(BASE_URL, INPUT_FILE, OUTPUT_FILE, MAX_CONCURRENT, TIMEOUT_PER_REQUEST)
    
