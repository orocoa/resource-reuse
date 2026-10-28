#!/usr/bin/env python3
"""Read-only fclones adapter. No remove, link, dedupe, move or apply commands."""
import argparse,collections,json,os,shutil,stat,subprocess,sys,time
from pathlib import Path
sys.dont_write_bytecode=True
from reuse import DATALESS,signature,no_link_ancestors
import project_scope as scope

SKIP_DIRS={'.git','node_modules','.pnpm','.venv','venv','__pycache__','vendor','Library','.ssh','.aws','.gnupg','.config','.codex','.agents'}
SKIP_NAMES={'auth.json','credentials','credentials.json','config.json'}
SKIP_SUFFIXES={'.db','.sqlite','.sqlite3','.pem','.key','.p12'}

def blocked_dir(p):
 return p.name in SKIP_DIRS or p.name.endswith(('.app','.photoslibrary','.musiclibrary','.sparsebundle')) or (p/'resource-pool.json').exists() or (p/'.resource-view.json').exists() or (p/'.resource-reuse-retired.json').exists()

def eligible_files(roots,min_bytes=1):
 paths={};skips=collections.Counter();issues=[]
 def issue(p,e):
  skips['unreadable']+=1
  if len(issues)<100:issues.append({'path':str(p),'error':str(e)})
 for value in roots:
  root=Path(value).expanduser().absolute();scope.require_path(root);no_link_ancestors(root);st=root.lstat()
  if getattr(st,'st_flags',0)&DATALESS:raise ValueError('Cloud root not downloaded; not scanned')
  if not stat.S_ISDIR(st.st_mode) or blocked_dir(root):raise ValueError('Choose an ordinary workspace/material directory')
  device=st.st_dev
  for current,dirs,files in os.walk(root,followlinks=False,onerror=lambda e:issue(e.filename,e)):
   keep=[]
   for name in dirs:
    p=Path(current)/name
    try:
     s=p.lstat()
     try:scope.require_path(p)
     except ValueError:skips['different-project-directory']+=1;continue
     if p.is_symlink():skips['symlink-directory']+=1
     elif getattr(s,'st_flags',0)&DATALESS:skips['cloud-directory']+=1
     elif s.st_dev!=device:skips['other-filesystem']+=1
     elif blocked_dir(p):skips['managed-or-secret-directory']+=1
     else:keep.append(name)
    except OSError as e:issue(p,e)
   dirs[:]=keep
   for name in files:
    p=Path(current)/name
    try:
     s=p.lstat()
     try:scope.require_path(p)
     except ValueError:skips['different-project-file']+=1;continue
     if not stat.S_ISREG(s.st_mode):skips['symlink-or-special-file']+=1;continue
     if getattr(s,'st_flags',0)&DATALESS or name.endswith('.icloud'):skips['cloud-file']+=1;continue
     if s.st_dev!=device:skips['other-filesystem']+=1;continue
     if name.startswith('.env') or name.lower() in SKIP_NAMES or p.suffix.lower() in SKIP_SUFFIXES:skips['database-or-secret-file']+=1;continue
     if s.st_size<min_bytes:skips['below-minimum']+=1;continue
     # fclones 0.35 --stdin is line-delimited. Do not misparse unusual names.
     raw=str(p)
     if '\n' in raw or '\r' in raw:skips['newline-in-path-not-supported']+=1;continue
     try:raw.encode('utf-8')
     except UnicodeEncodeError:skips['non-utf8-path-not-supported']+=1;continue
     paths[raw]={'signature':signature(s),'size':s.st_size,'dev':s.st_dev,'ino':s.st_ino}
    except OSError as e:issue(p,e)
 return paths,dict(skips),issues

