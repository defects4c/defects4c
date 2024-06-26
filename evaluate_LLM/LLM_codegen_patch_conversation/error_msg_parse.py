import json
import xml.etree.ElementTree as ET
import os
import pandas as pd
import traceback

import re


def mask_path(error_message):
    path_pattern = re.compile(r'(/[^\s]*\w)')
    paths = path_pattern.findall(error_message)
    sub_path = [(x, os.path.basename(x)) for x in paths]
    for ori, repl in sub_path:
        error_message = error_message.replace(ori, repl)

    return error_message


def extract_llvm_errmsg(testcase_node):
    node_list = testcase_node.findall('failure')
    errmsg_list = []
    raw_errmsg_list = []
    for one_node in node_list:
        content = one_node.text
        if content is None or len(content) <= 0:
            continue
        raw_errmsg_list.append(content)
        content = content.split("Command Output (stderr):")[-1]
        content = mask_path(error_message=content)
        errmsg_list.append(content)

    return raw_errmsg_list, errmsg_list


def extract_systemout_plain_errmsg(testcase_node):
    node_list = testcase_node.findall('system-out')
    errmsg_list = []
    raw_errmsg_list = []
    for one_node in node_list:
        content = one_node.text
        result = content.split("Tests failed:", 1)
        if result is None or len(result) <= 0:
            continue
        content = result[1:]
        content = "\n".join(content)

        raw_errmsg_list.append(content)
        content = mask_path(error_message=content)
        errmsg_list.append(content)

    return raw_errmsg_list, errmsg_list


def libevent___libevent(testcase_node):
    node_list = testcase_node.findall('system-out')
    errmsg_list = []
    raw_errmsg_list = []
    for one_node in node_list:
        content = one_node.text
        if content is None:
            continue
        raw_errmsg_list.append(content)

        if "[err]" in content:
            content = "\n".join([x for x in content.split("\n") if "[err]" in x])

        content = mask_path(error_message=content)
        errmsg_list.append(content)

    return raw_errmsg_list, errmsg_list


def KhronosGroup___SPIRV(testcase_node):
    node_list = testcase_node.findall('system-out')
    errmsg_list = []
    raw_errmsg_list = []
    for one_node in node_list:
        content = one_node.text
        if content is None:
            continue
        raw_errmsg_list.append(content)

        # if "[ RUN      ]" in content :
        #     content ="\n".join( [x for x in content.split("[ RUN      ]")  if "failed" in x.lower() ]  )
        # print ( content )
        c = content
        c = re.sub(re.compile(r'\[ RUN\s+\].+?\n\[ +OK +\].*[^\n]'), "", c)
        c = re.sub(re.compile(r'\[\-+\].*[^\n]'), "", c)
        content = c.replace("\n\n", "")

        content = mask_path(error_message=content)
        errmsg_list.append(content)

    return raw_errmsg_list, errmsg_list


def taobao(testcase_node):
    node_list = testcase_node.findall('system-out')
    errmsg_list = []
    raw_errmsg_list = []
    for one_node in node_list:
        content = one_node.text
        if content is None:
            continue
        raw_errmsg_list.append(content)

        # c= content
        # c= re.sub( re.compile(r'\[ RUN\s+\][^\[]*\[ +OK +\].*[^\n]')   ,  "", c )
        # c = re.sub( re.compile(r'\[\-+\].*[^\n]')   ,  "", c )
        # content = c.replace("\n\n","")

        c = content
        c = re.findall(r'\[ RUN\s+\][^\[]*\[ +FAILED +\].*[^\n]', c)
        content = "\n".join(c)

        content = mask_path(error_message=content)
        errmsg_list.append(content)

    return raw_errmsg_list, errmsg_list


def libyang(testcase_node):
    node_list = testcase_node.findall('system-out')
    errmsg_list = []
    raw_errmsg_list = []
    for one_node in node_list:
        content = one_node.text
        if content is None:
            continue
        raw_errmsg_list.append(content)

        c = content
        # c= re.findall(r'\[ RUN\s+\][^\[]*\[\s+ERROR\s+\][^\[]*\[\s+LINE\s+\][^\[]*\[ +FAILED +\].*[^\n]'   , c )
        c = re.findall(r'\[\s+[ERROR|LINE|FAILED]+\s+\].*[^\n]', c)
        content = "\n".join(c)

        content = mask_path(error_message=content)
        errmsg_list.append(content)

    return raw_errmsg_list, errmsg_list


