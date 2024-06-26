# from glob2 import glob 
import os 
from os.path  import join as opj 
import json 
import  re 
import pprint 
# fl = []
import pandas as pd 
# search_dir = "../defectsc_tpl/projects"
# fl += glob( opj( search_dir, "**", "bugs_list_extra.json") )
# search_dir = "../defectsc_tpl/projects_v1"
# fl += glob( opj( search_dir, "**", "bugs_list_new.json") )


def list_all_sha(project_dir="./projects"):
    all_commit = []
    p_list=  os.listdir( project_dir )
    p_list = [x for x in p_list if "___" in x ]
    for x in p_list  :
        json_p = os.path.join( project_dir, x , "bugs_list_new.json")
        with open(json_p) as f :
            data = json.load(f)
            ci_list = [{"project":x , "sha": y["commit_after" ] } for y in data  ]
            all_commit += ci_list 

    df_sha = pd.DataFrame( all_commit )
    print ( df_sha["project"].value_counts().sort_index() )


list_all_sha()

def detect_which_not_run (  ):
    
    def load_json( j_p ):
        project = os.path.basename(  os.path.dirname(j_p) )
        print ("project", project )
        
        with open( j_p ) as f :
            data=  json.load( fp =f )
            data = [x["commit_after"] for x in data]
   
        
        return  [(project,x)  for x in  data ] 
    
    ext=[]
    for one_f in fl :
        ext += load_json( j_p = one_f  )
        


from concurrent.futures import ThreadPoolExecutor
import pandas as pd 

with open("llvm.list") as f :
    llvm_list = [x.strip() for x in f.readlines()]

with open("non_llvm_v1.list") as f :
    llvm_list += [x.strip() for x in f.readlines()]

llvm_list = set( llvm_list )

def load_faile_success_log(a_path):
    with open(a_path ) as f :
        videos= [x for x in f.readlines()] 


    def process_file(i):
        i_p = videos [i ]
        i_p = i_p.strip()
        project= os.path.basename( os.path.dirname( os.path.dirname( i_p ) ) )
        
        i_p_fn = os.path.basename( i_p )

        m= re.match( r"test_(?P<sha>([a-f0-9]{40,}))_(?P<role>[buggy|fix]+)" ,i_p_fn )
        
        m_dict = m.groupdict()
        if m_dict is not None : 
            sha= m_dict["sha"]
            role = m_dict["role"]
        else:
            return None 
        if sha in llvm_list :
            return None 
        # print ( sha, role )
        
        with open(i_p ) as f :
            status = f.read().strip().lower() 
            if 'failed'  in status and len(status)>0: 
                status= "failed"
            elif "success" in status or "pass" in status :
                status = "success"
            else:
                status = "failed"

        return {"sha":sha, "role":role ,"status":status ,"project":project, "fn":i_p_fn }
    
    num_workers = os.cpu_count()-1 
    
    with ThreadPoolExecutor(max_workers=num_workers) as ex:
        predictions = ex.map(process_file, range(len(videos)))

    predictions =  list(predictions)
    predictions = [x  for x in predictions if x is not None ]
    df = pd.DataFrame( predictions )

    # print (df.shape, "df total...", df["status"].value_counts()  )
    # exit()
    df_bug = df[ df["role"]=="buggy" ]
    df_bug = df_bug[ df_bug["status"]=="failed"] 
    # print (df_bug.shape, "df_bug...")
    df_fix = df[ df["role"]=="fix" ]
    df_fix = df_fix[ df_fix["status"]=="success"] 
    # print (df_fix.shape, "df_fix...")
     
    
    
    df_final = df_bug.merge(df_fix, how="inner", on="sha" )
     
    # print ( df_final .shape, df_final.columns )
    df_left_null = df_final[ pd.isnull(df_final["status_x"] ) ]
    df_right_null = df_final[ pd.isnull(df_final["status_y"] ) ]
    # print ("left", df_left_null.shape, "right", df_right_null.shape ) 
    df_same  = df_final[ df_final["status_y"] == df_final["status_x"]  ]
    # print ("same", df_same.shape )
    
    
    uniq_id =  set( df_final["sha"].tolist() )
    
    print (len(uniq_id), "uniq_id")
    #
    print ( "df_final", df_final.columns )
    df_selected = df_final [ ( df_final["sha"].isin(uniq_id )  ) &  (  df_final["role_x"]=="buggy" ) ]
    print ( df_selected["project_x"].value_counts().sort_index() )
    print ("df_selected", df_selected.shape )


            
    # print ("======"*8 )
    #
    #print ( df_bug["status"].describe() , df_bug["status"].value_counts() )
    #print ( df_fix["status"].describe() , df_fix["status"].value_counts() )
    # with open("success_sha_list.txt","w") as f :
    #     f.write("\n".join( list(set(df_final["sha"].tolist() ) ) ) )
        
    
load_faile_success_log( a_path="/out/all.out" ) 






