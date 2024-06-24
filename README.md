## Defects4C, a Benchmarking C/C++ Faults to Assess LLM-Based Program Repair 👋

Most existing Automated program repair (APR) research focuses on Java programs, Defects4J. Despite the significant prevalence of C/C++ vulnerabilities, the field lacks extensive research on the automated repair of such vulnerabilities.

To fill this critical gap, we introduces Defects4C, a high-quality executable benchmark for C/C++ defects. It consists of **248** buggy functions and  **102** vulnerable functions paired with the test cases for reproduction. 



## 1. Overview
- Assess the effectiveness of existing state-of-the-art APR techniques in repairing C/C++ faults, we conduct a comprehensive empirical study including 24 state-of-the-art LLMs using **Defects4C** in two different scenarios:
  - Single-round repair
  - Conversation-based repair for evaluation. 



## 2. Setup the docker. 

a. Initialize Defects4C :

```shell
  docker image build -t defects4c/defects4c -f docker_dirs/Dockerfile .
or 
  docker pull defects4c/defects4c
```

```
 docker run --name my_defects4c -d \
        --ipc=host \
         -v "`pwd`/defectsc_tpl:/src" \
         -v "`pwd`/out_tmp_dirs:/out" \
         -v "`pwd`/patche_dirs:/patches" \
        defects4c/defects4c:latest
```

b. Change working environment into the docker container
```
 docker exec -it my_defects4c bash
```

c. Install the system level dependence from the container's inner side
```
bash /src/install_deps.sh 
```

This is a onetime setup, it takes 10-15 minutes in 128 cores, all bugs' env initial time only in here.

## 3, Reproduce a bug 
there are two parts for defects4c, one is defects4c_bug which collect normal bug from real-worldby our human

- List Projects

```shell
find projects* -name '*bug*json'|xargs jq '.[]|select(.unittest.status=="success2")|.url'|awk -F "/commits/" '{print $1}'|sort |uniq -c
```

- List the buglist for a specific project (list -r [project] ):

```
jq ".[]|.commit_after" projects_v1/[repo]/bugs_list_new.json

#for example
jq ".[]|.commit_after" projects_v1/llvm___llvm-project/bugs_list_new.json

```

- Get information for a specific bug (info [bug_id]):

```
jq '.[]|select(.commit_after=="[commit_after]")|.' projects_v1/[repo]/bugs_list_new.json
#for example
jq '.[]|select(.commit_after=="7b54a29c2e72e3e6bf7bb8cb5acfe254335584d7")|.' projects_v1/llvm___llvm-project/bugs_list_new.json
```

- Checkout a buggy source code and reproduce the UnitTest pair (reproduce [bug_id]):

```
python3 bug_helper_v1_out2.py  reproduce [bug_id]
for example
python3 bug_helper_v1_out2.py  reproduce danmar___cppcheck@a0c37ceba27179496fa2f44072f85e2a5448216e 
```

* then you can check out the status and error message from the path '/out/[project]', e.g. `ls /out/danmar___cppcheck `, there are two file types, the log for error message of compilation and XML for units report.

## 4, Fix a bug by given patch path

- Verify a patch whether can repair the error or not:

```
python3 bug_helper_v1_out2.py  fix [bug_id] [patch_path] 
#for example 

 python3 bug_helper_v1_out2.py  fix danmar___cppcheck@a0c37ceba27179496fa2f44072f85e2a5448216e /patch/gpt-3.5-turbo_temp_0@@danmar___cppcheck@@ea2916a3e49934d482cd9b30b520c7873db4de82___tokenlist.cpp@6@1
```

Finally, it will show the patch verification result, if the status is a failure, you can check the log file in "/out/[project]" again to build the prompt's query and ask the LLM to refine the patch making it correct.


# Benchmark in one 
The scripts to 
We offer the script to assess the C/C++ Faults for LLM-Based Program Repair, calculate the pass@k where k in greedy, 1, 10 and 100 repsectively, which depends on ([VLLM](https://github.com/vllm-project/vllm)) 

```
updating
```

