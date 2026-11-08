"""Run the same application regressions in the application environment."""
import bootstrap as b
import runpy

runpy.run_path(str(b.ROOT/'scripts/gpu_experiment/checks.py'),run_name='__main__')
