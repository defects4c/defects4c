# The scripts for reproducing and fixing the Defects4C_vul

- Most script are same as Defects4C_bug, the only change is bug_helper_v1_out2.py to bug_helper2.py, and project_v1 to projects.
  for example,

```
## meta file save in projects for Defects4C_vul rather than project_v1
find . -name "run_patch.sh" -exec sed -i 's/project_v1/projects/g' {} \;
find . -name "run_reproduce.sh" -exec sed -i 's/project_v1/projects/g' {} \;

## entry_point is bug_helper2.py
find . -name "run_patch.sh" -exec sed -i 's/bug_helper_v1_out2/bug_helper2/g' {} \;
find . -name "run_reproduce.sh" -exec sed -i 's/bug_helper_v1_out2/bug_helper2/g' {} \;
```
