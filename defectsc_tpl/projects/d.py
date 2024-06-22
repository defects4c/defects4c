from glob import glob 
import json
import pandas as pd 
import os 


fl = glob("./**/bug*json")

print (fl )

def read( xp ):
    data= json.load( open(xp) )
    inf_list = []
    for x in data :
        cid = None 
        if x["unittest"]["status"]!="success2":
            continue
        if "type" in x :
            cid=x["type"]["id"]
        url = x["url"]
        url = url.replace("api.github.com/repos/","github.com/").replace("/commits/","/commit/")
        info = {"cve":cid, "url":url}
        inf_list.append( info )
    return inf_list

dd= []
for one_f in fl :
    dd.extend( read( xp = one_f ) )


df = pd.DataFrame( dd )
df.to_csv("cve.list.csv",index=False )
