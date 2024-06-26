"""
structures copy from jiaolong's PromptCreator.py
"""
import os 
import json 
import sys 

def build_prompt(contract_type="vanilla", structure="hunk",**kwargs ):
    footer = """Please provide the correct line following commit message at the infill location."""
    footer_func = """Please fix bugs in the function and tell me the complete fixed function."""
    def build_commit(commit_msg,**kwargs):
        return f"""
The commit message is:` {commit_msg}`
        """
    def build_buggy_func(buggy,**kwargs):
        return  f"""
The following function contains bugs:```cpp\n{buggy}```\n """

    def build_buggy(prefix,suffix,buggy_hunk_masked,**kwargs):
        INFILL= ">>> [ INFILL ] <<<"
        return  f"""
The following code contains a buggy {structure} that has been removed.
```cpp
{prefix}
{INFILL}
{suffix}
```
This was the original buggy {structure} which was removed by the infill location
```cpp
// buggy hunk
{buggy_hunk_masked}
```
"""
    def build_comment(user_comments=None ,**kwargs):
        if user_comments is None :
            return None  
        user_comments = [user_comments] if type(user_comments)!=list else user_comments 
        cmt_str = "\n".join(user_comments )
        return f""" The comments from users are: {cmt_str} """
   
    # def build_errormsg(failing_test=None,failing_line=None, error_msg=None ,**kwargs):
    #     ret_list= [f"""The code fails on this test: `{failing_test}()` """ if failing_test is not None else "",
    #             f"""on this test line: `{failing_line}` """ if failing_line is not None else "",
    #             f"""with the following test error: {error_msg} """ if error_msg is not None else "" , ] 
    #     return "\n".join( [x for x in ret_list if x is not None ])
    def build_errormsg(failing_test=None,failing_line=None, error_msg=None ,**kwargs):
        ret_list= [f"""The code fails on this test: `{failing_test}()` """ if failing_test is not None else "",
                f"""on this test line: `{failing_line}` """ if failing_line is not None else "",
                f"""with the following test error: {error_msg} """ if error_msg is not None else "" , ] 
        return "\n".join( [x for x in ret_list if x is not None ])


    def build_extenal_headers(header_files_declarations=None  ,**kwargs):
        if header_files_declarations is None : return None 
        declares = "\n".join(header_files_declarations) 
        signature_format = f""" Given the following definition for a C/C++ function,
        ```cpp
        {declares}
        ```
        the fix function signature should match the provided definition. Ensure that the data types, parameter names, and return type align correctly."""
        return signature_format 
    
    
    if contract_type=="vanilla":
        msg = [
            build_buggy( **kwargs ) if structure !="function" else build_buggy_func(**kwargs),
            build_commit(**kwargs ), 
            footer_func if structure == 'function' else footer,
            ]
        return "\n".join(msg) 
    
    elif contract_type=="buggy_errmsg" or contract_type=="buggy_errmsg_cve":
        msg = [
            build_buggy( **kwargs ) if structure !="function" else build_buggy_func(**kwargs),
            build_errormsg(**kwargs ), 
            footer_func if structure == 'function' else footer,
            ]
        return "\n".join(msg) 
    
    return None 
    

def load_data(json_p):
    with open(json_p) as f :
        data=  json.load(f)
    return data 

SYSTEM_PROMPT= "You are a C/CPP code program repair expert"
def build_openai_message(content_user, temperature=0.01 ):
    return {   "temperature":temperature  ,  
            "prompt":[{"role":"system","content":SYSTEM_PROMPT},{"role":"user","content":content_user}],
        }

    
if __name__=="__main__":
    '''
    python prompt.py ../data/corpus/vanilla/single_function_repair.json  

    python prompt.py ../data/corpus/buggy_errmsg/single_function_repair.json  
    
    '''
    json_p = sys.argv[-1]
    assert os.path.isfile(json_p) and "json" in os.path.basename(json_p) , (json_p, "not match .json or not exist")
    guess_role =  "hunk" if "_hunk_" in os.path.basename(json_p) else "line" if "_line_" in os.path.basename(json_p) else "function"
    
    # print ("guess_role", guess_role ,"-->", json_p )
    data =  load_data(json_p)
    contract_type = os.path.basename(os.path.dirname(json_p))
    assert contract_type in ["vanilla","buggy_errmsg","buggy_errmsg_cve"],(contract_type, json_p )
    
    save_json_p =os.path.join("../data", "prompts", contract_type , os.path.basename( json_p).replace(".json",".saved.jsonl") )
    os.makedirs( os.path.dirname(save_json_p) , exist_ok=True )
    assert  os.path.basename(save_json_p) != os.path.basename(json_p) , (json_p, save_json_p )
    print ("===> [save]==>", save_json_p )
    
    with open(save_json_p, "w" ) as fw:
        
        for idx, item  in data.items(): 
            # print (idx,"\n\n\n\n","======>"*8 )
            fmt = build_prompt(contract_type=contract_type,structure=guess_role , **item )
            msg = build_openai_message(content_user=fmt )
            msg.update({"idx":idx})
            fw.write( json.dumps(msg))
            fw.write("\n")
    
    
    
    
    
    
    
    
    
    
    