import requests
import json
import time
import os
import random
from openai import OpenAI

# Setup
DEFECTS4C_BASE_URL = "http://127.0.0.1:11111"
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
client = OpenAI(
    api_key=OPENAI_API_KEY,
    base_url=os.getenv("OPENAI_BASE_URL", "http://157.10.162.82:443/v1/"),
)


def main():
    # Step 0: Get list of defects and randomly select one
    print("Step 0: Getting list of defects...")
    list_response = requests.get(f"{DEFECTS4C_BASE_URL}/list_defects_bugid")
    defects_data = list_response.json()

    if defects_data.get("status") != "success":
        print(f"Error getting defects list: {defects_data}")
        return

    # Recommend: filter out llvm defects (CPU-heavy for online service)
    filtered_defects = [
        d for d in defects_data["defects"] if "llvm___llvm" not in d
    ]
    selected = random.choice(filtered_defects)
    print(f"Selected entry: {selected}")

    # Step 1: Get defect information and prompts
    print("Step 1: Getting defect info...")
    response = requests.get(f"{DEFECTS4C_BASE_URL}/get_defect/{selected}")
    defect_data = response.json()

    if defect_data.get("status") != "success":
        print(f"Error getting defect: {defect_data}")
        return

    # Use the authoritative bug_id from the response — it is always in
    # "project@sha" format even if the listing returned a bare SHA.
    bug_id = defect_data["bug_id"]
    print(f"Resolved bug_id: {bug_id}")

    prompts = defect_data["prompt_data"]["prompt"]
    temperature = defect_data["prompt_data"].get("temperature", 0.7)

    # Step 2: Send prompts to LLM
    print("Step 2: Sending to LLM...", prompts)
    ai_response = client.chat.completions.create(
        model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
        messages=prompts,
        temperature=temperature,
        max_tokens=4096,
    )
    print("Waiting for response...")

    llm_response = ai_response.choices[0].message.content
    print(f"LLM response: {llm_response[:100]}...")

    # Step 3: Build patch from AI response
    print("Step 3: Building patch...")
    patch_payload = {
        "bug_id": bug_id,           # guaranteed "project@sha" format
        "llm_response": llm_response,
        "method": "direct",
        "generate_diff": True,
        "persist_flag": True,
    }

    patch_response = requests.post(
        f"{DEFECTS4C_BASE_URL}/build_patch",
        headers={"Content-Type": "application/json"},
        json=patch_payload,
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
    # NOTE: endpoint is /fix (not /fix2 — that route was removed in the
    # unified new_main.py service).
    print("Step 4: Submitting fix check...")
    fix_payload = {
        "bug_id": bug_id,
        "patch_path": patch_path,
    }

    fix_response = requests.post(
        f"{DEFECTS4C_BASE_URL}/fix",          # was /fix2 — now /fix
        headers={"Content-Type": "application/json"},
        json=fix_payload,
    )

    fix_data = fix_response.json()
    handle = fix_data["handle"]
    print(f"Fix submitted, handle: {handle}")

    # Step 5: Poll for fix status
    print("Step 5: Checking fix status...")
    max_wait = 300       # 5 minutes
    poll_interval = 10   # 10 seconds
    start_time = time.time()
    status_data = {}

    while time.time() - start_time < max_wait:
        status_response = requests.get(f"{DEFECTS4C_BASE_URL}/status/{handle}")
        status_data = status_response.json()

        status_completed = status_data.get("status", "unknown")
        is_completed = status_completed in ("completed", "failed")
        print(f"Current status: {status_completed}")

        if is_completed:
            fix_status = status_data.get("fix_status", "")
            return_code = status_data.get("return_code", -1)
            if return_code == 0:
                print("✅ Fix successful!")
            else:
                print(f"❌ Fix failed (rc={return_code}): "
                      f"{status_data.get('error', 'Unknown error')}")
            break

        print(f"Waiting {poll_interval} seconds...")
        time.sleep(poll_interval)
    else:
        print("⏱️  Timed out waiting for fix result")

    return status_data


if __name__ == "__main__":
    if not OPENAI_API_KEY:
        print("Please set OPENAI_API_KEY environment variable")
        exit(1)

    main()

