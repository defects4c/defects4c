import sys 
import jmespath 
import os 
from os.path import join as opj 
import json 
from jinja2 import Environment, FileSystemLoader

import pprint 


ROOT_DIR = "/out/" 
SRC_DIR = os.path.dirname( os.path.abspath(__file__) )

PROJECTS_DIRS = {
    "v0": os.path.join(SRC_DIR, "projects"),
    "v1": os.path.join(SRC_DIR, "projects_v1"),
}

COMMON_META_INFO = dict(
    repo_dir     = None, 
    log_dir      = None, 
    build_dir    = None, 
    test_log     = None, 
    commit_after  = None, 
    commit_before = None, 
    src_files    = None, 
)

def apt_install_tool():
    tpl_lib= """
apt_install_fn() {
    library=$1
    if dpkg -s "$library" &> /dev/null; then
        echo "$library is already installed"
    elif which "$library" >/dev/null 2>&1; then
        echo "$library is already installed"
    else
        echo "$library is not installed, attempting to install..."
        # Install the library using apt-get
        sudo apt-get update -y 
        sudo apt-get install -y "$library"
    fi
}
    """
    return tpl_lib

def detect_version(project):
    """Detect which projects directory contains the given project."""
    for version, base_dir in PROJECTS_DIRS.items():
        candidate = os.path.join(base_dir, project)
        if os.path.isdir(candidate):
            return version, base_dir
    raise ValueError(f"Project '{project}' not found in any known projects directory: {list(PROJECTS_DIRS.values())}")


