#
#
#
#
#### 
#
#
#export CUDA_VISIBLE_DEVICES=0,1,2,3,4,5,6,7
#export VLLM_N_GPUS=8
#
#
#for VARIABLE in  "mixtral-8x7b-instruct" 
#	#"mistral-7b" "openchat" "deepseek-coder-33b-base" "deepseek-coder-33b-instruct" "opencodeinterpreter-ds-33b" ""
#       
#
#
#do 
#
##------T=0.2
#
#
#python generate.py   \
#	--model $VARIABLE \
#	--bs 100 \
#	--root ../data/patches_errmsg/ \
#	--dataset-path=../data/prompts/buggy_errmsg_inone/single_function_allinone.saved.jsonl \
#	--greedy \
#	--n_samples 1 \
#	--resume
#
#python generate.py   \
#	--model $VARIABLE \
#	--bs 100 \
#	--root ../data/patches_errmsg/ \
#	--dataset-path=../data/prompts/buggy_errmsg_inone/single_function_allinone.saved.jsonl \
#	--temperature=0.2 \
#	--n_samples 100 \
#	--resume
#
#
#python generate.py   \
#	--model $VARIABLE \
#	--bs 100 \
#	--root ../data/patches_errmsg/ \
#	--dataset-path=../data/prompts/buggy_errmsg_inone/single_function_allinone.saved.jsonl \
#	--temperature=0.8 \
#	--n_samples 100 \
#	--resume
#
#
#
#
#done
