
##step1 
docker image build -t base/defect4c . 


## step2 run instance



 docker run --rm -d \
        --ipc=host \
                --cap-add SYS_PTRACE \
         -v "`pwd`/defectsc_tpl:/src" \
         -v "`pwd`/out_tmp_dirs:/out" \
         -v "`pwd`/patche_dirs:/patches" \
	 -v "`pwd`/../LLM_Defects4C:/src2" \
        base/defect4c:latest