def scan(roots,fclones=None,min_bytes=1,selected_paths=None):
 backend=fclones or shutil.which('fclones')
 if not backend:raise FileNotFoundError('Install fclones separately or supply --fclones; no replacement scanner or automatic installation is used')
 files,skips,issues=eligible_files(roots,min_bytes)
 if selected_paths is not None:
  chosen={str(Path(p).absolute()) for p in selected_paths}
  if not chosen.issubset(files):raise ValueError('Selected file is not eligible in these scan roots')
  files={p:info for p,info in files.items() if p in chosen}
 version=subprocess.check_output([str(backend),'--version'],text=True,timeout=15).strip()
 groups=[];warnings=''
 if files:
  cmd=[str(backend),'group','--stdin','--depth','0','--hash-fn','sha256','--threads','2','--format','json']
  p=subprocess.run(cmd,input='\n'.join(files)+'\n',capture_output=True,text=True,timeout=1800)
  if p.returncode:raise RuntimeError('fclones group failed; original files retained: '+p.stderr[-2000:])
  data=json.loads(p.stdout);warnings=p.stderr[-4000:]
  for g in data.get('groups',[]):
   matched=[];inodes=set()
   for value in g.get('files',[]):
    value=str(Path(value).absolute())
    if value not in files:raise ValueError('Backend reported an unselected path')
    try:
     s=Path(value).lstat()
     if signature(s)!=tuple(files[value]['signature']):continue
     if s.st_size!=g['file_len'] or not stat.S_ISREG(s.st_mode):continue
    except OSError:continue
    matched.append(value);inodes.add((s.st_dev,s.st_ino))
   if len(inodes)>1:groups.append({'fclones_sha256':g['file_hash'],'bytes_per_file':g['file_len'],'paths':matched,'independent_inodes':len(inodes),'logical_duplicate_upper_bytes':g['file_len']*(len(inodes)-1)})
 changed=[]
 for path,old in files.items():
  try:unchanged=signature(Path(path).lstat())==tuple(old['signature'])
  except OSError:unchanged=False
  if not unchanged:changed.append(path)
 return {'schema':'resource-reuse-scan-v1','mode':'read-only','backend':version,'eligible_files':len(files),'skips':skips,'issues':issues,'changed_during_scan':changed,'groups':groups,'duplicate_groups':len(groups),'logical_duplicate_upper_bytes':sum(g['logical_duplicate_upper_bytes'] for g in groups),'files_modified_by_adapter':0,'limits':['Logical duplicate bytes are not reclaimable physical bytes; APFS clones may already share all data.','No automatic registration, replacement or deletion. Recheck selected originals before adding them to a pool.','Cloud placeholders, protected/managed data, special files and unsupported path encodings are excluded.']}

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--project-root');p.add_argument('--config');p.add_argument('--root',action='append',required=True);p.add_argument('--fclones');p.add_argument('--min-bytes',type=int,default=1);p.add_argument('--out',required=True)
 a=p.parse_args()
 scope.configure(a.project_root,a.config)
 try:
  out=Path(a.out).expanduser().absolute();scope.require_path(out,write=True);no_link_ancestors(out)
  skill=Path(__file__).resolve().parents[1]
  if out==skill or skill in out.parents:raise ValueError('Reports belong outside the shareable skill')
  for value in a.root:
   root=Path(value).expanduser().absolute()
   if root==out or root in out.parents:raise ValueError('Report must be outside the scanned roots')
  if out.exists():raise FileExistsError('Existing report retained; choose a new path')
  r=scan(a.root,a.fclones,a.min_bytes);out.parent.mkdir(parents=True,exist_ok=True)
  fd=os.open(out,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
  with os.fdopen(fd,'w') as f:json.dump(r,f,ensure_ascii=False,indent=2)
  print(json.dumps({'status':'complete','report':str(out),'eligible_files':r['eligible_files'],'duplicate_groups':r['duplicate_groups'],'logical_duplicate_upper_bytes_not_reclaimable':r['logical_duplicate_upper_bytes'],'source_changes_seen':len(r['changed_during_scan']),'files_deleted':0}));return 0
 except (OSError,ValueError,RuntimeError,subprocess.SubprocessError) as e:
  print(json.dumps({'status':'error','error':str(e),'originals_retained':True}),file=sys.stderr);return 1
if __name__=='__main__':raise SystemExit(main())
