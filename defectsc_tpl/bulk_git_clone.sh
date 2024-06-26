
project=$1

if [ ! -z $project ]; then 
	project_list=($project)
else
	project_list=$( find . -name 'project*json'|xargs jq  -r ".repo_name" )	
fi 

echo "scan project_list..."$project_list
check_list=()
for one_project in $project_list ; do 
	#echo "start..."$one_project

	sha_list=$(find . -name '*bug*json' -type f |grep $one_project |xargs jq -r ".[].commit_after"             )
	size=$(find . -name '*bug*json' -type f |grep $one_project |xargs jq ".[].commit_after"     |wc -l    )
	#echo "size=="$size
	if [[ $size -eq 0 ]]; then
		echo "empty queue "
		exit 1 
	fi 


	raw_repor="${one_project/___/\/}"
	for sha in $sha_list ; do 
		repo="git clone --recursive http://github.com/${raw_repor} /out/${one_project}/git_repo_dir_${sha} && cd   /out/${one_project}/git_repo_dir_${sha} && git checkout -f ${sha} "
		#echo "--"$repo
		check_list+=("$repo")
	done 

done


echo "now will checkout totally "${#check_list[@]}

cpu_count=$(($(nproc) - 1))

_run_checkout() {
	printf "%s\n" "${check_list[@]}" > /tmp/checklist.txt 
	cat /tmp/checklist.txt |xargs -I {} -P $cpu_count sh -c "{}"
}

while true; do
    read -p "Do you wish to run git clone for  this program? " yn
    case $yn in
        [Yy]* ) _run_checkout ; break;;
        [Nn]* ) exit;;
        * ) echo "Please answer yes or no.";;
    esac
done

