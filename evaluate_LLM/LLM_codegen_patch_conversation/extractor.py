import argparse
import json
import re
import os
from tqdm import tqdm

from concurrent.futures import ThreadPoolExecutor
from glob2 import glob


def extract_code_from_markdown_v2(markdown  ):
    if markdown.count("```")%2!=0:
        markdown +="```"

    def select_one_from_list(list_item,strategy="longest"):
        if type(list_item)!=list or len(list_item)<=1:
            return list_item 
        
        if strategy=="longest":
            
            list_item = sorted(  list_item , key=lambda x:len(x) )
            # try :
            list_item = list(list_item)[-1]
            # except :
            #     print (list_item,type(list_item), "???-->")
            assert type(list_item)==str, ( type(list_item), list_item )
            return [list_item]      
          
    def _extract_code_from_markdown_v2(lines: list[str], *, language: str = "cpp") -> list[str]:
        """Outputs extracted code blocks from a list of strings of markdown text"""
        regex = re.compile(
            r"(?P<start>```[^\n]*\n)(?P<code>[\s\S]*?)(?P<end>```)",
            re.DOTALL|re.IGNORECASE | re.MULTILINE,
        )
        blocks = [
              match.group("code") 
            for match in regex.finditer("".join(lines).strip())
        ]
        return blocks 
    def _extract_code_from_markdown_with_language(lines: list[str], *, language: str = "cpp") -> list[str]:
        """Outputs extracted code blocks from a list of strings of markdown text"""
        regex = re.compile(
            r"(?P<start>```"+language+"[^\n]*\n)(?P<code>[\s\S]*?)(?P<end>```)",
            re.DOTALL|re.IGNORECASE | re.MULTILINE,
        )
        blocks = [
              match.group("code") 
            for match in regex.finditer("".join(lines).strip())
        ]
        return blocks 
    list_str = _extract_code_from_markdown_with_language([markdown], language="cpp")
    if list_str is None or len(list_str)<=0 :
        list_str = _extract_code_from_markdown_v2([markdown], language="cpp")

    if list_str is None or len(list_str)<=0:
        return None 
    
    list_str = select_one_from_list( list_str )
    
    if type(list_str)!=list or len(list_str )<=0 :
        return None 
    return list_str[0] 



if __name__ == "__main__":
    with open(
            "../data/patches/gpt-35-turbo_temp_0.7/buggy_errmsg/0c3518e84b668975df03ac8b9620d7bf181bd349___SimplifyCFG.cpp@150@9") as f:
        content = f.read()

        code = extract_code_from_markdown_v2(markdown=content)