def extract_systemout_default(testcase_node):
    node_list = testcase_node.findall('system-out')
    errmsg_list = []
    raw_errmsg_list = []
    for one_node in node_list:
        content = one_node.text
        if content is None:
            continue
        raw_errmsg_list.append(content)
        content = mask_path(error_message=content)
        errmsg_list.append(content)

    return raw_errmsg_list, errmsg_list


def extract_failed_test(xml_file, project_name=''):
    with open(xml_file) as f:
        data = f.read()
    c = data.count('<?xml ')
    # print (c,xml_file,"c---")
    if c == 0:
        return pase_jsonl(xml_file=xml_file)
    if c == 1:
        return _extract_failed_test(xml_file=xml_file, project_name=project_name)
    final_list = []

    for xml_file_content in data.split('<?xml version="1.0" encoding="UTF-8"?>'):
        if len(xml_file_content.strip()) == 0:
            continue
        sha = _get_sha(xml_file=xml_file)
        v, msg = _extract_failed_test(xml_file=xml_file_content, sha=sha, project_name=project_name)
        if len(v) == 0:
            return v, msg
            # print (msg)
        final_list.extend(v)

    return final_list, (-100, None)


def _get_sha(xml_file):
    sha1 = os.path.basename(xml_file)
    sha1 = [x for x in sha1.split("_") if len(x) == 40 and "." not in x ]
    assert len(sha1) == 1, (sha1)
    sha = sha1[0]
    return sha
def _get_sha_v2(xml_file):
    sha1 = os.path.basename(xml_file)
    sha1 = [x for x in sha1.split("_") if len(x) == 40]
    assert len(sha1) == 1, (sha1)
    sha = sha1[0]
    return sha


def _extract_failed_test(xml_file, sha=None, project_name=''):
    try:
        if xml_file.endswith(".xml"):
            # print ("load from file")
            tree = ET.parse(xml_file)
            root = tree.getroot()
        else:
            tree = ET.fromstring(xml_file)
            root = tree
    except:
        ## man
        traceback.print_exc()
        print(xml_file, "fail read")
        return [], (-3, "read error ")

    ret_list = []

    if sha is None:
        sha = _get_sha(xml_file=xml_file)

    is_buggy = "_buggy.xml" in os.path.basename(xml_file)

    testsuite_list = []
    # print (xml_file, "testsuite--->",dir(root),  len( root.findall('.//testsuite')) )
    for testsuite in root.findall('.//testsuite'):
        testsuite_name = testsuite.get('classname')
        for testcase in testsuite.findall('.//testcase'):
            testsuite_list.append((testsuite_name, testcase))
    if len(testsuite_list) == 0:
        testsuite_list = root.findall('.//testcase')

    total_sub_case = 0
    for testcase_tuple in testsuite_list:
        testsuite_name = None
        if type(testcase_tuple) == tuple:
            testsuite_name, testcase = testcase_tuple
        else:
            testcase = testcase_tuple
        # print (dir(testcase))
        # v = testcase.findall(".//failure")
        classname = testcase.get('classname')
        testname = testcase.get('name')

        name = os.path.join(classname, testname) if classname != testname else testname
        result = testcase.get("result")
        status = testcase.get("status")

        raw, msg = None, None
        # if project_name=="llvm___llvm-project":
        #     raw, msg=  extract_llvm_errmsg( testcase_node= testcase )
        # elif project_name=="danmar___cppcheck":
        #     raw, msg=  extract_systemout_plain_errmsg( testcase_node= testcase )
        # elif project_name in ["uncrustify___uncrustify"]:
        #     raw, msg=  extract_systemout_default( testcase_node= testcase )
        # elif project_name=="libevent___libevent":
        #     raw, msg=  libevent___libevent( testcase_node= testcase )
        # elif project_name=="KhronosGroup___SPIRV-Tools":
        #     raw, msg=  KhronosGroup___SPIRV( testcase_node= testcase )
        if project_name in FILTER_FUNC:
            FUNC_X = FILTER_FUNC[project_name]
            raw, msg = FUNC_X(testcase_node=testcase)
        else:
            raw, msg = extract_systemout_default(testcase_node=testcase)

        # if msg is not None and len(msg)>0 and "exec_testsuit_raw" not in xml_file:
        #     with open("/tmp/{}.t.txt".format( os.path.basename(xml_file) ) ,"a") as f :
        #         f.write( ET.tostring(testcase).decode("utf-8") )
        #     with open("/tmp/{}.txt".format( os.path.basename(xml_file) ) ,"a") as f :
        #         msg = "\n".join( msg )
        #         f.write( msg )
        #         f.write( "\n\n\n"*4 )
        #     with open("/tmp/{}.raw.txt".format( os.path.basename(xml_file) ) ,"a") as f :
        #         raw = "\n".join( raw )
        #         f.write( raw )
        # sub_case = extract_subcase(node=testcase,xml_file =xml_file )
        # total_sub_case+=sub_case
        # print (sub_case, "sub_case")
        if status is not None:
            is_fail = status == "fail"
        elif result is not None:
            is_fail = result == "comleted"
        else:
            failure_element = testcase.find('failure')
            is_fail = failure_element is not None
        # print(f'Failed testcase: {classname}/{testname}')
        # ret_list.append( {"sha":sha ,  "classname":classname,"testname":testname, "is_fail":is_fail , "is_buggy":is_buggy  })
        # ret_list.append( {"sha":sha ,  "name":name ,   "suitname":testsuite_name,     "classname":classname,"testname":testname,       "is_fail":is_fail , "is_buggy":is_buggy  , "sub_case":sub_case })
        ret_list.append(
            {"sha": sha, "name": name, "suitname": testsuite_name, "classname": classname, "testname": testname,
             "is_fail": is_fail, "is_buggy": is_buggy, "errmsg": msg, "errrawmsg": raw})

    # if total_sub_case <=0 and "llvm" not in  xml_file :
    #     print ("====>", xml_file )
    return ret_list, (1, None)


