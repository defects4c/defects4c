import os, sys

"""
modify from container 
"""

from os.path import join as opj
import json

import logging

import shlex
import subprocess

import jmespath
import shutil

import backoff


def _load_config(repo_dir=None):
    if repo_dir is None:
        repo_dir = OUT_DIR

    with open(opj(repo_dir, BUG_P)) as f:
        conf_dict = json.load(f)
    return conf_dict


def reproduce(bug_id):
    config_dict = _load_config()

    for item in config_dict:
        if item["commit_after"] == bug_id:
            print(item)

    return item


# folder  structure
# -- root_dir
#   bug_helper.py
#   projects
#       apple__swift
#       llvm___clang
# -- workspace == root_dir/projects/apple__swift
#   project.json
#   bugs_list.json
#   out_dir
# --  out_dir   == root_dir/projects/apple__swift/out_dir
#   out_[bug_id]
#   git_repo_dir --> git clone
#   patch_dir  --> your patch
# -- patch_file
#    xxxx.patch --> diff buggy.py my_fix.py >> xxxx.patch
#    python bug_helper.py fix [bug_id] xxxx.patch

'''
 x.py list  --> list whatever
 x.py list tensorflow/tensorflow_js  --> list this repo   
 x.py info [bug_id]
 x.py fix [bug_id] [patch_path]
     --> x.py compile [bug_id] 
     --> then x.py fix 
 x.py reproduce [bug_id]
     --> x.py compile [bug_id] 
     --> x.py reproduce [bug_id] 
'''


