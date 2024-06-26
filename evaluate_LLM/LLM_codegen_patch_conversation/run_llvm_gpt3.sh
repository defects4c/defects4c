unset OPENAI_API_BASE
unset OPENAI_BASE_URL
#export  OPENAI_BASE_URL="http://10.96.183.224:40004/v1"
#export  OPENAI_API_BASE="http://10.96.183.224:40004/v1"

export OPENAI_API_KEY="sk-proj-xxxxxxxxxxx"

nohup python3 conversation_fix_generate_llvm.py  \
	 --model gpt-3.5-turbo \
	--bs 1 --root ../data/patches_errmsg_conversation \
	--dataset_path ../data/prompts/buggy_errmsg/single_function_repair.saved.jsonl \
	--resume \
	--temperature=1   --n_samples 6 \
	--n_round 2 --n_tries 3 \
	--original_json_path ../data/corpus/buggy_errmsg/single_function_repair.json  2>&1 >>xxd1.log &


	python3 conversation_fix_generate_llvm.py  \
	 --model gpt-3.5-turbo \
	--bs 1 --root ../data/patches_errmsg_conversation \
	--dataset_path ../data/prompts/buggy_errmsg/single_function_repair.saved.jsonl \
	--resume \
	--temperature=0 --greedy  --n_samples 6 \
	--n_round 2 --n_tries 3 \
	--original_json_path ../data/corpus/buggy_errmsg/single_function_repair.json    2>&1 >>xxd1.log &
 
 

nohup python3 conversation_fix_generate_llvm.py  \
	 --model gpt-3.5-turbo \
	--bs 1 --root ../data/patches_errmsg_conversation \
	--dataset_path ../data/prompts/buggy_errmsg/single_function_single_hunk_repair.saved.jsonl \
	--resume \
	--temperature=1   --n_samples 6 \
	--n_round 2 --n_tries 3 \
	--original_json_path ../data/corpus/buggy_errmsg/single_function_single_hunk_repair.json  2>&1 >>xxd2.log &



nohup	 python3 conversation_fix_generate_llvm.py  \
	 --model gpt-3.5-turbo \
	--bs 1 --root ../data/patches_errmsg_conversation \
	--dataset_path ../data/prompts/buggy_errmsg/single_function_single_hunk_repair.saved.jsonl \
	--resume \
	--temperature=0 --greedy  --n_samples 6 \
	--n_round 2 --n_tries 3 \
	--original_json_path ../data/corpus/buggy_errmsg/single_function_single_hunk_repair.json    2>&1 >>xxd2.log &
 
 
 
 
nohup python3 conversation_fix_generate_llvm.py  \
	 --model gpt-3.5-turbo \
	--bs 1 --root ../data/patches_errmsg_conversation \
	--dataset_path ../data/prompts/buggy_errmsg/single_function_single_line_repair.saved.jsonl \
	--resume \
	--temperature=1   --n_samples 6 \
	--n_round 2 --n_tries 3 \
	--original_json_path ../data/corpus/buggy_errmsg/single_function_single_line_repair.json   2>&1 >>xxd3.log &

nohup	 python3 conversation_fix_generate_llvm.py  \
	 --model gpt-3.5-turbo \
	--bs 1 --root ../data/patches_errmsg_conversation \
	--dataset_path ../data/prompts/buggy_errmsg/single_function_single_line_repair.saved.jsonl \
	--resume \
	--temperature=0 --greedy  --n_samples 6 \
	--n_round 2 --n_tries 3 \
	--original_json_path ../data/corpus/buggy_errmsg/single_function_single_line_repair.json    2>&1 >>xxd3.log &
 
