import os 
import pandas as pd 
import json 
import subprocess
import jmespath 
import sys  
import traceback 

cur_dir = os.path.dirname( os.path.abspath(__file__) )

print (cur_dir ,"cur_d")

def read_openai(json_p ):
    x_item= None 
    if json_p.endswith(".jsonl"):
        with open(json_p) as f :
            x_item = [json.loads(x.strip()) for x in f.readlines () ]
    else:
        with open(json_p) as f :
            x_item  = json.load(f)
        
    ret_list= []

    for one_item in x_item :
        big_key = one_item["idx"]
        sub_id = one_item["md5"]
        patch =  one_item ["patch"]
        commit_after = big_key.split("___")[0]
        if patch is not None :
            ret = {"commit_after":commit_after ,"idx":big_key,  "s_idx":sub_id , "patch":patch, "md5":one_item["md5"] }
            ret_list.append( ret )

    return ret_list 

    
def replace_patch(  df_g , patch_info, save_patch_dir  , role =None ,debug=False  ):
    assert "idx" in patch_info , (type(patch_info), patch_info) 
    assert "patch" in patch_info  , (type(patch_info), patch_info)
    assert os.path.isdir(save_patch_dir) , save_patch_dir 
    
    # if role is None :
    #     role = os.path.basename( save_patch_dir )
    # assert "patch" in role.lower()   ,(role,save_patch_dir)
    
    commit_id = patch_info["commit_after"]
    
    cur_df  =  df_g[ df_g["commit_after"]==commit_id ].to_dict(orient="records")
    if len(cur_df)<=0 :
        print ("miss...", commit_id)
        return None 
    assert len(cur_df)==1, (cur_df , commit_id )
    
    cur_df = cur_df[-1]
    # print (cur_df)
    # exit()
    
    src_path = cur_df["src_path"]
    func_start_byte = cur_df["func_start_byte"]
    func_end_byte = cur_df["func_end_byte"]
    
    project  = cur_df["project"]
    # print ("src_path" , src_path, "replace_content ", )
    assert os.path.isfile(src_path) , src_path
    try :
        with open(src_path ) as f :
            content = f.read() 
    except :
        traceback.print_exc()
        return None 
    
    replace_content = patch_info["patch"]
    if replace_content is None :
        return None 
    # print ( type(replace_content), "replace_content" , type(content),  func_start_byte , func_end_byte )
    # content[func_start_byte: func_end_byte ] = replace_content 
    content = content[:func_start_byte] + replace_content + content[func_end_byte:]
    # print ("list(patch_info) , ", list(patch_info) , )
    # build save patch filename 
    # fn_prefix , fn_ext = os.path.splitext( os.path.basename( patch_info ["b_idx"] ) )
    # fn_prefix  =  os.path.basename( patch_info ["b_idx"] )
    md5 = patch_info["md5"]
     
    fix_filename = "{}/{}@{}#{}".format(project, md5  ,   patch_info ["idx"] , patch_info["sub_id"]   )
    fix_p = os.path.join(save_patch_dir,fix_filename ) 
    fix_p = os.path.abspath( fix_p )
    
    if not  os.path.isdir( os.path.dirname(fix_p) ):
        os.makedirs(  os.path.dirname(fix_p) , exist_ok=True  )
    
    # if os.path.isfile(fix_p) :
    #     print ("file iexsit ...")
    #     return None 
    # print ("fix_p", fix_p, replace_content is None , "replace_content is None , " )
    with open( fix_p  , "w") as f :
        f.write( content )
    
    if debug :
        patch_filename = "{}/{}@{}#{}.patch".format(project, md5  ,   patch_info ["idx"]  , patch_info["sub_id"]    )
        patch_p  = os.path.join(save_patch_dir,patch_filename ) 
        diff_two_file( pre_f= src_path , tgt_f=fix_p  , save_patch=patch_p )
    
    def get_buggid_from_filename(fn_prefix ):
        # fix_p  = os.path.basename(fix_p )
        buggid = "{}@{}".format(project, fn_prefix  .split("___")[0] )
        return buggid 
    
    meta=  {"dir":os.path.join("/patches",project, ), "bugid":get_buggid_from_filename(fn_prefix=patch_info["idx"]), "fix_p":fix_p  }
    # print (meta) 
    
    return meta 
    
def diff_two_file( pre_f, tgt_f , save_patch ):
    command = f"git diff --no-index {pre_f} {tgt_f}  > {save_patch} "
    # print (command )
    result = subprocess.run(command, shell=True)
    # if result.returncode == 0:
    #     pass 
    #     # print("Build successful")
    # else:
    #     print(f"Build failed. Check {save_patch} for error messages.")
    