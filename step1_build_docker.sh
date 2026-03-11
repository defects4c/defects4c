#!/bin/bash



## checkout the repo into out, it will takes 20 minis and 80GB into out 

# step1: build docker image
docker image build -t base/defect4c .


# step2: run instance
docker run  -d   --name my_defects4c \
       --ipc=host \
	--cap-add SYS_PTRACE \
	-p 11111:80 \
         -v "`pwd`/defectsc_tpl:/src" \
         -v "`pwd`/out_tmp_dirs:/out" \
         -v "`pwd`/patche_dirs:/patches" \
	 -v "`pwd`/LLM_Defects4C:/src2" \
	 base/defect4c:latest


# step 3: download mini repos, except  llvm ,
docker exec my_defects4c bash -lc 'cd /src && bash  bulk_git_clone_v2.sh  '

# step4: this warmup takes 20 mins to run , it  run cmake or config to  reproduce 
docker exec my_defects4c bash -lc 'cd /src && bash run_warmup.sh 8'

# inspect and  get into container
#docker exec -it my_defects4c bash


# step5: play the tutorial  
OPENAI_MODEL=gpt-4o-mini OPENAI_API_KEY="sk-xxx" OPENAI_BASE_URL="https://api.openai.com/v1/" python http_tutorial.py 
OPENAI_MODEL=deepseek-chat OPENAI_API_KEY="sk-xxx" OPENAI_BASE_URL="https://api.deepseek.com" python http_tutorial.py 
OPENAI_MODEL="Qwen/Qwen3-235B-A22B"  OPENAI_API_KEY="sk-xxx" OPENAI_BASE_URL="http://127.0.0.1:8888/v1/" python http_tutorial.py 



