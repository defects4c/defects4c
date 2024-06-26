
export OPENAI_API_KEY="sk-acxxxxxxxx"



for VARIABLE in    "gpt-4-1106-preview"
#for VARIABLE in  "gpt-3.5-turbo"  "gpt-4-1106-preview"
	# "gpt-35-turbo"
      


do 

#------T=0.2


python generate.py   \
	--model $VARIABLE \
	--bs 100 \
	--root ../data/patches_errmsg/ \
	--dataset-path=../data/prompts/buggy_errmsg_inone/single_function_allinone.saved.jsonl \
	--greedy \
	--n_samples 1 \
	--resume

#python generate.py   \
#	--model $VARIABLE \
#	--bs 100 \
#	--root ../data/patches_errmsg/ \
#	--dataset-path=../data/prompts/buggy_errmsg_inone/single_function_allinone.saved.jsonl \
#	--temperature=0.2 \
#	--n_samples 100 \
#	--resume


#python generate.py   \
#	--model $VARIABLE \
#	--bs 100 \
#	--root ../data/patches_errmsg/ \
#	--dataset-path=../data/prompts/buggy_errmsg_inone/single_function_allinone.saved.jsonl \
#	--temperature=0.8 \
#	--n_samples 100 \
#	--resume




done
