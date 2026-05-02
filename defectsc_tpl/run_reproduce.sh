
project=$1
project=$(basename $project)

venv_candidates=()
if [[ -n "${DEFECTS4C_VENV:-}" ]]; then
        venv_candidates+=("${DEFECTS4C_VENV}")
fi
venv_candidates+=("/opt/defects4c-venv" "/src/.venv")

python_bin=""
for venv_dir in "${venv_candidates[@]}"; do
        if [[ -x "${venv_dir}/bin/python" ]]; then
                python_bin="${venv_dir}/bin/python"
                break
        fi
done

if [[ -z "${python_bin}" ]]; then
        echo "No usable Python environment found. Set DEFECTS4C_VENV or create /opt/defects4c-venv." >&2
        exit 1
fi



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
                "${python_bin}" bug_helper_v1_out2.py reproduce \
                        "${project}@${one_sha}" 
        else 
                echo "exist.....-->"$test_log

        fi

done 
