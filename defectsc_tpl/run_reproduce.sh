
project=$1
project=$(basename $project)



sha=$2

if [ ! -z $sha ]; then 
	sha_list=($sha)
	size=1
else	
	sha_list=$(jq -cr ".[]|.commit_after" /src/projects_v1/$project/bugs_list_new.json )
	size=$(jq -cr ".[]|.commit_after" /src/projects_v1/$project/bugs_list_new.json |wc -l )
fi 

echo "size=="$size



for one_sha in $sha_list ; do 

        test_log="/out/$project/logs/${one_sha}.log"

        if [[ ! -f $test_log ]]; then 
                python3 bug_helper_v1_out2.py  reproduce   \
                        "${project}@${one_sha}" 
        else 
                echo "exist.....-->"$test_log

        fi

done 

