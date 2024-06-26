import argparse
import os
import subprocess

import prompt
from os import PathLike
from codegen_GPT.model import DecoderBase, make_model
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    TextColumn,
    TimeElapsedColumn,
)

import openai
from openai import AzureOpenAI


import traceback
import json
# import extractor
from ChatParser import ChatParser
import pandas as pd
import patch_process_evalplus
import error_msg_parse
import is_pass_or_not
import random

with open("/src/patch_cve.list") as f :
    LLVM_IDS = [x.strip() for x in f.readlines() ]
LLVM_IDS= set(LLVM_IDS )
# LLVM_IDS =set(["68e0fa7499876fc0cf86b8be784a890226648645"])


OUT_DIR="/out"

def read_dataset(dataset_path):
    if dataset_path.endswith(".jsonl"):
        with open(dataset_path) as f:
            data = [json.loads(x) for x in f.readlines()]
            return data
    else:
        try:
            with open(dataset_path) as f:
                data = json.load(f)
        except:
            with open(dataset_path) as f:
                data = [json.loads(x) for x in f.readlines()]


import re
def mask_path (error_message ):
    if type(error_message) !=str :
        return error_message 
    path_pattern = re.compile(r'(/[^\s]*\w)')
    paths = path_pattern.findall(error_message)
    sub_path = [( x, os.path.basename(x) ) for x in paths]
    for ori , repl in sub_path:
        error_message = error_message.replace(ori,repl)
    
    return error_message 

import hashlib 
def get_md5( str_value ):
    return hashlib.md5(str_value.strip().lower().encode('utf-8')).hexdigest() 


def process_file2(item):
    if item["sampled"] is None :
        print ( item )
    code_str = extract_code_from_markdown_v2( markdown=item["sampled"] )
    sub_idx ="{}@{}".format( item ["ii"],  item ["ii"])
    idx=  item["idx"] 
    task =  item["task"] 
    if code_str is None :
        # return None 
        return {"task":task , "idx":idx,"sub_id":sub_idx ,"patch": None,"md5": None , "status":-2 }
    if len(code_str.strip())<=4 :
        return {"task":task , "idx":idx,"sub_id":sub_idx ,"patch": None,"md5": None , "status":-4 }

    code_str = embed_patch(idx, patch_part=code_str )
    if code_str is None :# the id not exist 
        return {"task": task, "idx":idx,"sub_id":sub_idx ,"patch": None,"md5": None  , "status":-3 }
        
    md5 = get_md5( code_str )
    return {"task": task, "idx":idx,"sub_id":sub_idx ,"patch": code_str ,"md5": md5  ,"status":1 }

