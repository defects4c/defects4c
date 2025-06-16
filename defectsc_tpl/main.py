from pathlib import Path
import glob, os 

from fastapi import FastAPI
import  extract_patch_with_integrating  as extract_imp
#import ROOT_SRC,load_metadata, load_guidance,load_src_content, load_prompt_list ,load_prefix_suffix_meta 
from extract_patch_with_integrating import  app as extract_app

#from defects4c_api import app as defects4c_app
from defects4c_api_merged import app as defects4c_app
from defects4c_api_merged_nothit import app as defects4c_app_nohit

# Create the main FastAPI application
app = FastAPI(
    title="Combined Patch Service",
    version="1.0.0",
    description="Combined service from file1.py and file2.py"
)

# Mount the sub-applications

app.include_router(defects4c_app_nohit.router, tags=["bug-hlper-hit"])
app.include_router(defects4c_app.router,  tags=["bug-helper"])
app.include_router(extract_app.router, tags=["patch-service"])


# Optional: Add health check endpoint
@app.get("/health")
async def health_check():
    return {"status": "healthy"}

# ───────────────────── startup: load all data ─────────────



HERE = Path(__file__).resolve().parent

#@app.on_event("startup")
def init_data():
    meta_paths = (
        glob.glob( os.path.join(str(extract_imp. ROOT_SRC),  "projects/**/bug*.json" ), recursive=True) +
        glob.glob( os.path.join(str(extract_imp. ROOT_SRC), "projects_v1/**/bug*.json" ), recursive=True)
    )
    role = "buggy_errmsg"
    raw_prefix_dirs = [
        HERE / f"./data/{role}/single_function_repair.json",
        HERE / f"./data/{role}/single_function_single_hunk_repair.json",
        HERE / f"./data/{role}/single_function_single_line_repair.json",
        HERE / f"./data/{role}_cve/single_function_repair.json",
        HERE / f"./data/{role}_cve/single_function_single_hunk_repair.json",
        HERE / f"./data/{role}_cve/single_function_single_line_repair.json",
        ]

    print(f"startup: scanning {len(meta_paths)} metadata files")
    prefix= 0
    p = []
    m = extract_imp.load_metadata(meta_paths)
    g = extract_imp.load_guidance(str(HERE / "./data/raw_info_step1.csv"))
    s = extract_imp.load_src_content(str(HERE / "./data/github_src_path.jsonl"))
    p = extract_imp.load_prompt_list(str(HERE / "./data/single_function_allinone.saved.jsonl"))
    
    prefix  = extract_imp.load_prefix_suffix_meta( prefix_dirs=raw_prefix_dirs )
    print(f"[startup] metadata={m}, guidance={g}, src_content={s}, prompt_len={p}, prefix={prefix} ")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=80, reload=True)