class Defect4C_BUG:
    project_meta = {}
    bug_list = []

    repo_dir = None
    out_root_dir = None

    def _docker_(self):
        cmd = "\n\n docker run --rm -it  \
        --ipc=host \
        -v \"{}:/out\" \
        base/defect4c:latest sh -c \"python3  {} \" \n\n".format(self.out_root_dir, " ".join(sys.argv))
        print(cmd)

    def __init__(self,
                 root_dir,
                 out_root_dir,
                 repo_name,
                 workspace=None,
                 commit_id=None,
                 delete_repo=False,
                 ):

        self.workspace = workspace if workspace is not None else opj(root_dir, "projects", repo_name)
        self.out_root_dir = out_root_dir

        if os.environ.get("AM_I_IN_A_DOCKER_CONTAINER", None) is None:
            self._docker_()
            raise Exception("outside of container")

        project_path = opj(workspace, PROJECT_META_P)
        bug_path = opj(workspace, BUG_META_P)

        logger.info("now read the project meta from {}".format(project_path))
        logger.info("now read the bug.list meta from {}".format(bug_path))

        self.project_meta = json.load(open(project_path))

        logger.info("=======log env ========")
        self._load_env()

        self.bug_list = json.load(open(bug_path))

        self.commit_id = commit_id

        self.bug = [x for x in self.bug_list if x["commit_after"] == commit_id]
        assert len(self.bug) > 0
        self.bug = self.bug[0]

        self.repo_dir = opj(self.out_root_dir, GITHUB_SRC)
        buid_plus = jmespath.search("c_compile.root_dir", self.project_meta)

        self.build_dir = opj(self.out_root_dir, GITHUB_SRC,
                             f'build_{commit_id}')  # if buid_plus is None else opj( self.out_root_dir,GITHUB_SRC, f'build_{commit_id}'  , buid_plus )
        self.build_dir_buggy = opj(self.out_root_dir, GITHUB_SRC,
                                   f'build_{commit_id}')  # if buid_plus is None else opj( self.out_root_dir,GITHUB_SRC, f'build_{commit_id}'  , buid_plus )
        self.download_dir = opj(self.out_root_dir, DOWNLOAD_SRC, f'{repo_name}@{commit_id}')
        os.makedirs(self.download_dir, exist_ok=True)

        self.stdout_dir = opj(self.out_root_dir, "logs")  # ,  f'out_{commit_id}'  )
        # self.stdout_dir = opj( self.out_root_dir,"logs",  f'out_{commit_id}'  )
        os.makedirs(self.stdout_dir, exist_ok=True)

        # redict stdout
        self.stdout_file = sys.stdout

        ### overwrite
        self.defined_builder = jmespath.search("c_compile.build", self.project_meta)  # =="ninja"
        self.defined_builder = jmespath.search("c_compile.build", self.bug) if jmespath.search("c_compile.build",
                                                                                               self.bug) is not None else self.defined_builder
        # assert  type(self.defined_builder) ==bool

        self.run_clone(delete_repo=delete_repo)

    def _load_env(self):
        '''
          - k=v
            k2=v2
            ---> {k:v, k2:v2}
        '''
        self._env = dict(os.environ)
        env = self.project_meta.get("env", [])
        res = dict([list(map(str.strip, one_env.split('=', 1))) for one_env in env])
        print(res, "res//..")
        self._env.update(res)

    def _exec(self, cmd_info):
        if type(cmd_info) == dict:
            one_cmd = cmd_info.pop("cmd")
        else:
            one_cmd = str(cmd_info)
            cmd_info = {"cwd": self.out_root_dir}

        logger.info(">>>>>")
        logger.info(one_cmd)
        logger.info(cmd_info)
        logger.info("<<<<<")

        one_cmd = shlex.split(one_cmd)
        proc = subprocess.run(one_cmd,
                              stdout=self.stdout_file,
                              stderr=self.stdout_file,
                              **cmd_info,
                              env=self._env,
                              )

    def run_clone(self, delete_repo=True):
        def get_clone():
            return self.project_meta["main_repo"]

        repo_dir = self.repo_dir
        if os.path.isdir(repo_dir):
            if not delete_repo:
                logger.info("the directory already exist, {}".format(self, repo_dir))
                pass
                # return False
            else:
                logger.info(" the folder exist, now delete it ==> {}".format(repo_dir))
                shutil.rmtree(repo_dir)

        main_repo = get_clone()

        logger.info("git clone  {}  -=========> into {}".format(main_repo, os.path.dirname(repo_dir)))
        os.makedirs(os.path.dirname(repo_dir), exist_ok=True)

        if not os.path.isdir(opj(self.repo_dir, ".git")):
            one_cmd = f"git clone --recursive {main_repo} {self.repo_dir} "
            self._exec(cmd_info=one_cmd)

            logger.info("install pre_install.sh -=========>")
            one_cmd = f" cp {self.workspace}/pre_install.sh {self.repo_dir} "
            self._exec(cmd_info={"cmd": one_cmd, "cwd": self.workspace})
            one_cmd = f" bash  pre_install.sh "
            self._exec(cmd_info={"cmd": one_cmd, "cwd": self.repo_dir})

    def pre_build(self):
        logger.info("install pre_build.sh -=========>")
        one_cmd = f" cp {self.workspace}/*.sh {self.repo_dir} "
        subprocess.call(one_cmd, shell=True, cwd=self.workspace)
        # self._exec(cmd_info={"cmd":one_cmd, "cwd":self.workspace ,"shell":True } )
        one_cmd = f" bash  pre_build.sh "
        self._exec(cmd_info={"cmd": one_cmd, "cwd": self.repo_dir})

    def run_configure(self, defined_builder=True):
        def get_configure(build_dir="build", defined_builder=True):
            flags_raw = self.project_meta.get("c_compile", {"build_flags": []}).get("build_flags", [])
            flags_override = self.bug.get("c_compile", {"build_flags": []}).get("build_flags", [])
            flags_override = flags_override if flags_override is not None else []
            flags = " ".join(flags_raw + flags_override)

            if defined_builder.lower() == "ninja":
                return f"cmake -G Ninja -B {build_dir} {flags} "
            elif defined_builder.lower() == "cmake":
                return f"cmake  -B {build_dir} {flags} -S . "
            elif defined_builder.lower().startswith("bash"):
                return f" echo 'not need run configure, is bash '"
                # return f"{defined_builder} {build_dir}  {flags} "
            else:
                return f"cmake  -B {build_dir} {flags} -S . "

        build_dir = os.path.basename(self.build_dir)

        conf_cmd = get_configure(build_dir=build_dir, defined_builder=self.defined_builder)

        self._exec(cmd_info={"cmd": conf_cmd, "cwd": self.repo_dir})

    @backoff.on_exception(
        wait_gen=backoff.expo,
        exception=(
                subprocess.CalledProcessError,
        ),
        max_tries=1,
    )
    def run_build(self, defined_builder=True):
        def get_build(build_dir="build", defined_builder=True):
            flags_raw = self.project_meta.get("c_compile", {"build_flags": []}).get("build_flags", [])
            flags_override = self.bug.get("c_compile", {"build_flags": []}).get("build_flags", [])
            flags_override = flags_override if flags_override is not None else []
            flags = " ".join(flags_raw + flags_override)

            if defined_builder.lower() == "ninja":
                return f"ninja -C {build_dir}"
            elif defined_builder.lower() == "cmake":
                return f"  make -j {NPROC} -C {build_dir} --silent "
            elif defined_builder.lower().startswith("bash"):
                return f"{defined_builder} {build_dir}  {flags} "
            else:
                return f"  make -j {NPROC} -C {build_dir} --silent "

        build_dir = os.path.basename(self.build_dir)
        cmd_info = get_build(build_dir=build_dir, defined_builder=defined_builder)
        self._exec(cmd_info={"cmd": cmd_info, "cwd": self.repo_dir, "check": True})

    def run_ctest_summary(self):
        build_dir = os.path.basename(self.build_dir)
        cmd_info = f"ctest --test-dir {build_dir} -N "
        print("cmd_info", cmd_info)
        self._exec(cmd_info={"cmd": cmd_info, "cwd": self.repo_dir, "timeout": TIMEOUT})

    def run_ctest_all(self, junt_xml="/tmp/123.xml"):
        build_dir = os.path.basename(self.build_dir)
        cmd_info = f"ctest --test-dir {build_dir} -j {NPROC} -VV --output-junit {junt_xml}  "
        print("cmd_info", cmd_info)
        self._exec(cmd_info={"cmd": cmd_info, "cwd": self.repo_dir, "timeout": TIMEOUT})

    def run_ctest_one(self, test_name, junt_xml="/tmp/123.xml"):
        assert test_name is not None and type(test_name) == str and len(test_name) > 0, (
        test_name, f"ctest -R {test_name} ??")
        build_dir = os.path.basename(self.build_dir)
        cmd_info = f"ctest --test-dir {build_dir} -R \"{test_name}\" -VV --output-junit {junt_xml}   "
        print("cmd_info", cmd_info)
        self._exec(cmd_info={"cmd": cmd_info, "cwd": self.repo_dir, "timeout": TIMEOUT})

    def run_test_script(self, test_script, junt_xml="/tmp/123.xml"):
        build_dir = os.path.basename(self.build_dir)
        cmd_info = f"{test_script}  {build_dir}  {junt_xml} "
        print("cmd_info", cmd_info)
        self._exec(cmd_info={"cmd": cmd_info, "cwd": self.repo_dir, "timeout": TIMEOUT})

    def reproduce(self, commit_id=None, delete=True):
        '''
        delete --> delete the [build_dir] if exist
        '''
        commit_after_id = self.bug["commit_after"]
        commit_id = self.commit_id if commit_id is None else commit_id

        assert commit_id == commit_after_id, ("you input ", commit_id, "but we believe it not belong to ", self.bug)

        commit_before_id = self.bug["commit_before"]
        file_list = self.bug["files"]["src"]
        assert len(file_list) > 0, (self.bug, file_list)

        if delete and os.path.isdir(self.build_dir):
            logger.info(" the folder exist, now delete it ==> {}".format(self.build_dir))
            shutil.rmtree(self.build_dir)
        if delete and os.path.isdir(self.build_dir_buggy):
            logger.info(" the folder exist, now delete it ==> {}".format(self.build_dir_buggy))
            shutil.rmtree(self.build_dir_buggy)

        def get_status():
            cmd = "git rev-parse HEAD"
            self._exec(cmd_info={"cmd": cmd, "cwd": self.repo_dir})

        def checkout_commit():
            cmd = f"git checkout -f {commit_id}"
            self._exec(cmd_info={"cmd": cmd, "cwd": self.repo_dir, "check": True})

        # def exec_testsuit():
        #     self.pre_build()
        #     self.run_configure(defined_builder=self.defined_builder )
        #     self.run_build(defined_builder=self.defined_builder )
        #     #self.run_ctest_all()

        def checkout_reproducing_buggy(commit_before_id, file_list):
            for one_file in file_list:
                cmd = f"git checkout {commit_before_id} -- {one_file}"
                self._exec(cmd_info={"cmd": cmd, "cwd": self.repo_dir})

        test_script = self.project_meta.get("c_compile", {"test": "ctest"}).get("test", "ctest")
        test_name = self.bug.get("unittest", {"name": None}).get("name", None)
        test_script_override = self.bug.get("c_compile", {"test": "ctest"}).get("test", "ctest")
        test_script = test_script if test_script_override is None else test_script_override

        assert test_script.startswith("ctest") or test_script.startswith("bash") or test_script.startswith("gtest"), (
        test_script, test_script_override, self.project_meta, self.bug)

        raw_build_dir = self.build_dir
        with open(opj(self.stdout_dir, f"out_{self.commit_id}_exec_testsuit_raw.log"), "w") as f:
            junt_xml = opj(self.stdout_dir, f"out_{self.commit_id}_exec_testsuit_raw.xml")
            self.stdout_file = f

            logger.info("====== step1 ========")
            logger.info(f"checkout commit {commit_id}")
            checkout_commit()
            get_status()

            logger.info("====== step2 ========")
            logger.info(f"conf/build/ctest for raw commit {commit_id}")
            # exec_testsuit()
            self.pre_build()
            self.run_configure(defined_builder=self.defined_builder)
            self.run_build(defined_builder=self.defined_builder)

            if test_script == "ctest":
                if test_name is not None:
                    test_name = "|".join(test_name)
                    self.run_ctest_one(test_name=test_name, junt_xml=junt_xml)
                else:
                    self.run_ctest_all(junt_xml=junt_xml)
            elif test_script.startswith("bash"):
                self.run_test_script(test_script=test_script, junt_xml=junt_xml)
            else:
                raise Exception("unkn test_script={}".format(test_script))

        self.build_dir = self.build_dir_buggy
        with open(opj(self.stdout_dir, f"out_{self.commit_id}_exec_testsuit_buggy.log"), "w") as f:
            junt_xml = opj(self.stdout_dir, f"out_{self.commit_id}_exec_testsuit_buggy.xml")
            self.stdout_file = f
            logger.info("====== step3 ========")
            logger.info(f"overwrite the file from before commit {commit_before_id}")
            checkout_reproducing_buggy(commit_before_id=commit_before_id, file_list=file_list)

            logger.info("====== step4 ========")
            logger.info(f"conf/build/ctest for buggy commit {commit_id}")

            self.pre_build()
            self.run_configure(defined_builder=self.defined_builder)
            self.run_build(defined_builder=self.defined_builder)
            # self.run_ctest_all(junt_xml=junt_xml)
            if test_script == "ctest":
                if test_name is not None:
                    self.run_ctest_one(test_name=test_name, junt_xml=junt_xml)
                else:
                    self.run_ctest_all(junt_xml=junt_xml)
            elif test_script.startswith("bash"):
                self.run_test_script(test_script=test_script, junt_xml=junt_xml)
            else:
                raise Exception("unkn test_script={}".format(test_script))

        self.build_dir = raw_build_dir

    def fix(self, patch_path_list):
        patch_path_list = patch_path_list if type(patch_path_list) == list else [patch_path_list]

        assert all([os.path.isfile(one_patch_path) for one_patch_path in patch_path_list]), (
        "cannot find the patch file ", patch_path_list)
        assert all([os.path.isdir(self.build_dir), os.path.isdir(self.build_dir_buggy)]), (
        self.build_dir, self.build_dir_buggy)

        # get file list
        commit_after_id = self.bug["commit_after"]
        # assert commit_id == commit_after_id , ("you input ", commit_id, "but we believe it not belong to ", self.bug )

        commit_before_id = self.bug["commit_before"]
        file_list = self.bug["files"]["src"]
        assert len(file_list) > 0, (self.bug, file_list)

        # def check_patch_is_valid(patch_path):
        #     with open(patch_path) as fff :
        #         content = fff.read()
        #     assert "@@" in content , ("this patch file is not valid", patch_path )

        # def apply_patch (patch_file ):
        #     cmd = f"git apply --check {os.path.abspath(patch_path) } "
        #     self._exec(cmd_info={"cmd":cmd, "cwd":self.repo_dir } )
        #
        #     cmd = f"git apply  {os.path.abspath(patch_path) } "
        #     self._exec(cmd_info={"cmd":cmd, "cwd":self.repo_dir } )
        #
        def replace_patch(patch_file, dst_file):
            cmd = f"cp {patch_file}  {dst_file} "
            self._exec(cmd_info={"cmd": cmd, "cwd": self.repo_dir})

        def exec_testsuit(junt_xml):
            # test_script
            # test_name
            # junt_xml
            test_script = self.project_meta.get("c_compile", {"test": "ctest"}).get("test", "ctest")
            test_name = self.bug.get("unittest", {"name": None}).get("name", None)
            test_script_override = self.bug.get("c_compile", {"test": "ctest"}).get("test", "ctest")
            test_script = test_script if test_script_override is None else test_script_override
            assert test_script.startswith("ctest") or test_script.startswith("bash") or test_script.startswith(
                "gtest"), (test_script, test_script_override, self.project_meta, self.bug)

            if test_script == "ctest":
                if test_name is not None:
                    test_name = "|".join(test_name)
                    self.run_ctest_one(test_name=test_name, junt_xml=junt_xml)
                else:
                    self.run_ctest_all(junt_xml=junt_xml)
            elif test_script.startswith("bash"):
                self.run_test_script(test_script=test_script, junt_xml=junt_xml)
            else:
                raise Exception("unkn test_script={}".format(test_script))

        def checkout_reproducing_buggy(commit_before_id, commit_after_id, file_list):
            def checkout_commit():
                cmd = f"git checkout -f {commit_after_id}"
                self._exec(cmd_info={"cmd": cmd, "cwd": self.repo_dir, "check": True})

            git_v = subprocess.run("git rev-parse HEAD", cwd=self.repo_dir, shell=True, text=True,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            is_git_match = git_v.stdout.strip() == commit_after_id
            print(git_v.stdout.strip(), "-->", commit_after_id, "is_git_match", is_git_match)
            if not is_git_match:
                cmd = "git reset HEAD --hard "
                self._exec(cmd_info={"cmd": cmd, "cwd": self.repo_dir})
                # reverse to after
                checkout_commit()

            for one_file in file_list:
                cmd = f"git checkout {commit_before_id} -- {one_file}"
                self._exec(cmd_info={"cmd": cmd, "cwd": self.repo_dir})
            # reverse to eahc before

        suffix = "" if "@@" not in patch_path_list[0] else os.path.basename(patch_path_list[0])
        fix_loger = opj(self.stdout_dir, f"out_{self.commit_id}_exec_testsuit_fix_{suffix}.log")
        if os.path.isfile(fix_loger):
            print("exist...fix log")
            return None
        with open(fix_loger, "a") as f:
            junt_xml = opj(self.stdout_dir, f"out_{self.commit_id}_exec_testsuit_fix_{suffix}.xml")

            self.stdout_file = f
            logger.info(f"====== step1 [fix] ensure all file are in buggy status {patch_path_list}========")
            logger.info(f"overwrite the file from before commit {commit_before_id}")
            checkout_reproducing_buggy(commit_before_id=commit_before_id, commit_after_id=commit_after_id,
                                       file_list=file_list)

            logger.info("====== step2 [fix] check patch  ========")
            logger.info(f"overwrite the file from before commit {commit_before_id}")
            # check_patch_is_valid( patch_path=patch_path )
            # apply_patch( patch_path=patch_path )
            for one_file, one_patch in zip(file_list, patch_path_list):
                replace_patch(patch_file=one_patch, dst_file=one_file)

            self.pre_build()
            # self.run_configure(defined_builder=self.defined_builder )
            self.run_build(defined_builder=self.defined_builder)

            logger.info("====== step3 [fix] ========")
            logger.info(f"conf/build/ctest for buggy commit {self.commit_id}")
            exec_testsuit(junt_xml=junt_xml)

    def download_buggy(self, commit_id=None):
        commit_after_id = self.bug["commit_after"]
        # commit_id = self.commit_id  if commit_id is None else commit_id
        #
        # assert commit_id == commit_after_id , ("you input ", commit_id, "but we believe it not belong to ", self.bug )
        #
        commit_before_id = self.bug["commit_before"]
        file_list = self.bug["files"]["src"]
        assert len(file_list) > 0, (self.bug, file_list)

        download_dir = self.download_dir

        for one_file_p in file_list:
            one_file_p_save = opj(download_dir, one_file_p.replace("/", "@"))
            down_cmd = f"git checkout {commit_before_id} -- {one_file_p}"
            self._exec(cmd_info={"cmd": down_cmd, "cwd": self.repo_dir, "check": True})

            down_cp_cmd = f"cp  {one_file_p} {one_file_p_save} "
            self._exec(cmd_info={"cmd": down_cp_cmd, "cwd": self.repo_dir, "check": True})


from glob import glob
import base64


class Defect4C_Query:
    def __init__(self,
                 root_dir):
        self.root_dir = root_dir

    def _print_f(self, dict_or_list=None, columns=None, print_type=None):
        from prettytable import PrettyTable
        import pprint

        if type(dict_or_list) == list and len(dict_or_list) > 0 and type(dict_or_list[0]) == dict:  # list.dict
            first_row = dict_or_list[0]
            table = PrettyTable(list(first_row.keys()))
            [table.add_row(list(row.values())) for row in dict_or_list]
            print(table)
        elif type(dict_or_list) == dict and print_type == "pprint":
            pprint.pprint(dict_or_list)
        elif type(dict_or_list) == dict:
            columns = ["k", "v"] if columns is None else columns
            table = PrettyTable(columns, align='l', max_width=50, )
            # table = PrettyTable(columns , align='l', max_width=250 )
            [table.add_row([k, v]) for k, v in dict_or_list.items()]
            print(table)

    def list_repo(self, ):
        root_dir = self.root_dir
        ## search
        project_list_p = opj(root_dir, "projects", "*___*", PROJECT_META_P)
        project_list = glob(project_list_p)
        repo_list = [(os.path.basename(os.path.dirname(x)), x) for x in project_list]

        ## format
        final_list = []
        for repo_name, x in repo_list:
            y = x.replace(PROJECT_META_P, BUG_META_P)
            bug_list = json.load(open(y))

            bug_list = [x for x in bug_list if x["status_manual"] >= 1 and x["status"] > 0]
            # bug_list = [x for x in bug_list if x["status_manual"]>=1  ]
            if len(bug_list) > 0:
                # ctest_status =

                bug_list_expected = [x for x in bug_list if
                                     x["status_manual"] >= 1 and x["status"] >= 0 and x["unittest"].get("status",
                                                                                                        None) == "success"]
                bug_list_spicific = [x for x in bug_list if
                                     x["status_manual"] >= 1 and x["status"] >= 0 and x["unittest"].get("status",
                                                                                                        None) == "buggy==raw!=100"]
                bug_list_hell = [x for x in bug_list if x["status_manual"] >= 1 and x["status"] >= 0 and (
                            x["unittest"].get("status", None) == "buggy_compile_error" or x["unittest"].get("status",
                                                                                                            None) == "100%")]

                need_check = len(bug_list) - len(bug_list_expected) - len(bug_list_spicific) - len(bug_list_hell)

                final_list.append({"repo_name": repo_name,
                                   "bugs.count": len(bug_list),
                                   "checked": len(bug_list_expected),
                                   "suspecious": len(bug_list_spicific),
                                   "fail": len(bug_list_hell),
                                   "progressing": need_check,
                                   })
        final_list = sorted(final_list, key=lambda x: x["bugs.count"])

        # try :
        if 1 == 1:
            import pandas as pd
            df = pd.DataFrame(final_list)
            df_c = list(df.columns)
            print("df_c", type(df_c), df_c)
            df_c.remove("repo_name")

            df.loc['Column_Total'] = df.sum(numeric_only=True, axis=0)
            df = df.astype({c: int for c in df_c})
            df["repo_name"][-1] = "total"
            df.loc[pd.isnull(df.repo_name), 'repo_name'] = "Total"

            final_list = df.to_dict(orient="records")
        # except :
        #     pass
        ## replace
        self._print_f(dict_or_list=final_list)

        self._print_f(dict_or_list=self._suggest(), columns=["action", "example"])

    def list_bugs_for_repo(self, repo_name):
        root_dir = self.root_dir
        ## search
        project_list_p = opj(root_dir, "projects", repo_name, PROJECT_META_P)
        assert os.path.isfile(project_list_p), project_list_p

        bugs_list_p = opj(root_dir, "projects", repo_name, BUG_META_P)
        assert os.path.isfile(bugs_list_p), bugs_list_p

        ## format
        with open(bugs_list_p) as f:
            bug_list = json.load(f)

        final_list = [{"bug_id": "{}@{}".format(repo_name, x["commit_after"])} for x in bug_list]
        ## replace
        self._print_f(dict_or_list=final_list)

        self._print_f(dict_or_list=self._suggest(), columns=["action", "example"])

    @staticmethod
    def parse_bug_id(bug_id):
        _bug_id = os.path.basename(bug_id)
        assert "@" in _bug_id, ("[repo_name]@[bug_id_int]", _bug_id)
        repo_name = _bug_id.split("@")[0]
        bug_id_int = _bug_id.split("@")[-1]
        # return {"repo_name":repo_name, "commit_after":bug_id_int }
        return repo_name, bug_id_int.strip()

    def info(self, repo_name, commit_id):
        commit_after = commit_id
        # repo_name , commit_after = self.parse_bug_id(bug_id=bug_id)

        root_dir = self.root_dir
        ## search
        project_list_p = opj(root_dir, "projects", repo_name, PROJECT_META_P)
        assert os.path.isfile(project_list_p), project_list_p

        bugs_list_p = opj(root_dir, "projects", repo_name, BUG_META_P)
        assert os.path.isfile(bugs_list_p), bugs_list_p

        ## format
        with open(bugs_list_p) as f:
            bug_list = json.load(f)

        item = [x for x in bug_list if x["commit_after"] == commit_after]
        assert len(item) == 1, ("this id={} is not belong to {}".format(bug_id, bugs_list_p))
        item = item[-1]

        item["commit_msg"] = base64.b64decode(item["commit_msg"].encode("utf-8")).decode("utf-8")
        item["commit_msg"] = item["commit_msg"].replace("\n", "\\n")
        ## replace
        self._print_f(dict_or_list=item, print_type="pprint")

        self._print_f(dict_or_list=self._suggest(), columns=["action", "example"])

    def _suggest(self, ):
        script_file = os.path.basename(os.path.abspath(__file__))
        sugg_list = {}
        sugg_list["list"] = f"{script_file} list "
        sugg_list["list.bugs"] = f"{script_file} list -r [repo_name] "

        sugg_list["info"] = f"{script_file} info [bug_id]"
        sugg_list["reproduce"] = f"{script_file} reproduce [bug_id]"
        sugg_list["  -compile"] = f"    {script_file} compile [bug_id]"
        # sugg_list["  -build"] = f"    {script_file} build [bug_id]"
        sugg_list["  -unittest"] = f"    {script_file} test [bug_id]"

        sugg_list["fix"] = f"{script_file} fix [bug_id] /tmp/xx.patch "
        sugg_list["  -compile "] = f"    {script_file} compile [bug_id] /tmp/xx.patch "
        # sugg_list["  -build "] = f"    {script_file} build [bug_id] /tmp/xx.patch "
        sugg_list["  -unittest "] = f"    {script_file} test [bug_id] /tmp/xx.patch "

        return sugg_list


def init_parse(subparsers, is_in_single_repo=False):
    # Command: reproduce
    reproduce_parser = subparsers.add_parser("reproduce", help="Reproduce a defect")
    reproduce_parser.add_argument("bug_id", help="ID of the bug")
    reproduce_parser.add_argument("--delete", help="if build_dir exist, delete ", action='store_true')
    reproduce_parser.add_argument("--delete-repo", help="if repo exist, delete ", action='store_true')
    reproduce_parser.add_argument('--seperate_repo', action='store_true')

    # Command: reproduce
    info_parser = subparsers.add_parser("info", help="Get information about a defect")
    info_parser.add_argument("bug_id", help="ID of the bug")

    # if not is_in_single_repo:
    #     # Command: list_org
    list_buggy_parser = subparsers.add_parser("list", help="List defects in an organization")
    list_buggy_parser.add_argument("--repo_name", "-r", dest="repo_name", default=None, help="Name of the repository")

    # # Command: download
    dl_parser = subparsers.add_parser("download", help="Get information about a defect")
    dl_parser.add_argument("bug_id", help="ID of the bug")

    # Command: fix
    fix_parser = subparsers.add_parser("fix", help="Fix a defect")
    fix_parser.add_argument("bug_id", help="ID of the bug")
    fix_parser.add_argument("patch_path", help="ID of the bug", nargs='+')

    fix_parser.add_argument("--delete", help="if build_dir exist, delete ", action='store_true')
    fix_parser.add_argument("--delete-repo", help="if repo exist, delete ", action='store_true')
    fix_parser.add_argument('--seperate_repo', action='store_true')

    # # Command: fix_with_gt
    # fix_with_gt_parser = subparsers.add_parser("fix_with_gt", help="Fix a defect with greater details")
    # fix_with_gt_parser.add_argument("bug_id", help="ID of the bug")

    return subparsers


CUR_DIR = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.environ.get("OUR_DIR", "/out")  # "/out" if os.path.isdir("/out") else CUR_DIR

# print (OUT_DIR, "OUT_DIR")
PROJECT_META_P = "project.json"
BUG_META_P = "bugs_list.json"
# GITHUB_SRC="git_repo_dir"
GITHUB_SRC = os.environ.get("repo", "git_repo_dir")
TIMEOUT = os.environ.get("timeout_test", None)
TIMEOUT = int(TIMEOUT) if TIMEOUT is not None else TIMEOUT

DOWNLOAD_SRC = "download"

NPROC = os.cpu_count() + 1

if __name__ == "__main__":

    import argparse

    parser = argparse.ArgumentParser(description="Runs the script")
    parser.add_argument("--root_dir", default=CUR_DIR, type=str, help="ID of the bug")
    parser.add_argument("--out_dir", default=OUT_DIR, type=str, help="ID of the bug")
    parser.add_argument('-v', '--verbose', action='store_true')

    subparsers = parser.add_subparsers(title="Commands", dest="command")
    subparsers = init_parse(subparsers=subparsers)

    args = parser.parse_args()

    ## declare the global variables
    if hasattr(args, "bug_id"):
        repo_name, bug_id_int = Defect4C_Query.parse_bug_id(bug_id=args.bug_id)
        setattr(args, "repo_name", repo_name)
        setattr(args, "commit_id", bug_id_int)
        out_dir = opj(args.out_dir, repo_name)
        setattr(args, "out_dir", out_dir)
        workspace = opj(args.root_dir, "projects", repo_name)
        setattr(args, "workspace", workspace)

    if hasattr(args, "seperate_repo") and args.seperate_repo:
        GITHUB_SRC = f"{GITHUB_SRC}_{args.commit_id}"

    ## prepare logger
    os.makedirs(opj(args.out_dir, "logs"), exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler(opj(args.out_dir, "logs", "sys.log")),
        ]
    )
    logger = logging.getLogger(__file__)

    # print (args.command , "comd", vars(args))

    dfc_obj = None
    if args.command in ["download", "reproduce", "fix", "fix_with_gt", ]:
        dfc_obj = Defect4C_BUG(
            root_dir=args.root_dir,
            out_root_dir=args.out_dir,
            repo_name=args.repo_name,
            workspace=args.workspace,
            commit_id=args.commit_id,
            delete_repo=args.delete_repo if hasattr(args, "delete_repo") else False,
        )
    else:
        dfc_obj = Defect4C_Query(
            root_dir=args.root_dir)

    if args.command == "download":
        dfc_obj.download_buggy(commit_id=args.commit_id)
    if args.command == "reproduce":
        dfc_obj.reproduce(delete=args.delete)  # commit_id=args.commit_id )
    elif args.command == "list":
        if args.repo_name is None:
            dfc_obj.list_repo()
        else:
            dfc_obj.list_bugs_for_repo(repo_name=args.repo_name)
    elif args.command == "info":
        dfc_obj.info(repo_name=args.repo_name, commit_id=args.commit_id)
    elif args.command == "fix":
        dfc_obj.fix(
            patch_path_list=args.patch_path)  # repo_name=args.repo_name , commit_id =args.commit_id , patch_path =args.patch_path   )