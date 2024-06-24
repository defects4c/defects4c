
##step1 
docker image build -t base/defect4c . 


## step2 run instance



 docker run  -d   --name my_defects4c \
        --ipc=host \
	--cap-add SYS_PTRACE \
         -v "`pwd`/defectsc_tpl:/src" \
         -v "`pwd`/out_tmp_dirs:/out" \
         -v "`pwd`/patche_dirs:/patches" \
	 -v "`pwd`/../LLM_Defects4C:/src2" \
        defects4c/defects4c:latest
 


 # step3 get into container
docker exec -it my_defects4c bash 
