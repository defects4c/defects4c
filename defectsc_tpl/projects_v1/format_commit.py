import json 
from glob2 import glob 
from tqdm import tqdm  
fl = glob("./**/bugs_list_new.json")



for fl_one in tqdm( fl ):
    
    data = json.load(open(fl_one ))
    
    change_c = 0 
    
    for i in range(len(data)):
        item = data[i]
        if "commit_message" in item :
            del data[i]["commit_message"]
            change_c+=1 
        if "commit_msg" in item :
            del data[i]["commit_msg"]
            change_c+=1 
        
        if change_c ==0:
            continue 
        assert "unittest" in item 
        
        unittest_name = item["unittest"]["name"]
        assert item["c_compile"]["test_flags"] is None , item["c_compile"]
        data[i]["c_compile"]["test_flags"]= unittest_name
    
    if change_c >0 :
        with open(fl_one,"w") as ffff :
            json.dump(obj=data, fp = ffff ,indent=4 ) 
        