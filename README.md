## Defects4C: Benchmarking C/C++ Faults to Assess LLM-Based Program Repair 👋

Most existing Automated Program Repair (APR) research focuses on Java programs, primarily through Defects4J. Despite the significant prevalence of C/C++ vulnerabilities, extensive research on the automated repair of such vulnerabilities is lacking.

To fill this critical gap, we introduce Defects4C, a high-quality executable benchmark for C/C++ defects. It consists of **248** buggy functions and **102** vulnerable functions, paired with test cases for reproduction.




## 1. Overview

- To assess the effectiveness of existing state-of-the-art APR techniques in repairing C/C++ faults, we conduct a comprehensive empirical study using 24 state-of-the-art LLMs with Defects4C in two different scenarios:

  - Single-round repair
  - Conversation-based repair for evaluation. 



## 2. Setup the docker. 

a. Initialize Defects4C :

```shell
  docker image build -t defects4c/defects4c -f docker_dirs/Dockerfile .
or 
  docker pull defects4c/defects4c
```
Run the Docker container:

```
 docker run --name my_defects4c -d \
        --ipc=host \
         -v "`pwd`/defectsc_tpl:/src" \
         -v "`pwd`/out_tmp_dirs:/out" \
         -v "`pwd`/patche_dirs:/patches" \
        defects4c/defects4c:latest
```

b. Change the working environment to the Docker container:

```
 docker exec -it my_defects4c bash
```

c. Install system-level dependencies from within the container:

```
bash /src/install_deps.sh 
```

This is a one-time setup, taking 10-15 minutes on a 128-core machine. All bugs' environments are initialized here.

There are two parts to Defects4C: one collects normal bugs from the real world, Defects4C_bug and another is collect from CVE, named Defects4C_vul, we are only demostrated the Defects4C_bug, you can check [Defects4C_vul](Defects4C_vul.md) for Defects4C_vul

## 3. Download Bug Repositories

<details>

<summary>One command to download all projects:

```
bash bulk_git_clone.sh
```

</summary>

### You can also check out projects one by one


- List Projects

```shell
find projects* -name '*bug*json'|xargs jq '.[]|select(.unittest.status=="success2")|.url'|awk -F "/commits/" '{print $1}'|sort |uniq -c
```

- List the buglist for a specific project (list -r [project] ):

```
jq ".[]|.commit_after" projects_v1/[repo]/bugs_list_new.json

#for example
jq ".[]|.commit_after" projects_v1/danmar___cppcheck/bugs_list_new.json

```

- Get information for a specific bug (info [bug_id]):

```
jq '.[]|select(.commit_after=="[commit_after]")|.' projects_v1/[repo]/bugs_list_new.json
#for example
jq '.[]|select(.commit_after=="d2284ddbcd2a70b4a39047ae32b1c5662060407f")|.' projects_v1/danmar___cppcheck/bugs_list_new.json
```

- Checkout a buggy source code and reproduce the UnitTest pair (reproduce [bug_id]):
```
bash bulk_git_clone.sh [repo]
# or git clone one project or all projects 
bash bulk_git_clone.sh danmar___cppcheck
bash bulk_git_clone.sh 
```

</details>

## 4, Reproduce one bug
Now, you can reproduce any bug:

```
bash run_reproduce.sh  [repo] [bug_id]
# for example
bash run_reproduce.sh  danmar___cppcheck 099b4435c38dd52ddb38e6b1706d9c988699c082

```
Then you can check the status and error messages from the path '/out/[project]'. For example: `ls /out/danmar___cppcheck `, there are two file types, the `msg` for error message of compilation and `status` for units pass.

```
# Check error message

# cat  /out/danmar___cppcheck/logs/test_099b4435c38dd52ddb38e6b1706d9c988699c082_fix.msg

# Check status

cat  /out/danmar___cppcheck/logs/test_099b4435c38dd52ddb38e6b1706d9c988699c082_fix.status
cat  /out/danmar___cppcheck/logs/test_099b4435c38dd52ddb38e6b1706d9c988699c082_buggy.status
```

## 5. Fix a Bug Using a Given Patch

- Verify whether a patch can repair the error:

```
bash run_patch.sh  099b4435c38dd52ddb38e6b1706d9c988699c082

```

Check the patch verification result:



```
cat  /out/danmar___cppcheck/logs/patch_099b4435c38dd52ddb38e6b1706d9c988699c082_01d594477413b345316d0c0e2acbe8e9.msg

cat  /out/danmar___cppcheck/logs/patch_099b4435c38dd52ddb38e6b1706d9c988699c082_01d594477413b345316d0c0e2acbe8e9.status

```


</details>
Finally, it will show the patch verification result. If the status is a failure, you can check the log file in "/out/[project]" again to build the prompt's query and ask the LLM to refine the patch, making it correct.




