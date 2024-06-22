import sys 
import jmespath 
import os 
import json 
from jinja2 import Environment, FileSystemLoader

import pprint 


# ROOT_DIR = "/data3/code_dst2/repo_dirs/" 
ROOT_DIR = "/out/" 
SRC_DIR = os.path.dirname( os.path.abspath(__file__) )
# print ("SRC_DIR" , SRC_DIR )


COMMON_META_INFO = dict(
#  SystemInfo:
# WorkInfo :
    repo_dir  =None, 
    log_dir   =None, 
    build_dir    =None, 
    test_log    =None, 

# MetaInfo :
    commit_after  =None, 
    commit_before  =None, 
    src_files   =None, 
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
    return  tpl_lib#.format( tool_name )
    
class BugsInfo :
    meta_info = {
        "apt_install_fn":apt_install_tool(),
        "cpu_count" : os.cpu_count()-1, 
        }
    
    def __init__(self,project ,  sha ):
        self.sha= sha 
        self.project = project 

        
        self.wrk_git =  os.path.join(ROOT_DIR ,project  , f"git_repo_dir_{self.sha}" )
        if not os.path.isdir(self.wrk_git):
            self.wrk_git =  os.path.join(ROOT_DIR ,project  , f"git_repo_dir" )
            
        self.wrk_log =  os.path.join(ROOT_DIR ,project  , "logs" )
        self.wrk_log_fn =  os.path.join(ROOT_DIR ,project  , "logs", f"{self.sha}.log" )
        os.makedirs(self.wrk_git,exist_ok=True )
        os.makedirs(self.wrk_log,exist_ok=True )
        
        self.src_project= os.path.join(SRC_DIR, "projects", project)
        ###
        # defect meta 
        ###
        with open( os.path.join(self.src_project ,  "bugs_list_new.json" )  ) as f :
            meta_bugs = json.load( f  )

        with open( os.path.join(self.src_project ,  "project.json" )  ) as f :
            self.meta_project = json.load( f  )
            
        self.meta_defect = jmespath.search ("[?commit_after=='"+self.sha+"']", meta_bugs  ) 
        assert len(self.meta_defect)  ==1 , self.meta_defect 
        self.meta_defect = self.meta_defect[0]
        
        self.meta_info.update({ k:v for k,v in self.meta_defect.items() if k in COMMON_META_INFO})
        self.meta_info .update({
            "repo_dir":self.wrk_git,
            "log_dir":self.wrk_log,
            })

        ###
        # compile 
        ###
        system_compile = jmespath.search ("c_compile", self.meta_project ) 
        defect_compile = jmespath.search ("c_compile", self.meta_defect ) 

        b_f_1 = jmespath.search ("c_compile.build_flags", self.meta_project ) 
        b_f_2 = jmespath.search ("c_compile.build_flags", self.meta_defect ) 
        b_flags =( b_f_1 if b_f_1 is not None else [] ) +(b_f_2 if b_f_2 is not None else []  )
        
        t_f_1 = jmespath.search ("c_compile.test_flags", self.meta_project ) 
        t_f_2 = jmespath.search ("c_compile.test_flags", self.meta_defect ) 
        t_flags =( t_f_1 if t_f_1 is not None else [] ) +( t_f_2 if t_f_2 is not None else []  )

        e_f_1 = jmespath.search ("env", self.meta_project ) 
        e_f_2 = jmespath.search ("c_compile.env", self.meta_defect ) 
        e_flags =( e_f_1 if e_f_1 is not None else [] ) +( e_f_2 if e_f_2 is not None else []  )

        defect_compile = {x:y for x,y in defect_compile.items() if y is not None and len(y)>0 }
        compile_in_one = {**self.meta_project, **system_compile, **defect_compile,"build_flags":b_flags,"test_flags":t_flags , "env":e_flags }
        # compile_in_one["c_compile"]["build_flags"]= b_flags
        # compile_in_one["c_compile"]["test_flags"]= t_flags

        self.meta_info.update(compile_in_one)
        
        ###
        # path 
        ###
        self.meta_info.update( {
            "build_dir" : f"build_{sha}",
            "test_log" : os.path.join(self.wrk_log, f"test_{sha}_fix.log"),
            "test_files" : jmespath.search( "files.test", self.meta_defect ),
            "src_file" : jmespath.search( "files.src[0]", self.meta_defect ),
        } )
        
        pprint.pprint ( self.meta_info)# "===>self.meta_info" )
        
    
    def set_reproduce_build(self  ):
        
        def  build_tpl( tpl_path  ,  dict_info, save_path= None,    ):
            loader_dir=  self.src_project 
            if tpl_path.startswith("/"):
                loader_dir = os.path.dirname(tpl_path)
            # print ("loader_dir", loader_dir, tpl_path, tpl_path.startswith("/"))
            # Load the Jinja environment
            env = Environment( loader=FileSystemLoader( loader_dir ) )
            
            # Load the template
            template = env.get_template(os.path.basename( tpl_path  ) )
            
            # Render the template with the provided variables
            output_text = template.render( ** dict_info )
            
            # Write the rendered output to a file
            with open( save_path , "w") as f:
                f.write(output_text)


        build_tpl(
            tpl_path =self.meta_info["build"]  if ".jinja"  in str(self.meta_info["build"]) else os.path.abspath( opj(self.src_project_dir ,"common_build_tpl.jinja") ),
            dict_info = self.meta_info , 
            save_path=   os.path.join(self.wrk_git , "inplace_build.sh"),
            )
        build_tpl(
            tpl_path =self.meta_info["build"]  if ".jinja"  in str(self.meta_info["build"]) else os.path.abspath( opj(self.src_project_dir ,"common_build_tpl.jinja") ),
            dict_info ={
                "is_rebuild":True, 
                "test_log" : os.path.join(self.wrk_log, f"test_{self.sha}_fix.log"),
                ** self.meta_info}  , 
            save_path=   os.path.join(self.wrk_git , "inplace_rebuild.sh"),
            )
        build_tpl(
            tpl_path =self.meta_info["test"]  if ".jinja"  in str(self.meta_info["test"]) else os.path.abspath( opj(self.src_project_dir ,"common_test_tpl.jinja") ),
            dict_info = self.meta_info , 
            save_path=   os.path.join(self.wrk_git , "inplace_test.sh"),
            )
        
        build_tpl(
            tpl_path = os.path.join(SRC_DIR, "projects" , "workflow_tpl.jinja"),
            dict_info = self.meta_info , 
            save_path=   os.path.join(self.wrk_git , "run_reproduce.sh"),
            )
        
    def set_patch_build(self  ):
        
        def  build_tpl( tpl_path  ,  dict_info, save_path= None,    ):
            loader_dir=  self.src_project 
            if tpl_path.startswith("/"):
                loader_dir = os.path.dirname(tpl_path)
            # print ("loader_dir", loader_dir, tpl_path, tpl_path.startswith("/"))
            # Load the Jinja environment
            env = Environment( loader=FileSystemLoader( loader_dir ) )
            
            # Load the template
            template = env.get_template(os.path.basename( tpl_path  ) )
            
            # Render the template with the provided variables
            output_text = template.render( ** dict_info )
            
            # Write the rendered output to a file
            with open( save_path , "w") as f:
                f.write(output_text)

        build_tpl(
            tpl_path =self.meta_info["build"]  if ".jinja"  in str(self.meta_info["build"]) else os.path.abspath( opj(self.src_project_dir ,"common_build_tpl.jinja") ),
            dict_info ={
                "is_rebuild":True, 
                "test_log" : os.path.join(self.wrk_log, f"test_{self.sha}_fix.log"),
                ** self.meta_info}  , 
            save_path=   os.path.join(self.wrk_git , "inplace_rebuild.sh"),
            )
        build_tpl(
            tpl_path =self.meta_info["test"]  if ".jinja"  in str(self.meta_info["test"]) else os.path.abspath( opj(self.src_project_dir ,"common_test_tpl.jinja") ),
            dict_info = self.meta_info , 
            save_path=   os.path.join(self.wrk_git , "inplace_test.sh"),
            )


        build_tpl(
            tpl_path = os.path.join(SRC_DIR, "projects" , "workflow_cmake_rebuild_tpl.jinja"),
            dict_info ={
                ** self.meta_info,
                "test_log" : os.path.join(self.wrk_log, f"patch_{self.sha}_fix.log"),
                }  , 
            save_path=   os.path.join(self.wrk_git , "run_patch.sh"),
            )



import shlex 
import subprocess 

def exec_cmd(cmd_info):
    
    one_cmd = cmd_info.pop("cmd")
    one_cmd = shlex.split( one_cmd )

    proc = subprocess.run(one_cmd,
                                # stdout= test_log, 
                                # stderr= test_log , 
                               **cmd_info,
                               # env=self._env , 
                               )
    

if __name__=="__main__":
    import argparse 
    project_list = os.listdir(os.path.join(SRC_DIR, "./projects") )
    project_list = [os.path.basename(x) for x in project_list if "___" in x ]
    
    parser = argparse.ArgumentParser(
                    prog='ProgramName',
                    description='What the program does',
                    epilog='Text at the bottom of help')
    
    subparsers = parser.add_subparsers(title="Commands", dest="command")

    reproduce_parser = subparsers.add_parser("reproduce", help="Reproduce a defect")
    reproduce_parser.add_argument("bug_id", help="ID of the bug")

    # Command: fix
    fix_parser = subparsers.add_parser("fix", help="Fix a defect")
    fix_parser.add_argument("bug_id", help="ID of the bug")
    # fix_parser.add_argument("patch_path", help="ID of the bug", nargs='+' )
    fix_parser.add_argument("patch_path", help="ID of the bug",  )

    args = parser.parse_args()
    
    bug_idx = args. bug_id
    _project = bug_idx.split("@")[0]
    _sha = bug_idx.split("@")[-1]
    
    # parser.add_argument('project')           # positional argument
    # parser.add_argument('bugid')           # positional argument
    
    
    assert _project in project_list , (_project, project_list )
    
    instance = BugsInfo( project = _project , sha=_sha  )




    if args.command == "reproduce":
        with open(instance.wrk_log_fn, "w") as log_f : 


            exec_cmd( cmd_info={
            "cmd":"git clean -dfx",
            "cwd":instance.wrk_git,
            "stdout":log_f,
            "stderr":log_f,
            })

            instance.set_reproduce_build( )
        
            try:
                exec_cmd( cmd_info={
                    "cmd":"bash run_reproduce.sh",
                    "cwd":instance.wrk_git,
                    "stdout":log_f,
                    "stderr":log_f,
                    "timeout":60*30,
                    })
            except subprocess.TimeoutExpired as exp :
                print ("timeout", exp )
                
                
    elif args.command == "fix":
        assert os.path.isfile( args.patch_path), args.patch_path 
        
        with open(instance.wrk_log_fn, "a") as log_f : 
            instance.set_patch_build( )
        
            try:
                exec_cmd( cmd_info={
                    "cmd":f"bash run_patch.sh {args.patch_path}",
                    "cwd":instance.wrk_git,
                    "stdout":log_f,
                    "stderr":log_f,
                    "timeout":60*30,
                    })
            except subprocess.TimeoutExpired as exp :
                print ("timeout", exp )



