import json 
import os 

from evalplus.eval import (
    estimate_pass_at_k,
)

import copy 
import sys 

import numpy as np 
from collections import defaultdict
# code

# -test_fail
# -pass 
# -markdown_fail

from error_report import extract_error_info, format_error_report 


def format_error( x_log_str ):
    if type(x_log_str) == dict :
        x_log_str = str(x_log_str )
    result = extract_error_info( x_log_str )
    formated = format_error_report( result )

    #print ("========>"*8, "\n")
    #print ( result , "formated...")
    return formated 

def identify_item_pass_status( result ):
    x_log_str = None  
    x_pass = False 
    msg_code = 0 
    if  "status_data" in result and "fix_status" in result["status_data"] :
        if "success" in str(result["status_data"]["fix_status"]).lower():

            return {"pass" : True ,"code":"pass", "log_str":None }
        elif "fail" in str(result["status_data"]["fix_status"]).lower():
            fix_status = result["status_data"]["fix_status"]
            fix_log = result["status_data"]["fix_log"]

            #fix_status_dict = format_error( fix_status )
            fix_log= fix_log or fix_status 
            fix_status_dict = {}
            fix_log_dict = format_error( fix_log )

            return {"pass" : False ,"code":"test_fail","log_str":fix_log_dict or fix_status_dict }

    if "patch_msg" in result and ("HTTP 400:" in  result["patch_msg"]  and "markdown extract fail" in  result["patch_msg"]  ):
        return  {"pass" : False ,"code":"markdown_fail"}
    if "status_data" in result and "fix_status" in result["status_data"] and (result["status_data"]["fix_status"] =="" or result["status_data"]["fix_status"] is None ) :
        fix_log = result["status_data"].get("fix_log","")
        return {"pass":False , "code": "compile_fail"}

    if "status_data" in result and  "error" in result["status_data"] and "fix_status" not in result["status_data"]:
        err_str = result["status_data"] ["error"]
        if "/src/defects4c_api_" in err_str and "timed out after" in err_str :
            return {"pass":False , "code": "timeout_api"}


    #print ( result, list( result), result["llm_md5"] )



def read_jsonl(json_p):
    with open( json_p )as fr :
        exist_lines = [json.loads(x) for x in fr.readlines() ]

    exist_lines = [x for x in exist_lines if "status_data" in x or ("patch_msg" in x and ("Patch build failed: HTTP 400" in x["patch_msg"] and "markdown extract fail" in x["patch_msg"] )  ) ]
    return exist_lines 

def infill_blank( results ,jsonp ):
    jsonp  = os.path.basename(jsonp).split(".jsonl")[0]
    expect = 0 
    if jsonp.endswith("_n1"):
        expect = 1 
    if jsonp.endswith("_n5"):
        expect = 5 
    if jsonp.endswith("_n10"):
        expect = 10 
    if jsonp.endswith("_n100"):
        expect = 100 
    task_list = list( results.keys() )
    missing_task = valid_list - set(task_list)
    assert len( missing_task ) >=0 

    assert len( set(task_list) ) <= len( valid_list )  , set(task_list) - valid_list 
    for key in list( results.keys() ):
        vlist = results[key]
        vlist = copy.deepcopy( vlist )
        if len(vlist)>=expect :
            vlist = vlist[:expect ]#
        else:
            vlist = vlist + [{"task_id":key, "pass":False } ] *(expect- len(vlist) )
        assert len(vlist) == expect ,( vlist ,"expect" , expect)
        results[key ] = vlist 

    max_list_len = max( [len(v) for k,v in  results.items() ] )
    assert max_list_len== expect, (expect , "max_list_len", max_list_len , jsonp ) 
    if missing_task :
        for k in missing_task :
            results[k]=  [{"task_id":key, "pass":False } ]* max_list_len 

    final_tasks = [
            t
                for task_list in results.values()
                    for t in task_list
                    ]
    return results 




def get_pass_k( results ):
    # Calculate pass@k.
    total = np.array([len(r) for r in results.values()])
    base_correct = []
    new_correct = []
    for res in results.values():
        bc = sum([r["pass"] == True for r in res])
        base_correct.append(bc)
    base_correct = np.array(base_correct)
    #print ( base_correct.shape ,"base_correct", base_correct )
    pass_at_k = {f"pass@{k}": estimate_pass_at_k(total, base_correct, k).mean() for k in [1, 5, 10, 50,100] if total.min() >= k}
    return pass_at_k 


if __name__=="__main__":
    json_p = sys.argv[-1]
    assert os.path.isfile( json_p ), json_p 
    assert json_p.endswith(".jsonl"), json_p 

    item_list = read_jsonl( json_p )
    #print ( " total read" , len( item_list )) 
    ## first read valid lid 
    valid_list =[json.loads(x)["idx"] for x in  open("../data/prompts/buggy_errmsg/single_function_allinone.saved.jsonl").readlines() ]
    valid_list = set(valid_list)
    assert len(valid_list)==328 


    results = defaultdict( list )
    results_excluded = defaultdict( list )
    big_llm_md5 = {}
    for i in range(len(item_list)):
        item = item_list[i]
        task_id = item["task_id"]
        if task_id not in valid_list:
            continue 
        xpass_item = identify_item_pass_status( result=item )

        key = "{}__{}".format( item["task_id"], item["llm_md5"] )
        if xpass_item is not  None and  key  not in big_llm_md5 : 
            big_llm_md5[ key ] = xpass_item 
        if xpass_item is None and key  in big_llm_md5:
            xpass_item = big_llm_md5[  key ] #item["llm_md5"] ]

        #print ( xpass_item.get("log_str") )

        results[task_id].append(
                {
                        "task_id": task_id,
                        "pass": xpass_item.get("pass") if xpass_item is not None else False,
                        "code": xpass_item.get("code","None") if xpass_item is not None else "None",
                }
        )
        if task_id not in results_excluded:
            results_excluded[task_id].append( 
                         {
                             "task_id": task_id,
                             "pass": xpass_item.get("pass") if xpass_item is not None else False ,
                         }
            )

    results = infill_blank( results, json_p )
    ## greedy 
    is_greedy = True 
    x_json_p = os.path.basename(json_p).split(".jsonl")[0]
    if x_json_p.endswith("_n1") :
        is_greedy = True 



    final_tasks = [
            t
                for task_list in results.values()
                    for t in task_list
                    ]


    pass_at_k = get_pass_k( results )
    pass_at_k.update({"read.len":len(final_tasks), "id":os.path.basename(json_p).split(".jsonl")[0] } )
    print ( "pass_at_k" , pass_at_k )
    code_list = [x.get("code","None") for x in final_tasks ]

    print ("error code", )
    print ( np.unique( code_list, return_counts=True ))