def code_generate(args, workdir: PathLike, model: DecoderBase, dataset_path):
    dataset_name = os.path.basename(dataset_path)
    with Progress(
            TextColumn(
                f"{dataset_name} •" + "[progress.percentage]{task.percentage:>3.0f}%"
            ),
            BarColumn(),
            MofNCompleteColumn(),
            TextColumn("•"),
            TimeElapsedColumn(),
    ) as p:
        assert os.path.isfile(dataset_path), dataset_path
        dataset = read_dataset(dataset_path)
        # dataset = dataset[:4]
        random.shuffle( dataset )

        p_name = os.path.basename(os.path.dirname(dataset_path))
        # use a dict to record if pass for each try
        role = os.path.basename(workdir) #"buggy_errmsg_temp1"



        pass_dict = {}
        for item in p.track(dataset):
            # print ( type(item) , "item .", list(item ) )
            task_id, task = item["idx"], item  # ["prompt"]
            # print ("task_id" , task_id )
            sha= task_id.split("___")[0]
            assert len(sha)==40 , (task, task_id, len(sha), "--->sha",sha)
            if sha not in LLVM_IDS :
                # print ("skup llvm", sha, task_id )
                continue 
            # if sha !="81a1d744c6e9d13f2fac894c380caafb270741df":
            #     continue 
            pass_dict[task_id] = {}
            os.makedirs(os.path.join(workdir, p_name), exist_ok=True)
            log = f"Codegen: {p_name} @ {model}"
            n_existing = 0
            if args.resume:
                # count existing .py files
                n_existing = len(
                    [
                        f
                        for f in os.listdir(os.path.join(workdir, p_name))
                        if task_id in f
                    ]
                )
                if n_existing > 0:
                    log += f" (resuming from {n_existing})"
                    continue 

            nsamples = args.n_samples - n_existing
            sidx = args.n_samples - nsamples

            #  add by kjl: get the type of template -- function/hunk/line
            guess_role = "hunk" if "_hunk_" in os.path.basename(args.dataset_path) else "line" if "_line_" in os.path.basename(args.dataset_path) else "function"
            chart_type = 'simple' if guess_role == 'function' else 'complex'
            _chatgpt_parser = ChatParser(chart_type)
            try:  # add by kjl: add round and tries, to conduct conversation fix
                is_pass = False
                while sidx < args.n_samples and not is_pass:
                    # add by kjl: start a new round
                    for n_round in range(args.n_round):
                        if is_pass:
                            break
                        original_data_dict = prompt.load_data(args.original_json_path)
                        data_item = original_data_dict[task_id]
                        for n_tries in range(args.n_tries):
                            if is_pass:
                                break
                            if n_tries == 0:  # if the first try of current round
                                print(f"The {n_round}-{n_tries} for {task_id}")
                                task = item
                            # else:  # get the iterative prompt (according to the patch from the last try)
                            task['prompt'][1]['content'] = task['prompt'][1]['content'].replace('```cpp', '```')
                            try :
                                outputs = model.codegen(
                                        task["prompt"],
                                        do_sample=not args.greedy,
                                        num_samples=args.n_samples - sidx,
                                )
                            except (openai.APIError, openai.BadRequestError) :
                                traceback.print_exc()
                                string_round_try = f"{n_round}-{n_tries}"
                                pass_dict[task_id][string_round_try] = False
                                continue 

                            p.console.print("=====>" * 8, sidx)
                            p.console.print(task["prompt"])

                            p.console.print("<<<==" * 2 )
                            p.console.print(outputs)
                            
                            assert outputs, "No outputs from model!"
                            for impl in outputs:
                                # rnd = random.randint(0, 1000)
                                rnd = n_round
                                try:
                                    with open(
                                            os.path.join(workdir, p_name, f"{task_id}@{rnd}@{sidx}"),
                                            "w",
                                            encoding="utf-8",
                                    ) as f:
                                        if model.conversational:
                                            f.write(impl)
                                        else:
                                            f.write(task["prompt"] + impl)
                                except UnicodeEncodeError:
                                    traceback.print_exc()
                                    continue
                                sidx += 1

                            #  0. get the patch code as new buggy code
                            #  1. fill the patch back to project before building
                            #  2. run "bug_helper.py" and store feedback
                            #  3. get the error message about unitest

                            # patch_path
                            # patch_code = extractor.extract_code_from_markdown_v2(markdown=outputs[0])
                            if guess_role == 'function':
                                patch_code, _ = _chatgpt_parser.chatgpt_parse(outputs[0])
                            else:
                                patch_code, _ = _chatgpt_parser.chatgpt_parse(outputs[0], suffix=original_data_dict[task_id]['suffix'],
                                                                           prefix=original_data_dict[task_id]['prefix'])
                            print(patch_code)

                            # patch_fill_back_cmd = "patch_process_evalplus.py"
                            # bug_helper_cmd = "python bug_helper.py fix  [bugid] [patch_path]"
                            # get_error_msg_cmd = "error_msg_parse.py"
                            # get_is_pass_cmd = "is_pass_or_not.py"

                            #  after loading the original item, substitute its content with new one
                            if guess_role == 'function':
                                data_item['buggy'] = patch_code
                            else:
                                data_item['buggy'] = original_data_dict[task_id]['prefix'] + '\n' + patch_code + '\n' + original_data_dict[task_id]['suffix']
                                data_item['buggy_hunk_masked'] = patch_code

                            #  patch_fill_back_cmd = "patch_process_evalplus.py"
                            guidance_path = "../data_meta/raw_info_step1.csv"
                            save_dir = "../data/patch_replaced_dirs/"
                            save_patch_dir = os.path.join(save_dir, role)
                            os.makedirs(save_patch_dir, exist_ok=True)
                            
                            md5_value = get_md5(data_item['buggy'])
                            dict_bug_info = {'commit_after': task_id[:40], 'idx': task_id, 'sub_id': str(n_round)+'@'+str(n_tries), 'patch': data_item['buggy'],"md5": md5_value }
                            df_guid = pd.read_csv(guidance_path)
                            df_guid["commit_after"] = df_guid["github"].apply(lambda x: x.replace("/commits/","/commit/").split("/commit/")[-1])
                            df_guid["src_path"] = df_guid["src_path"].apply(lambda x: os.path.join("/out/src_dirs_v2", os.path.basename(x) )  )

                            df_guid["project"] = df_guid["github"].apply(
                                lambda x: (x.replace("/commits/","/commit/").split("/commit/")[0]).replace("http://", "https://").replace(
                                    "https://github.com/", "").replace("https://api.github.com/repos/","").replace("/", "___").replace(".git", ""))
                            meta = patch_process_evalplus.replace_patch(
                                df_g=df_guid,
                                patch_info=dict_bug_info,
                                save_patch_dir=save_patch_dir,
                                role=role,
                                debug=True)
                            # print(meta)
                            p.console.print("==[meta]" * 8, sidx)
                            p.console.print(meta)

                            if meta is None :
                                continue 
                            # build and evaluate the patch generated
                            # project_name = meta['bugid'].split('@')[0]
                            file_path =os.path.abspath(  os.path.join(save_patch_dir, meta['fix_p']) )
                            sha = meta['bugid'].split("@")[-1]
                            # get error message from feedback
                            project_name = meta['bugid'].split('@')[0]
                            xml_log = os.path.join(OUT_DIR, project_name, 'logs',
                                                    'patch_{}_{}.log'.format(sha, md5_value ) )
                            xml_log_xml = os.path.join(OUT_DIR, project_name, 'logs',
                                                    'patch_{}_{}.log.xml'.format(sha, md5_value ) )
                            xml_log_msg = os.path.join(OUT_DIR, project_name, 'logs',
                                                    'patch_{}_{}.msg'.format(sha, md5_value ) )
                            xml_log_status = os.path.join(OUT_DIR, project_name, 'logs',
                                                    'patch_{}_{}.status'.format(sha, md5_value ) )

                            print (
                                xml_log,
                                # xml_log_msg,
                                # xml_log_status, 
                                )

                            if not os.path.isfile(xml_log):
                                build_eval_cmd = f" python3 bug_helper2.py fix {meta['bugid']} {file_path}"
                                # with open("/tmp/cmd.run","w") as ffw:
                                #     ffw.write( build_eval_cmd )
                                    
                                # please use /src ,every is in /src.  
                                #log_in_evaluate = subprocess.run(build_eval_cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,cwd="/src")
                                log_in_evaluate = subprocess.run(build_eval_cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,cwd="/src2")
                                # print("Here is the log in evaluation:", log_in_evaluate.stdout)
                            else:
                                print ("skip.... "*8 )
                                
                            # is_pass = False
                            faile_reason = 0 
                            if  os.path.isfile(xml_log_status):
                                log_content = open(xml_log_status).read()
                                log_content_msg = open(xml_log_msg).read()
                                faile_reason="status is failed"
                                if log_content is not None and ("success"  in log_content.lower() or "pass"  in log_content.lower() )  :
                                    is_pass = True
                                    faile_reason= "pass or succe in status " 
                                data_item['error_msg'] = [log_content_msg] 
                            else:
                                if os.path.isfile(xml_log_msg):
                                    log_content_msg = open(xml_log_msg).read()
                                    # print("The new error_msg is:", log_content_msg)
                                    data_item['error_msg'] = [log_content_msg]
                                    faile_reason= "msg  fail " 
                                elif os.path.isfile(xml_log):
                                    log_content_msg = open(xml_log).read()
                                    # print("The new error_msg is:", log_content_msg)
                                    data_item['error_msg'] = [log_content_msg]
                                    faile_reason= "log  fail " 

                            os.makedirs(f"./tmp/{p_name}",exist_ok=True )
                            with open(f"./tmp/{p_name}/{task_id}--{n_round}-{n_tries}","w") as f :
                                json.dump(obj=data_item,fp=f,indent=4)
                            data_item['error_msg'] = [ mask_path(x) for x  in   data_item['error_msg']  ]
                            if not is_pass  and os.path.isfile(xml_log_xml):
                                buggy_ret, msg = error_msg_parse.extract_failed_test(xml_file=xml_log_xml, project_name=project_name)
                                tmp = data_item['error_msg'] 
                                data_item['error_msg'] = tmp + [ buggy_ret[0]['errmsg'] ]
                                
                                                                
                            if len(str(data_item['error_msg'] ) )> 1024:
                                data_item['error_msg']  =[  str(data_item['error_msg']) [-512:] ]
                                                            # get result of is_pass
                            if not is_pass  :
                                p.console.print("==err===>" * 8, sidx)
                                p.console.print(data_item['error_msg'] )
                            # is_pass= False 
                            # if os.path.isfile(xml_path):
                            #     info = is_pass_or_not.process_thread(
                            #         filename=xml_path, project_name=project_name, fix_role=role)
                            #     print(info)
                            #     if info["remain_fails_c"] <= 0:
                            #         print("pass")
                            #         is_pass = True
                            #     else:
                            #         print("still fail")
                            if not is_pass :
                                print("still fail", faile_reason )

                            # update is_pass according to the results above
                            # is_pass = ...
                            string_round_try = f"{n_round}-{n_tries}"
                            pass_dict[task_id][string_round_try] = is_pass

                            # construct prompt as input
                            fmt = prompt.build_prompt(contract_type="buggy_errmsg", structure=guess_role, **data_item)
                            msg = prompt.build_openai_message(content_user=fmt)
                            msg.update({"idx": task_id})
                            

                            task = msg

            except openai.APIError:
                traceback.print_exc()
                pass
        with open("../data/conversation_pass_results.json", 'a') as f1:
            f1.write(json.dumps(pass_dict))

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", required=True, type=str)
    parser.add_argument("--bs", default=1, type=int)
    parser.add_argument("--temperature", default=0.0, type=float)
    parser.add_argument(
        "--dataset_path", required=True, type=str,
    )
    parser.add_argument("--root", type=str, required=True)
    parser.add_argument("--n_samples", default=1, type=int)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--greedy", action="store_true")
    #  n_samples = n_round * n_tries  for example, 30 = 10*3
    parser.add_argument("--n_round", default=1, type=int)
    parser.add_argument("--n_tries", default=1, type=int)
    parser.add_argument(
        "--original_json_path", required=True, type=str,
    )
    parser.add_argument(
        "--given_sha", default=None, type=str,
    )
    # id_range is list
    args = parser.parse_args()
    if args.given_sha is not None :
        LLVM_IDS = set([args.given_sha])

    if args.greedy and (args.temperature != 0 or args.bs != 1 or args.n_samples != 1):
        args.temperature = 0
        args.bs = 1
        args.n_samples = args.n_round * args.n_tries
        print("Greedy decoding ON (--greedy): setting bs=1, n_samples=1, temperature=0")

    # Make project dir
    os.makedirs(args.root, exist_ok=True)
    # Make dataset dir
    # os.makedirs(os.path.join(args.root, args.dataset), exist_ok=True)
    # Make dir for codes generated by each model

    args.model = args.model.lower()

    model = make_model(
        name=args.model, batch_size=args.bs, temperature=args.temperature
    )

    workdir = os.path.join(
        args.root,
        # args.dataset,
        args.model
        + f"_temp_{args.temperature}"
        # + ("" if args.contract_type == "none" else f"-contract-{args.contract_type}"),
    )

    os.makedirs(workdir, exist_ok=True)

    with open(os.path.join(workdir, "args.txt"), "w") as f:
        f.write(str(args))

    code_generate(args, workdir=workdir, model=model, dataset_path=args.dataset_path)


if __name__ == "__main__":
    '''
    export AZURE_OPENAI_ENDPOINT=xx 
    export AZURE_OPENAI_KEY=xx
    export AZURE_OPENAI_BASE=xx
    python generate.py --model  --root 
    '''
    main()