class BugsInfo:
    meta_info = {
        "apt_install_fn": apt_install_tool(),
        "cpu_count": os.cpu_count() - 1, 
    }
    
    def __init__(self, project, sha):
        self.sha = sha 
        self.project = project 

        # Detect which projects directory this project lives in
        self.version, self.src_project_dir = detect_version(project)
        self.src_project = os.path.join(self.src_project_dir, project)

        # --- wrk_git setup ---
        # v1: directory must already exist (assert)
        # v0: fall back to generic git_repo_dir if sha-specific one is missing
        self.wrk_git = os.path.join(ROOT_DIR, project, f"git_repo_dir_{self.sha}")
        if self.version == "v0":
            if not os.path.isdir(self.wrk_git):
                self.wrk_git = os.path.join(ROOT_DIR, project, "git_repo_dir")
        else:  # v1
            assert os.path.isdir(self.wrk_git), self.wrk_git

        self.wrk_log    = os.path.join(ROOT_DIR, project, "logs")
        self.wrk_log_fn = os.path.join(ROOT_DIR, project, "logs", f"{self.sha}.log")
        os.makedirs(self.wrk_git, exist_ok=True)
        os.makedirs(self.wrk_log, exist_ok=True)

        ###
        # defect meta 
        ###
        with open(os.path.join(self.src_project, "bugs_list_new.json")) as f:
            meta_bugs = json.load(f)

        with open(os.path.join(self.src_project, "project.json")) as f:
            self.meta_project = json.load(f)

        self.meta_defect = jmespath.search("[?commit_after=='" + self.sha + "']", meta_bugs)
        assert len(self.meta_defect) == 1, self.meta_defect
        self.meta_defect = self.meta_defect[0]

        self.meta_info.update({k: v for k, v in self.meta_defect.items() if k in COMMON_META_INFO})
        self.meta_info.update({
            "repo_dir": self.wrk_git,
            "log_dir":  self.wrk_log,
        })

        ###
        # compile 
        ###
        system_compile = jmespath.search("c_compile", self.meta_project)
        defect_compile = jmespath.search("c_compile", self.meta_defect)

        b_f_1   = jmespath.search("c_compile.build_flags", self.meta_project)
        b_f_2   = jmespath.search("c_compile.build_flags", self.meta_defect)
        b_flags = (b_f_1 if b_f_1 is not None else []) + (b_f_2 if b_f_2 is not None else [])

        t_f_1   = jmespath.search("c_compile.test_flags", self.meta_project)
        t_f_2   = jmespath.search("c_compile.test_flags", self.meta_defect)
        t_flags = (t_f_1 if t_f_1 is not None else []) + (t_f_2 if t_f_2 is not None else [])

        compile_kwargs = {"build_flags": b_flags, "test_flags": t_flags}

        # v0 additionally merges env flags
        if self.version == "v0":
            e_f_1 = jmespath.search("env", self.meta_project)
            e_f_2 = jmespath.search("c_compile.env", self.meta_defect)
            e_flags = (e_f_1 if e_f_1 is not None else []) + (e_f_2 if e_f_2 is not None else [])
            compile_kwargs["env"] = e_flags

        defect_compile = {x: y for x, y in defect_compile.items() if y is not None and len(y) > 0}
        compile_in_one = {**self.meta_project, **system_compile, **defect_compile, **compile_kwargs}

        self.meta_info.update(compile_in_one)

        ###
        # path 
        ###
        self.meta_info.update({
            "build_dir":  f"build_{sha}",
            "test_log":   os.path.join(self.wrk_log, f"test_{sha}_fix.log"),
            "test_files": jmespath.search("files.test", self.meta_defect),
            "src_file":   jmespath.search("files.src[0]", self.meta_defect),
        })

        pprint.pprint(self.meta_info)

    # ------------------------------------------------------------------
    # Internal helper: render a Jinja template and write to save_path
    # ------------------------------------------------------------------
    def _build_tpl(self, tpl_path, dict_info, save_path):
        loader_dir = self.src_project
        if tpl_path.startswith("/"):
            loader_dir = os.path.dirname(tpl_path)
        env      = Environment(loader=FileSystemLoader(loader_dir))
        template = env.get_template(os.path.basename(tpl_path))
        output_text = template.render(**dict_info)
        with open(save_path, "w") as f:
            f.write(output_text)

    # ------------------------------------------------------------------
    # Resolve build / test template paths
    # ------------------------------------------------------------------
    def _build_tpl_path(self):
        val = self.meta_info.get("build", "")
        return val if ".jinja" in str(val) else os.path.abspath(opj(self.src_project_dir, "common_build_tpl.jinja"))

    def _test_tpl_path(self):
        val = self.meta_info.get("test", "")
        return val if ".jinja" in str(val) else os.path.abspath(opj(self.src_project_dir, "common_test_tpl.jinja"))

    # ------------------------------------------------------------------
    # Workflow template varies by version
    # ------------------------------------------------------------------
    def _workflow_reproduce_tpl(self):
        if self.version == "v0":
            return os.path.join(SRC_DIR, "projects", "workflow_tpl.jinja")
        else:
            return os.path.join(SRC_DIR, "projects_v1", "workflow_cmake_tpl.jinja")

    def _workflow_patch_tpl(self):
        if self.version == "v0":
            return os.path.join(SRC_DIR, "projects", "workflow_cmake_rebuild_tpl.jinja")
        else:
            return os.path.join(SRC_DIR, "projects_v1", "workflow_cmake_rebuild_tpl.jinja")

    # ------------------------------------------------------------------

    def set_reproduce_build(self):
        rebuild_info = {
            "is_rebuild": True,
            "test_log": os.path.join(self.wrk_log, f"test_{self.sha}_fix.log"),
            **self.meta_info,
        }

        self._build_tpl(
            tpl_path  = self._build_tpl_path(),
            dict_info = self.meta_info,
            save_path = os.path.join(self.wrk_git, "inplace_build.sh"),
        )
        self._build_tpl(
            tpl_path  = self._build_tpl_path(),
            dict_info = rebuild_info,
            save_path = os.path.join(self.wrk_git, "inplace_rebuild.sh"),
        )
        self._build_tpl(
            tpl_path  = self._test_tpl_path(),
            dict_info = self.meta_info,
            save_path = os.path.join(self.wrk_git, "inplace_test.sh"),
        )
        self._build_tpl(
            tpl_path  = self._workflow_reproduce_tpl(),
            dict_info = self.meta_info,
            save_path = os.path.join(self.wrk_git, "run_reproduce.sh"),
        )

    def set_patch_build(self):
        rebuild_info = {
            "is_rebuild": True,
            "test_log": os.path.join(self.wrk_log, f"test_{self.sha}_fix.log"),
            **self.meta_info,
        }
        patch_info = {
            **self.meta_info,
            "test_log": os.path.join(self.wrk_log, f"patch_{self.sha}_fix.log"),
        }

        self._build_tpl(
            tpl_path  = self._build_tpl_path(),
            dict_info = rebuild_info,
            save_path = os.path.join(self.wrk_git, "inplace_rebuild.sh"),
        )
        self._build_tpl(
            tpl_path  = self._test_tpl_path(),
            dict_info = self.meta_info,
            save_path = os.path.join(self.wrk_git, "inplace_test.sh"),
        )
        self._build_tpl(
            tpl_path  = self._workflow_patch_tpl(),
            dict_info = patch_info,
            save_path = os.path.join(self.wrk_git, "run_patch.sh"),
        )


