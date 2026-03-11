#!/bin/bash



## checkout the repo into out, it will takes 20 minis and 80GB into out 

# step1: build docker image
docker image build -t base/defect4c .


# step2: run instance
docker run  -d   --name my_defects4c \
       --ipc=host \
	--cap-add SYS_PTRACE \
         -v "`pwd`/defectsc_tpl:/src" \
         -v "`pwd`/out_tmp_dirs:/out" \
         -v "`pwd`/patche_dirs:/patches" \
	 -v "`pwd`/LLM_Defects4C:/src2" \
	 base/defect4c:latest



# this warmup takes 20 mins to run 
docker exec my_defects4c bash -lc 'cd /src && bash run_warmup.sh 8'

# step3: get into container
docker exec -it my_defects4c bash

