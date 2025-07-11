import requests
import json
import time
import os
import random
from openai import OpenAI

# Setup
DEFECTS4C_BASE_URL = "https://defects4c.wj2ai.com"
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
client = OpenAI(api_key=OPENAI_API_KEY)

def main():
    # Step 0: Get list of defects and randomly select one
    print("Step 0: Getting list of defects...")
    list_response = requests.get(f"{DEFECTS4C_BASE_URL}/list_defects_bugid")
    defects_data = list_response.json()
    
    if defects_data.get("status") != "success":
        print(f"Error getting defects list: {defects_data}")
        return
    
    # Filter out llvm defects
    filtered_defects = [defect for defect in defects_data["defects"] if "llvm___llvm" not in defect]
    bug_id = random.choice(filtered_defects)
    print(f"Selected bug_id: {bug_id}")
    
    # Step 1: Get defect information and prompts
    print("Step 1: Getting defect info...")
    response = requests.get(f"{DEFECTS4C_BASE_URL}/get_defect/{bug_id}")
    defect_data = response.json()
    
    if defect_data.get("status") != "success":
        print(f"Error getting defect: {defect_data}")
        return
    
    prompts = defect_data["prompt_data"]["prompt"]
    temperature = defect_data["prompt_data"]["temperature"]
    
    # Step 2: Send prompts to OpenAI GPT-4o-mini
    print("Step 2: Sending to OpenAI...")
    ai_response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=prompts,
        temperature=temperature,
        max_tokens=4096
    )
    
    llm_response = ai_response.choices[0].message.content
    print(f"OpenAI response: {llm_response[:100]}...")
    
    # Step 3: Build patch from AI response
    print("Step 3: Building patch...")
    patch_payload = {
        "bug_id": bug_id,
        "llm_response": llm_response,
        "method": "direct",
        "generate_diff": True,
        "persist_flag": True
    }
    
    patch_response = requests.post(
        f"{DEFECTS4C_BASE_URL}/build_patch",
        headers={'Content-Type': 'application/json'},
        json=patch_payload
    )
    
    patch_data = patch_response.json()
    print(patch_data)
    
    if not patch_data.get("success"):
        print(f"Error building patch: {patch_data}")
        return
    
    if "patch_content" in patch_data:
        print(patch_data["patch_content"][:1000])
    
    patch_path = patch_data["fix_p"]
    print(f"Patch created: {patch_path}")
    
    # Step 4: Submit patch for fix verification
    print("Step 4: Submitting fix check...")
    fix_payload = {
        "bug_id": bug_id,
        "patch_path": patch_path
    }
    
    fix_response = requests.post(
        f"{DEFECTS4C_BASE_URL}/fix2",
        headers={'Content-Type': 'application/json'},
        json=fix_payload
    )
    
    fix_data = fix_response.json()
    handle = fix_data["handle"]
    print(f"Fix submitted, handle: {handle}")
    
    # Step 5: Check fix status
    print("Step 5: Checking fix status...")
    max_wait = 300  # 5 minutes
    poll_interval = 10  # 10 seconds
    start_time = time.time()
    
    while time.time() - start_time < max_wait:
        status_response = requests.get(f"{DEFECTS4C_BASE_URL}/status/{handle}")
        status_data = status_response.json()
        
        status_completed = status_data.get("status", "unknown")
        is_completed = status_completed == "completed"
        print(f"Status is_completed: {is_completed}")
        
        if is_completed:
            fix_status = status_data.get("fix_status")
            if fix_status == "success":
                print("✅ Fix successful!")
            else:
                print(f"❌ Fix failed: {status_data.get('error', 'Unknown error')}")
            break
        
        print(f"Waiting {poll_interval} seconds...")
        time.sleep(poll_interval)
    
    return status_data

if __name__ == "__main__":
    # Make sure to set OPENAI_API_KEY environment variable
    if not OPENAI_API_KEY:
        print("Please set OPENAI_API_KEY environment variable")
        exit(1)
    
    main()
