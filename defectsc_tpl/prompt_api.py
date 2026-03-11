from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse  # Add this import
import os
import re
import pandas as pd
import random
from pathlib import Path
import  extract_patch_with_integrating  as extract_imp
import openai
from pydantic import BaseModel


app = FastAPI()

PROMPT_DATA = {}
HERE = Path(__file__).parent


openai_api_key =  os.getenv("OPENAI_API_KEY")
#MODELNAME="qwen2.5:7b-instruct-q4_K_M"
MODELNAME="deepseek-chat"


class CodeFixRequest(BaseModel):
    code: str
    feedback: str = ""
    model: str = MODELNAME

class LLMDebugger:
    @staticmethod
    def get_debug_prompt(code: str, error_message: str) -> str:
        return f"""
Please analyze the following C/C++ code and fix the error:

ERROR MESSAGE:
{error_message}

CODE:
{code}

Please provide your response in the following format:
<fixed_code>
[Your fixed code here]
</fixed_code>

<explanation>
[Explanation of what was wrong and how you fixed it]
</explanation>

<changes_made>
- Change 1
- Change 2
- etc.
</changes_made>
"""

    @staticmethod
    def fix_code_with_qwen3_14b(code: str, error_message: str, stream: bool = False):
        if not openai:
            return {
                "fixed_code": code,
                "explanation": "OpenAI library not available",
                "changes_made": []
            }
            
        try:
            #client = openai.OpenAI(api_key=openai_api_key, base_url="https://api-inference.bitdeer.ai/api/inference/v1/")
            #client = openai.OpenAI(api_key=openai_api_key, base_url="http://10.96.177.54:50103/v1/")
            #client = openai.OpenAI(api_key=openai_api_key, base_url="https://api.deepseek.com/")
            client = openai.OpenAI(api_key=openai_api_key)
            prompt = LLMDebugger.get_debug_prompt(code, error_message)
            
            if stream:
                return client.chat.completions.create(
                    model=MODELNAME,
                    messages=[
                        {"role": "system", "content": "You are an expert C/C++ debugger."},
                        {"role": "user", "content": prompt}
                    ],
                    temperature=0.7,
                    max_tokens=4096,
                    stream=True,
    extra_body={
        "top_k": 20, 
 #       "chat_template_kwargs": {"enable_thinking": False},
    },

                )
            
            response = client.chat.completions.create(
                model=MODELNAME,
                messages=[
                    {"role": "system", "content": "You are an expert C/C++ debugger."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.7,
                max_tokens=4096,
    extra_body={
        "top_k": 20, 
 #       "chat_template_kwargs": {"enable_thinking": False},
    },

            )
            content = response.choices[0].message.content
            
            # Parse the response
            fixed_code = ""
            explanation = ""
            changes_made = []
            
            fixed_start = content.find('<fixed_code>')
            fixed_end = content.find('</fixed_code>')
            if fixed_start != -1 and fixed_end != -1:
                fixed_code = content[fixed_start + 12:fixed_end].strip()
            
            exp_start = content.find('<explanation>')
            exp_end = content.find('</explanation>')
            if exp_start != -1 and exp_end != -1:
                explanation = content[exp_start + 13:exp_end].strip()
            
            changes_start = content.find('<changes_made>')
            changes_end = content.find('</changes_made>')
            if changes_start != -1 and changes_end != -1:
                changes_text = content[changes_start + 14:changes_end].strip()
                changes_made = [line.strip().lstrip('- ').lstrip('• ') 
                              for line in changes_text.split('\n') 
                              if line.strip()]
            
            return {
                "fixed_code": fixed_code or code,
                "explanation": explanation or "No explanation provided",
                "changes_made": changes_made
            }
            
        except Exception as e:
            return {
                "fixed_code": code,
                "explanation": f"Error using Qwen3: {str(e)}",
                "changes_made": []
            }

'''
@app.on_event("startup")
async def startup_event():
    """Load the prompt data on startup"""
    global PROMPT_DATA
    try:
        # Load the prompt list using your existing function
        prompt_count = extract_imp.load_prompt_list(str(HERE / "./data/single_function_allinone.saved.jsonl"))
        PROMPT_DATA = extract_imp.PROMPT_CONTENT
        PROMPT_DATA_v = list(PROMPT_DATA.values())
        PROMPT_DATA_v = {x["idx"]:x for x in PROMPT_DATA_v}
        PROMPT_DATA = PROMPT_DATA_v
        print(f"Loaded {prompt_count} prompts on startup")
    except Exception as e:
        print(f"Failed to load prompts on startup: {e}")
'''


SHA_META_DICT = {}
@app.on_event("startup")
async def startup_event():

    URL_RE = re.compile(r"repos/(?P<owner>[^/]+)/(?P<repo>[^/]+)/commits/(?P<sha>[0-9a-f]{7,40})", re.I)

    """Load SHA to project mapping from CSV data"""
    global SHA_META_DICT
    
    def parse_url(url: str):
        m = URL_RE.search(url or "")
        if not m:
            return None, None
        return f"{m.group('owner')}___{m.group('repo')}", m.group('sha')
    
    def load_raw_info_pandas(csv_path: str | Path = "./data/raw_info_step1.csv"):
        csv_path = Path(csv_path).expanduser()
        if not csv_path.is_file():
            raise FileNotFoundError(csv_path)
        df = pd.read_csv(csv_path)
        df["url_src"] = df["api_url"].fillna(df["github"])
        df[["project", "sha"]] = df["url_src"].apply(
            lambda u: pd.Series(parse_url(u))
        )
        df = df.dropna(subset=["sha"])
        sha_to_project = pd.Series(df.project.values, index=df.sha).to_dict()
        return sha_to_project
    
    sha_to_row = load_raw_info_pandas()
    SHA_META_DICT.update(sha_to_row)


    """Load the prompt data on startup"""
    global PROMPT_DATA
    try:
        # Load the prompt list using your existing function
        prompt_count = extract_imp.load_prompt_list(str(HERE / "./data/single_function_allinone.saved.jsonl"))
        PROMPT_DATA = extract_imp.PROMPT_CONTENT
        PROMPT_DATA_v = list(PROMPT_DATA.values())
        PROMPT_DATA_v = {x["idx"]: x for x in PROMPT_DATA_v}
        
        PROMPT_DATA = PROMPT_DATA_v
        # Add bug_id to each entry
        for idx, entry in PROMPT_DATA_v.items():
            try:
                # Parse the idx to get project and sha
                proj, sha = parse_bug_id(idx)
                entry["bug_id"] = f"{proj}@{sha}"
                # Or if you just want the SHA:
                # entry["bug_id"] = sha
            except ValueError:
                # If parsing fails, extract first 40 chars as SHA
                potential_sha = idx[:40] if len(idx) >= 40 else idx
                entry["bug_id"] = potential_sha
            PROMPT_DATA[idx] = entry 
        PROMPT_DATA = {x["bug_id"]: x for k,x in PROMPT_DATA.items() }
        print(f"Loaded {prompt_count} prompts on startup with bug_ids added")
    except Exception as e:
        print(f"Failed to load prompts on startup: {e}")

def parse_bug_id(bug_id: str):
    """
    Parse bug_id in format 'project@sha' or just 'sha'.
    If only SHA is provided, attempt to look up the project from SHA_META_DICT.
    
    Args:
        bug_id: Either 'project@sha' or just 'sha'
        
    Returns:
        tuple: (project, sha)
        
    Raises:
        ValueError: If bug_id format is invalid or SHA cannot be resolved to project
    """
    # Fix the typo: bug*id -> bug_id
    proj, _, sha = bug_id.partition("@")
    
    # Case 1: Full format 'project@sha' provided
    if proj and sha:
        return proj, sha
    
    # Case 2: Only SHA provided (no '@' found, so proj contains the whole string)
    if proj and not sha:
        potential_sha = proj.strip()
        
        # Validate SHA format (7-40 hex characters)
        if not re.match(r'^[0-9a-f]{7,40}$', potential_sha, re.I):
            potential_sha = potential_sha[:40]
            if not re.match(r'^[0-9a-f]{7,40}$', potential_sha, re.I):
                raise ValueError(f"Invalid SHA format: {potential_sha}")
        
        # Look up project from SHA_META_DICT
        if potential_sha in SHA_META_DICT:
            project_name = SHA_META_DICT[potential_sha]
            return project_name, potential_sha
        else:
            raise ValueError(f"SHA '{potential_sha}' not found in metadata. "
                           f"Available SHAs: {len(SHA_META_DICT)} loaded.")
    
    # Case 3: Invalid format
    raise ValueError(f"bug_id must be 'project@sha' or 'sha', got: '{bug_id}'")




@app.get("/reset")
async def reset_random_prompt():
    """
    Randomly select one prompt from the loaded data
    Returns the complete prompt data structure
    """
    global PROMPT_DATA
    
    if not PROMPT_DATA:
        raise HTTPException(status_code=404, detail="No prompt data available")
    # Randomly select one item
    random_sha = random.choice(list(PROMPT_DATA.keys()))
    return await _get_defect(defect_id=random_sha)
    

@app.get("/get_defect/{defect_id}")
async def get_defect(defect_id: str):
    """
    Get defect information by defect_id (SHA)
    Returns the complete defect data structure including prompt, metadata, and guidance info
    """
    global PROMPT_DATA
    
    # Ensure data is loaded
    if not PROMPT_DATA:
        raise HTTPException(status_code=404, detail="No prompt data available")
    
    # Check if defect_id exists in PROMPT_DATA
    if defect_id not in PROMPT_DATA:
        list_sample_key= list(PROMPT_DATA)
        raise HTTPException(
            status_code=404, 
            detail=f"Defect ID {defect_id} not found in prompt data. Available IDs: {len(PROMPT_DATA)} total, for example {list_sample_key[:10]}"
        )
    return await _get_defect(defect_id=defect_id)

async def _get_defect( defect_id ):
    sha_id = defect_id[:40]
    
    try:
        # Get the basic prompt data
        defect_data = PROMPT_DATA[defect_id].copy()

        bug_id =defect_data["bug_id"]
        
        # Try to get additional metadata if available
        additional_info = {}
        
        # Check if META_DICT has info for this SHA
        if hasattr(extract_imp, 'META_DICT') and sha_id in extract_imp.META_DICT:
            additional_info['metadata'] = extract_imp.META_DICT[sha_id]
        
        # Check if guidance_df has info for this SHA
        if hasattr(extract_imp, 'guidance_df') and extract_imp.guidance_df is not None:
            guidance_row = extract_imp.guidance_df.loc[extract_imp.guidance_df["commit_after"] == sha_id]
            if not guidance_row.empty:
                additional_info['guidance'] = guidance_row.iloc[0].to_dict()
        
        # Check if there's prefix/suffix metadata
        if hasattr(extract_imp, 'META_DICT_PREFIX_SUFFIX') and sha_id in extract_imp.META_DICT_PREFIX_SUFFIX:
            additional_info['prefix_suffix'] = extract_imp.META_DICT_PREFIX_SUFFIX[sha_id]
        
        # Check if source content is available
        if hasattr(extract_imp, 'SRC_CONTENT') and additional_info.get('guidance'):
            src_path = additional_info['guidance'].get('src_path')
            if src_path and src_path in extract_imp.SRC_CONTENT:
                additional_info['has_source_content'] = True
                additional_info['source_content_length'] = len(extract_imp.SRC_CONTENT[src_path])
            else:
                additional_info['has_source_content'] = False
        
        return {
            "status": "success",
            #"defect_id": defect_id,
            "defect_id": bug_id,
            "sha_id": sha_id,
            "bug_id":bug_id,
            "prompt_data": defect_data,
            "additional_info": additional_info,
            "total_defects_available": len(PROMPT_DATA)
        }
        
    except Exception as e:
        raise HTTPException(
            status_code=500, 
            detail=f"Error retrieving defect {defect_id}: {str(e)}"
        )



@app.get("/list_defects_ids")
async def list_defects_ids():
    """
    List all available defect IDs (SHAs) from PROMPT_DATA
    Returns a list of all defect IDs that can be used with /get_defect/{defect_id}
    """
    global PROMPT_DATA
    
    # Ensure data is loaded
    if not PROMPT_DATA:
        raise HTTPException(status_code=404, detail="No prompt data available")
    
    try:
        PROMPT_DATA_v = list(PROMPT_DATA.values())
        PROMPT_DATA_v = {x["idx"]:x for x in PROMPT_DATA_v}
        defect_ids = list(PROMPT_DATA_v.keys())
        
        return {
            "status": "success",
            "total_count": len(defect_ids),
            "defect_ids": sorted(defect_ids),  # Sort for consistent ordering
            "sample_ids": defect_ids[:5] if len(defect_ids) > 5 else defect_ids  # Show first 5 as examples
        }
        
    except Exception as e:
        raise HTTPException(
            status_code=500, 
            detail=f"Error retrieving defect IDs: {str(e)}"
        )



'''
@app.post("/ask_llm_stream")
async def fix_code_stream(request: CodeFixRequest):
    """Stream the LLM-powered code fix back as text chunks."""
    try:
        def generate():
            stream_resp = LLMDebugger.fix_code_with_qwen3_14b(
                request.code, 
                request.feedback, 
                stream=True
            )
            for chunk in stream_resp:
                if chunk.choices:
                    delta = chunk.choices[0].delta.content
                    if delta:
                        yield delta
        
        return StreamingResponse(
            generate(),
            media_type='text/html'
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error streaming code fix: {str(e)}"
        )
'''

@app.post("/ask_llm_stream")
async def fix_code_stream(request: CodeFixRequest):
    """Stream the LLM-powered code fix back as text chunks in XML-tagged format."""
    try:
        def generate():
            # Accumulate all chunks to parse the complete response
            accumulated_content = []
            
            stream_resp = LLMDebugger.fix_code_with_qwen3_14b(
                request.code,
                request.feedback,
                stream=True
            )
            
            for chunk in stream_resp:
                # Handle both string chunks and structured response objects
                if isinstance(chunk, str):
                    # If chunk is already a string, accumulate it
                    accumulated_content.append(chunk)
                elif hasattr(chunk, 'choices') and chunk.choices:
                    # If chunk has choices attribute (OpenAI-style response)
                    delta = chunk.choices[0].delta.content
                    if delta:
                        accumulated_content.append(delta)
                elif hasattr(chunk, 'content'):
                    # Alternative: if chunk has direct content attribute
                    accumulated_content.append(chunk.content)
            
            # Join all chunks to get complete response
            full_content = ''.join(accumulated_content)
            
            # Parse the LLM response - it might already have XML tags or might be in other format
            fixed_code = ""
            explanation = ""
            changes_made = []
            
            # First, check if response already has XML tags
            fixed_start = full_content.find('<fixed_code>')
            fixed_end = full_content.find('</fixed_code>')
            if fixed_start != -1 and fixed_end != -1:
                # Already has XML tags, just return as-is
                yield full_content
                return
            
            # If no XML tags, parse the response and create XML format
            # The response should be the formatted output from get_debug_prompt
            # which asks for XML tags, so this should rarely be needed
            
            # Try to extract from the LLM's response structure
            exp_start = full_content.find('<explanation>')
            exp_end = full_content.find('</explanation>')
            if exp_start != -1 and exp_end != -1:
                explanation = full_content[exp_start + 13:exp_end].strip()
            
            changes_start = full_content.find('<changes_made>')
            changes_end = full_content.find('</changes_made>')
            if changes_start != -1 and changes_end != -1:
                changes_text = full_content[changes_start + 14:changes_end].strip()
                changes_made = [line.strip().lstrip('- ').lstrip('• ') 
                              for line in changes_text.split('\n') 
                              if line.strip()]
            
            # Extract code - try to find it between code tags or use the full content
            if fixed_start == -1:
                # No fixed_code tags found, assume entire response is code or extract from markdown
                code_match = re.search(r'```(?:cpp|c\+\+)?\n(.*?)```', full_content, re.DOTALL)
                if code_match:
                    fixed_code = code_match.group(1).strip()
                else:
                    # Use the original code as fallback
                    fixed_code = request.code
            
            # Format response as XML tags for HTML parser
            xml_response = f"""<fixed_code>
{fixed_code}
</fixed_code>

<explanation>
{explanation if explanation else "Code has been analyzed and fixed"}
</explanation>

<changes_made>
{chr(10).join('- ' + change for change in changes_made) if changes_made else '- Code modifications applied'}
</changes_made>"""
            
            yield xml_response
        
        return StreamingResponse(
            generate(),
            media_type='text/plain'
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error streaming code fix: {str(e)}"
        )



@app.post("/ask_llm")
async def fix_code(request: CodeFixRequest):
    """Get a non-streaming code fix response."""
    try:
        result = LLMDebugger.fix_code_with_qwen3_14b(
            request.code,
            request.feedback,
            stream=False
        )
        return result
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error fixing code: {str(e)}"
        )


@app.get("/list_defects_bugid")
async def list_defects_bugid():
   """
   List all available defects in the format 'project___repo@sha'
   Returns a list of all defects that can be used with /get_defect/{defect_id}
   """
   global PROMPT_DATA
   
   # Ensure data is loaded
   if not PROMPT_DATA:
       raise HTTPException(status_code=404, detail="No prompt data available")
   
   try:
       defect_list = []
       for defect_id, defect_data in PROMPT_DATA.items():
           bug_id = defect_data.get("bug_id", defect_id)
           defect_list.append(bug_id)
       
       return {
           "status": "success",
           "total_count": len(defect_list),
           "defects": sorted(defect_list),  # Sort for consistent ordering
           "sample_defects": defect_list[:5] if len(defect_list) > 5 else defect_list  # Show first 5 as examples
       }
       
   except Exception as e:
       raise HTTPException(
           status_code=500, 
           detail=f"Error retrieving defects: {str(e)}"
       )

