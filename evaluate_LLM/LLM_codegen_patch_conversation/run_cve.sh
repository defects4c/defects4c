
export  OPENAI_API_BASE="http://127.0.0.1:6006/v1"
export  OPENAI_BASE_URL="http://127.0.0.1:6006/v1"
export OPENAI_API_KEY="123"



md=$1
if [ -z  $md ]; then 
        echo "empty "
        exit 1 
fi

nohup python3 conversation_fix_generate_cve.py  \
         --model $md \
        --bs 1 --root ../data/patches_errmsg_conversation \
        --dataset_path ../data/prompts/buggy_errmsg_cve/single_function_repair.saved.jsonl \
        --resume \
        --temperature=1   --n_samples 30 \
        --n_round 10 --n_tries 3 \
        --original_json_path ../data/corpus/buggy_errmsg_cve/single_function_repair.json  2>&1 >>cve_d1.log &


nohup        python3 conversation_fix_generate_cve.py  \
         --model $md \
        --bs 1 --root ../data/patches_errmsg_conversation \
        --dataset_path ../data/prompts/buggy_errmsg_cve/single_function_repair.saved.jsonl \
        --resume \
        --temperature=0 --greedy  --n_samples 30 \
        --n_round 10 --n_tries 3 \
        --original_json_path ../data/corpus/buggy_errmsg_cve/single_function_repair.json    2>&1 >>cve_d1.log &
 
 

nohup python3 conversation_fix_generate_cve.py  \
         --model $md \
        --bs 1 --root ../data/patches_errmsg_conversation \
        --dataset_path ../data/prompts/buggy_errmsg_cve/single_function_single_hunk_repair.saved.jsonl \
        --resume \
        --temperature=1   --n_samples 30 \
        --n_round 10 --n_tries 3 \
        --original_json_path ../data/corpus/buggy_errmsg_cve/single_function_single_hunk_repair.json   2>&1 >>cve_d2.log &

nohup         python3 conversation_fix_generate_cve.py  \
         --model $md \
        --bs 1 --root ../data/patches_errmsg_conversation \
        --dataset_path ../data/prompts/buggy_errmsg_cve/single_function_single_hunk_repair.saved.jsonl \
        --resume \
        --temperature=0 --greedy  --n_samples 30 \
        --n_round 10 --n_tries 3 \
        --original_json_path ../data/corpus/buggy_errmsg_cve/single_function_single_hunk_repair.json    2>&1 >>cve_d2.log &
 
 
 
 
nohup python3 conversation_fix_generate_cve.py  \
         --model $md \
        --bs 1 --root ../data/patches_errmsg_conversation \
        --dataset_path ../data/prompts/buggy_errmsg_cve/single_function_single_line_repair.saved.jsonl \
        --resume \
        --temperature=1   --n_samples 30 \
        --n_round 10 --n_tries 3 \
        --original_json_path ../data/corpus/buggy_errmsg_cve/single_function_single_line_repair.json    2>&1 >>cve_d3.log &

nohup         python3 conversation_fix_generate_cve.py  \
         --model $md \
        --bs 1 --root ../data/patches_errmsg_conversation \
        --dataset_path ../data/prompts/buggy_errmsg_cve/single_function_single_line_repair.saved.jsonl \
        --resume \
        --temperature=0 --greedy  --n_samples 30 \
        --n_round 10 --n_tries 3 \
        --original_json_path ../data/corpus/buggy_errmsg_cve/single_function_single_line_repair.json    2>&1 >>cve_d3.log &

