

sha=$1


project=$(find  projects_v1/ -name "bugs_list*.json" |xargs grep "commit_after\": \""$sha"\""|head -n 1 |awk -F "\/" '{print $2}')


size=$(find /patches/$project/  -name "*@${sha}___*" |wc -l  )


patch_list=$(find /patches/$project/  -name "*@${sha}___*"  )


echo "size=="$size

if [[ $size -eq 0 ]]; then
        echo "empty queue "
        exit 1 
fi 


echo "patch_list...."$patch_list

for one_file in $patch_list ; do 
        #one_file=$(realpath $one_file)

        tmp=$(basename $one_file)
        OLD_IFS=$IFS
        IFS="@"
        read -ra parts <<< "$tmp"
        IFS=$OLD_IFS
        md5="${parts[0]}"
        sha_tmp="${parts[1]}"
        OLD_IFS=$IFS
        IFS="___"
        read -ra parts <<< "$sha_tmp"
        IFS=$OLD_IFS
        sha="${parts[0]}"

        test_log="/out/${project}/logs/patch_${sha}_${md5}.log"

        if [[ ! -f $test_log ]]; then 
                python3 bug_helper_v1_out2.py  fix   \
                        "${project}@${sha}"  \
                        $one_file 

        else 
                echo "exist.....-->"$test_log

        fi

done 


