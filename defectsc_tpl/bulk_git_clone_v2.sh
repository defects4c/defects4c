#!/bin/bash

project=$1
if [ ! -z "$project" ]; then 
    project_list=("$project")
else
    project_list=($(find . -name 'project*json' | xargs jq -r ".repo_name"))
fi 

echo "scan project_list... ${project_list[@]}"
check_list=()

for one_project in "${project_list[@]}"; do 
    #echo "start... $one_project"
    commit_after_list=$(find . -name '*bug*json' -type f | grep "$one_project" | xargs jq -r ".[].commit_after")
    commit_before_list=$(find . -name '*bug*json' -type f | grep "$one_project" | xargs jq -r ".[].commit_before")
    size=$(find . -name '*bug*json' -type f | grep "$one_project" | xargs jq ".[].commit_after" | wc -l)
    
    #echo "size== $size"
    if [[ $size -eq 0 ]]; then
        echo "empty queue"
        exit 1 
    fi 
    
    raw_repo="${one_project/___/\/}"
    
    # Convert commit lists to arrays
    commit_after_array=($commit_after_list)
    commit_before_array=($commit_before_list)
    
    # Create git_setup commands for each commit_after paired with its commit_before
    for i in "${!commit_after_array[@]}"; do
        commit_after="${commit_after_array[i]}"
        commit_before="${commit_before_array[i]}"
        
        repo="bash /out/git_setup.sh ${one_project} ${commit_after} ${commit_before}"
        check_list+=("$repo")
    done
done

echo "now will setup totally ${#check_list[@]} projects"
cpu_count=$(($(nproc) - 1))

run_checkout() {
    printf "%s\n" "${check_list[@]}" > /tmp/checklist.txt 
   # cat /tmp/checklist.txt | xargs -I {} -P "$cpu_count" sh -c "{}"
}

while true; do
    read -p "Do you wish to run git setup for this program? " yn
    case $yn in
        [Yy]* ) run_checkout; break;;
        [Nn]* ) exit;;
        * ) echo "Please answer yes or no.";;
    esac
done