def pase_jsonl(xml_file):
    print(xml_file, "xml_file")
    ret_list = []

    with open(xml_file) as f:
        data_list = f.readlines()
        for data in data_list:
            data = data.strip()
            if data.endswith("\\n"):
                data = data[:-2].strip()
            # .replace("}\\n","}").replace("}\\n","}")
            print(data, "<---")
            data = json.loads(data)
            # data= [ json.loads(x.strip()) for x in f.readlines() if len(x.strip())>0 ]

            is_buggy = "_buggy.xml" in os.path.basename(xml_file)
            sha = _get_sha(xml_file=xml_file)

            for one_data in data:

                for cls, cls_v in data["tests"].items():
                    if "expected" in cls_v and "actual" in cls_v:
                        name = cls
                        is_fail = cls_v["expected"] == "PASS" and cls_v["actual"] != "PASS"
                        ret_list.append({"sha": sha, "name": name, "is_fail": is_fail, "is_buggy": is_buggy})
                    else:
                        for cls1, cls1_v in cls_v.items():
                            assert "expected" in cls1_v and "actual" in cls1_v, (
                            cls1_v, "expected" in cls1_v, "actual" in cls1_v)
                            name = "{}.{}".format(cls, cls1)
                            is_fail = cls1_v["expected"] == "PASS" and cls1_v["actual"] != "PASS"
                            ret_list.append({"sha": sha, "name": name, "is_fail": is_fail, "is_buggy": is_buggy})

    return ret_list, (1, None)


cur_dir = os.path.dirname(os.path.abspath(__file__))
FILTER_FUNC = {
    "taosdata___TDengine": taobao,
    "llvm___llvm-project": extract_llvm_errmsg,
    "danmar___cppcheck": extract_systemout_plain_errmsg,
    "uncrustify___uncrustify": extract_systemout_default,
    "libevent___libevent": libevent___libevent,
    "KhronosGroup___SPIRV-Tools": KhronosGroup___SPIRV,
    "zeromq___libzmq": extract_systemout_default,
    "facebook___rocksdb": extract_systemout_default,
    "ggerganov___llama.cpp": extract_systemout_default,
    "skypjack___entt": taobao,
    "fmtlib___fmt": taobao,
    "bblanchon___ArduinoJson": taobao,
    "CLIUtils___CLI11": extract_systemout_default,
    "SOCI___soci": extract_systemout_default,
    "DynamoRIO___dynamorio": extract_systemout_default,
    "CESNET___libyang": libyang,
    "apache___arrow": taobao,
    "nanomsg___nng": extract_systemout_default,
    "awslabs___aws-c-common": extract_systemout_default,
}


import re
import os
def extract_content_from_log(input_string, start_word="FAILED:", end_word="ninja: build stopped: subcommand failed"):
    pattern = re.compile(f'{re.escape(start_word)}(.*?){re.escape(end_word)}', re.DOTALL)
    match = pattern.search(input_string)

    if match:
        xc= match.group(1)
        return [xc], (1,None)
    else:
        return [],(-1, None)





if __name__ == "__main__":
    buggy_path = "../data/out/danmar___cppcheck/logs/out_53734a3da1dd394aee9398127692b0e38e9ffa9f_exec_testsuit_buggy.xml"
    project_name = "danmar___cppcheck"
    buggy_ret, msg = extract_failed_test(xml_file=buggy_path)

    print(buggy_ret)
