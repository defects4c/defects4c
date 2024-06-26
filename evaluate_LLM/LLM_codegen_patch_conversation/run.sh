
export OPENAI_API_BASE="http://10.96.187.173/v1"
export  OPENAI_BASE_URL="http://10.96.187.173/v1"
export OPENAI_API_KEY="123"



nohup python3 conversation_fix_generate.py  \
	 --model CodeLlama-7b-Instruct-hf \
	--bs 1 --root ../data/patches_errmsg_conversation \
	--dataset_path ../data/prompts/buggy_errmsg/single_function_repair.saved.jsonl \
	--resume \
	--temperature=1   --n_samples 30 \
	--n_round 10 --n_tries 3 \
	--original_json_path ../data/corpus/buggy_errmsg/single_function_repair.json  &&  \
	\
	\
	python3 conversation_fix_generate.py  \
	 --model CodeLlama-7b-Instruct-hf \
	--bs 1 --root ../data/patches_errmsg_conversation \
	--dataset_path ../data/prompts/buggy_errmsg/single_function_repair.saved.jsonl \
	--resume \
	--temperature=0 --greedy  --n_samples 30 \
	--n_round 10 --n_tries 3 \
	--original_json_path ../data/corpus/buggy_errmsg/single_function_repair.json    2>&1 >>d1.log &
 
 

nohup python3 conversation_fix_generate.py  \
	 --model CodeLlama-7b-Instruct-hf \
	--bs 1 --root ../data/patches_errmsg_conversation \
	--dataset_path ../data/prompts/buggy_errmsg/single_function_single_hunk_repair.saved.jsonl \
	--resume \
	--temperature=1   --n_samples 30 \
	--n_round 10 --n_tries 3 \
	--original_json_path ../data/corpus/buggy_errmsg/single_function_single_hunk_repair.json  && \
\
\
\
	 python3 conversation_fix_generate.py  \
	 --model CodeLlama-7b-Instruct-hf \
	--bs 1 --root ../data/patches_errmsg_conversation \
	--dataset_path ../data/prompts/buggy_errmsg/single_function_single_hunk_repair.saved.jsonl \
	--resume \
	--temperature=0 --greedy  --n_samples 30 \
	--n_round 10 --n_tries 3 \
	--original_json_path ../data/corpus/buggy_errmsg/single_function_single_hunk_repair.json    2>&1 >>d2.log &
 
 
 
 
nohup python3 conversation_fix_generate.py  \
	 --model CodeLlama-7b-Instruct-hf \
	--bs 1 --root ../data/patches_errmsg_conversation \
	--dataset_path ../data/prompts/buggy_errmsg/single_function_single_line_repair.saved.jsonl \
	--resume \
	--temperature=1   --n_samples 30 \
	--n_round 10 --n_tries 3 \
	--original_json_path ../data/corpus/buggy_errmsg/single_function_single_line_repair.json   && \
	\
	\
	 python3 conversation_fix_generate.py  \
	 --model CodeLlama-7b-Instruct-hf \
	--bs 1 --root ../data/patches_errmsg_conversation \
	--dataset_path ../data/prompts/buggy_errmsg/single_function_single_line_repair.saved.jsonl \
	--resume \
	--temperature=0 --greedy  --n_samples 30 \
	--n_round 10 --n_tries 3 \
	--original_json_path ../data/corpus/buggy_errmsg/single_function_single_line_repair.json    2>&1 >>d3.log &
 