import shlex
import subprocess

def exec_cmd(cmd_info):
    one_cmd = cmd_info.pop("cmd")
    one_cmd = shlex.split(one_cmd)
    proc = subprocess.run(one_cmd, **cmd_info)


if __name__ == "__main__":
    import argparse

    # Collect projects from both directories
    def _collect_projects(base_dir):
        if not os.path.isdir(base_dir):
            return []
        return [os.path.basename(x) for x in os.listdir(base_dir) if "___" in x]

    project_list = (
        _collect_projects(PROJECTS_DIRS["v0"]) +
        _collect_projects(PROJECTS_DIRS["v1"])
    )

    parser = argparse.ArgumentParser(
        prog='bug_helper',
        description='Reproduce or fix a C defect',
        epilog='bug_id format: <project>@<sha>')

    subparsers = parser.add_subparsers(title="Commands", dest="command")

    reproduce_parser = subparsers.add_parser("reproduce", help="Reproduce a defect")
    reproduce_parser.add_argument("bug_id", help="ID of the bug  (project@sha)")

    fix_parser = subparsers.add_parser("fix", help="Fix a defect")
    fix_parser.add_argument("bug_id",     help="ID of the bug  (project@sha)")
    fix_parser.add_argument("patch_path", help="Path to the patch file")

    args = parser.parse_args()

    bug_idx  = args.bug_id
    _project = bug_idx.split("@")[0]
    _sha     = bug_idx.split("@")[-1]

    assert _project in project_list, (_project, project_list)

    instance = BugsInfo(project=_project, sha=_sha)

    if args.command == "reproduce":
        with open(instance.wrk_log_fn, "w") as log_f:

            # v0 projects need a clean working tree before reproducing
            if instance.version == "v0":
                exec_cmd(cmd_info={
                    "cmd":    "git clean -dfx",
                    "cwd":    instance.wrk_git,
                    "stdout": log_f,
                    "stderr": log_f,
                })

            instance.set_reproduce_build()

            try:
                exec_cmd(cmd_info={
                    "cmd":     "bash run_reproduce.sh",
                    "cwd":     instance.wrk_git,
                    "stdout":  log_f,
                    "stderr":  log_f,
                    "timeout": 60 * 30,
                })
            except subprocess.TimeoutExpired as exp:
                print("timeout", exp)

    elif args.command == "fix":
        assert os.path.isfile(args.patch_path), args.patch_path

        with open(instance.wrk_log_fn, "a") as log_f:
            instance.set_patch_build()

            try:
                exec_cmd(cmd_info={
                    "cmd":     f"bash run_patch.sh {args.patch_path}",
                    "cwd":     instance.wrk_git,
                    "stdout":  log_f,
                    "stderr":  log_f,
                    "timeout": 60 * 30,
                })
            except subprocess.TimeoutExpired as exp:
                print("timeout", exp)

