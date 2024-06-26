import os 
import subprocess 
from concurrent.futures import ThreadPoolExecutor

import numpy as np 
import pandas as pd 
# find /out -name 'patch*.log' -maxdepth 3  > /out/collect.log 

search_dir = "/out/collect.log"
save_status  =search_dir + ".csv"


'''
-2 only log
-1 status fail
1 status pass  
'''

num_workers = os.cpu_count()-1 

if __name__=="__main__":
    ## update 
    # Define the command
    
    command = "find /out/llvm___llvm-project/logs  -name 'patch*.log' -maxdepth 3 > /out/collect.log"
    try:
        subprocess.run(command, shell=True, check=True)
        print("Command executed successfully!")
    except subprocess.CalledProcessError as e:
        print(f"Command failed with error: {e}")
        exit(1)
    print ("done1")
    command = "find /out/*/logs  -name 'patch*.log' -maxdepth 3 >> /out/collect.log"
    try:
        subprocess.run(command, shell=True, check=True)
        print("Command executed successfully!")
    except subprocess.CalledProcessError as e:
        print(f"Command failed with error: {e}")
        exit(1)
    print ("done2")
    
    
    with open(search_dir) as f :
        videos = f.readlines() 
        videos = [x.strip() for x in videos ]
        print ("there are total file" , len(videos) )
    def process_file(i):
        if i %500 ==0:
            print (i)
        fnx = videos[i]
        status = -3 
        if os.path.isfile( fnx ):
            status = -2 
            fny= fnx.replace(".log",".status")
            if os.path.isfile(fny):
                status = -1 
                with open(fny ) as ff :
                    data = ff.read()
                    data = data.lower() if data is not None else data 
                if "success" in data or "pass" in data :
                    status = 1 
        
        
        fn = os.path.basename(fnx)
        fn = fn.split(".")[0]
        if fn.count("_")!=2 :
            return None 
        fninfo = fn.split("_")
        md5= fninfo[-1]
        sha= fninfo[1]
        if len(sha)!=40 :
            return None 
        # patch_509d721c2b61088c1e491c330c48b0cc01dc191e_c525c45111ce00a5f6da58a625968007.log 
        return {"idx": os.path.basename(fnx), "status": status }
        
    
    with ThreadPoolExecutor(max_workers=num_workers) as ex:
        predictions = ex.map(process_file, range(len(videos)))

    predictions = list(predictions)
    
    predictions_status = [x["status"] for x in predictions ]


    print ( np.unique(predictions_status,return_counts=True ) )

    df = pd.DataFrame( predictions )
    df.to_csv(save_status  ,index=False )


