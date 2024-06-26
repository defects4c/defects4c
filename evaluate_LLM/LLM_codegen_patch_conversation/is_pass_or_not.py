import sys
import json
import xml.etree.ElementTree as ET
import os
import pandas as pd
import traceback
import re

import random

#random.seed(10)


def extract_failed_test(xml_file, project_name=None):
    with open(xml_file) as f:
        data = f.read()
    c = data.count('<?xml ')
    if c == 0:
        return pase_jsonl(xml_file=xml_file)
    if c == 1:
        return _extract_failed_test(xml_file=xml_file, project_name=project_name)
    final_list = []

    for xml_file_content in data.split('<?xml version="1.0" encoding="UTF-8"?>'):
        if len(xml_file_content.strip()) == 0:
            continue
        sha = _get_sha(xml_file=xml_file)
        v, msg = _extract_failed_test(xml_file=xml_file_content, project_name=project_name, sha=sha)
        if len(v) == 0:
            return v, msg
        # print (msg)
        final_list.extend(v)

    return final_list, (-100, None)


def _get_sha(xml_file):
    matches = sha256_pattern.findall(xml_file)
    assert len(matches) > 0, (xml_file, sha256_pattern)
    sha_id = matches[0]
    assert len(sha_id) == 40, (xml_file, matches, sha_id)
    return sha_id
    # sha1 =  os.path.basename( xml_file )
    # sha1 = [x for x in  sha1.split("_") if len(x)==40  ]
    # assert len(sha1) ==1 ,  ( sha1, xml_file )
    # sha = sha1[0]
    # return sha


def _extract_failed_test(xml_file, project_name, sha=None):
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

        if status is not None:
            is_fail = status == "fail"
        elif result is not None:
            is_fail = result == "comleted"
        else:
            failure_element = testcase.find('failure')
            is_fail = failure_element is not None
        ret_list.append(
            {"sha": sha, "name": name, "suitname": testsuite_name, "classname": classname, "testname": testname,
             "is_fail": is_fail, "is_buggy": is_buggy, "errmsg": msg, "errrawmsg": raw})

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
            data = json.loads(data)

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


def load_all_sha(df_match):
    df_match_other = df_match[df_match["project"] != "llvm___llvm-project"]
    df_match_llvm = df_match[df_match["project"] == "llvm___llvm-project"]
    # with open("../func_local/comm_25_v2.txt") as f :
    #     sha_list= [ x.strip() for x in   f.readlines() if len(x.strip())>0 ]
    #     sha_list = set(sha_list)
    with open("llvm_valid_sha_16k.txt") as f:
        assert "16k" in fix_role
        sha_list = [x.strip() for x in f.readlines() if len(x.strip()) > 0]
        sha_list = set(sha_list)

    df_match_llvm = df_match_llvm[df_match_llvm["sha"].isin(sha_list)]
    # print ( df_match_llvm.shape,  )
    assert len(df_match_llvm["sha"].value_counts()) <= len(sha_list), (
    len(sha_list), len(df_match_llvm["sha"].value_counts()))

    df_all = pd.concat([df_match_other, df_match_llvm])
    # print ( df_all.shape )
    return df_all


from itertools import chain
from concurrent.futures import ThreadPoolExecutor

NUM_WORKERS = os.cpu_count() - 1
import re

sha256_pattern = re.compile(r'@@([a-fA-F0-9]{40})___')


def convert_filename_from_zxy2zyx(fix_id_raw):
    fix_id_pre = os.path.splitext(fix_id_raw)[0]
    ext = os.path.splitext(fix_id_raw)[-1]
    fix_id_list = fix_id_pre.split("@")
    fix_id_0 = fix_id_list[-1]
    fix_id_1 = fix_id_list[-2]
    fix_id_list = fix_id_list[:-2] + [fix_id_0] + [fix_id_1]
    fix_id = "@".join(fix_id_list) + ext
    return fix_id


# sha:["testname","testname"]
# RAW_FAILS_DICT = {
#
# }
#
# bug_raw_csv = "../config/is_buggy_raw_match_pattern.csv"
# df_match = pd.read_csv(bug_raw_csv)
# df_match = df_match[df_match["is_buggy_buggy"]]
#
# for one_raw in df_match.to_dict(orient="records"):
#     sha_id = one_raw["sha"]
#     if sha_id in RAW_FAILS_DICT:
#         continue
#     raw_test_cases = df_match[(df_match["sha"] == sha_id) & (df_match["is_fail_buggy"] == 1)]
#     if len(raw_test_cases) <= 0:
#         continue
#     raw_test_cases = raw_test_cases.to_dict(orient="records")
#     raw_test_cases_names = [x["name"] for x in raw_test_cases]
#     raw_test_cases_names = list(set(raw_test_cases_names))
#
#     assert len(raw_test_cases_names) > 0, (raw_test_cases, one_raw,)
#     # print ("type", type(raw_test_cases_names), sha_id )
#     RAW_FAILS_DICT[sha_id] = raw_test_cases_names


def process_thread(filename, project_name, fix_role):
    buggy_ret, msg = extract_failed_test(xml_file=filename, project_name=project_name)
    sha_id = _get_sha(xml_file=filename)

    #
    raw_test_cases_names = RAW_FAILS_DICT[sha_id]

    fix_test_case_name_success = [x["name"] for x in buggy_ret if x["is_fail"] == False]
    remain_fails = list(set(raw_test_cases_names) - set(fix_test_case_name_success))

    fix_id_raw = os.path.basename(filename)
    if "-16k" in fix_role:
        fix_id = convert_filename_from_zxy2zyx(fix_id_raw=fix_id_raw)
    else:
        fix_id = fix_id_raw
    ii = fix_id.split("@")[-2]
    ii = int(ii)
    return {"i": ii, "type": "xml", "sha": sha_id, "fix_id": fix_id, "fix_id_raw": fix_id_raw,
            "remain_fails_c": len(remain_fails), "remain_fails": remain_fails, }


if __name__ == "__main__":

    one_project = "danmar___cppcheck"
    fix_role = "vanilla"
    fix_role = "buggy_errmsg"

    info = process_thread(
        filename="../data/out/danmar___cppcheck/logs/out_099b4435c38dd52ddb38e6b1706d9c988699c082_exec_testsuit_fix_codellama-instruct-34b_temp_0.8__buggy_errmsg@@danmar___cppcheck@@099b4435c38dd52ddb38e6b1706d9c988699c082___preprocessor.cpp@353@66.xml")

    print(info)

    if info["remain_fails_c"] <= 0:
        print("pass")
    else:
        print("still fail")


