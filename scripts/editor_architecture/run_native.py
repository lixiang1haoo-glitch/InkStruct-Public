"""Sequential interleaved native runs; all stdout/stderr and failed runs retained."""
import common as b
import subprocess
import sys

modes=sys.argv[2].split(',') if len(sys.argv)>2 else ['thread','process','compact','admission','visible4']
start=int(sys.argv[1]) if len(sys.argv)>1 else 1
for repeat in range(start,start+3):
    offset=(repeat-start)%len(modes)
    order=modes[offset:]+modes[:offset]
    for mode in order:
        log=b.OUT/f'native-{mode}-{repeat}.log'
        if log.exists() or (b.OUT/f'native-{mode}-{repeat}.json').exists():raise SystemExit('Existing formal run')
        with log.open('xb') as file:
            result=subprocess.run([sys.executable,'-B',str(b.ROOT/'scripts/editor_architecture/native.py'),mode,str(repeat)],
                                  cwd=b.ROOT,stdout=file,stderr=subprocess.STDOUT)
        print(mode,repeat,'exit',result.returncode,flush=True)
        if result.returncode:raise SystemExit('See preserved failed run before continuing')
