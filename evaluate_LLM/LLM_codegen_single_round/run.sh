

python generate_base_inst.py  ../data/prompts/buggy_errmsg/single_function_allinone.saved.jsonl \
        --model deepseek-ai/deepseek-coder-6.7b-base \
        --bs 4 \
        --temperature 0.2 \
        --n_samples 200 \
        --resume --max-len 8192 \
        --backend vllm 




python generate_base_inst.py  ../data/prompts/buggy_errmsg/single_function_allinone.saved.jsonl \
        --model deepseek-ai/deepseek-coder-6.7b-base \
        --bs 4 \
        --temperature 0.8 \
        --n_samples 200 \
        --resume --max-len 8192 \
        --backend vllm 



python generate_base_inst.py  ../data/prompts/buggy_errmsg/single_function_allinone.saved.jsonl \
        --model deepseek-ai/deepseek-coder-6.7b-base \
        --greedy \
        --resume --max-len 8192 \
        --backend vllm 


