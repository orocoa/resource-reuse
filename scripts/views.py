#!/usr/bin/env python3
"""Named read-only views of one project's existing pool. Never replace originals."""
import argparse,json,os,sqlite3,stat,sys,unicodedata
from pathlib import Path,PurePosixPath
sys.dont_write_bytecode=True
import reuse as rp
import project_scope as scope

SCHEMA='resource-reuse-reference-view-v1'
INDEX='.resource-view.json'
MANAGED=rp.BLOCKED|{'.pnpm-store','vendor','Library','__pycache__','.codex','.agents'}
ASSET_KINDS={'image','font','video','audio','document','archive','model','design-source'}

def reviewed_role(role):
 return isinstance(role,str) and bool(role.strip()) and not any(x in role.casefold() for x in ('needs-review','unreviewed','unassigned'))

def logical_name(value):
 if not isinstance(value,str) or not value or '\\' in value or '\0' in value:
  raise ValueError('View names must be nonempty relative POSIX paths')
 parts=value.split('/')
 if any(p in ('','.', '..') or p.casefold()==INDEX or p.casefold() in {x.casefold() for x in MANAGED} or p.casefold().endswith(('.app','.photoslibrary','.musiclibrary','.sparsebundle')) for p in parts):
  raise ValueError('Unsafe or managed view path')
 if PurePosixPath(value).is_absolute():raise ValueError('Absolute view name refused')
 return value

def normalize_entries(entries):
 if not isinstance(entries,list) or not entries:raise ValueError('Choose at least one reviewed read-only resource')
 result=[];seen=set()
 for e in entries:
  if not isinstance(e,dict) or set(e)!={'path','id'}:raise ValueError('Each entry requires only path and id')
  name=logical_name(e['path']);key=unicodedata.normalize('NFC',name).casefold()
  if not isinstance(e['id'],str) or not e['id']:raise ValueError('Missing resource id')
  if key in seen:raise ValueError('Duplicate or case/normalization-colliding view name')
  seen.add(key);result.append({'path':name,'id':e['id']})
 for key in seen:
  parts=key.split('/')
  if any('/'.join(parts[:i]) in seen for i in range(1,len(parts))):raise ValueError('View file/directory name collision')
 return sorted(result,key=lambda e:e['path'])

def view_location(value):
 p=scope.require_path(Path(value).expanduser().absolute(),write=True);rp.no_link_ancestors(p)
 if any(part.casefold() in {x.casefold() for x in MANAGED} or part.casefold().endswith(('.app','.photoslibrary','.musiclibrary','.sparsebundle')) for part in p.parts):raise ValueError('View belongs outside managed stores')
 skill=Path(__file__).resolve().parents[1]
 if p==skill or skill in p.parents:raise ValueError('Generated views belong outside the shareable skill')
 return p

def selected_resources(pool,entries):
 pool,d=rp.pool_db(pool);d.close();resources={}
 for e in entries:
  if e['id'] in resources:continue
  r=rp.resolve_resource(pool=pool,rid=e['id'])
  if not reviewed_role(r.get('role')):raise ValueError('Resource purpose must be reviewed before reference use')
  if r['kind'] not in ASSET_KINDS:raise ValueError('Use independent materialization for source code, runtimes and editable fixtures')
  if Path(r['path']).stat().st_mode&0o222:raise ValueError('Pool object must have its normal read-only permissions')
  resources[e['id']]=r
 return pool,resources

def create_view(pool,entries,to,read_only_assets=False):
 if not read_only_assets:raise ValueError('Reference views are only for explicitly reviewed read-only assets; use materialize for editable data')
 entries=normalize_entries(entries);dest=view_location(to);pool,resources=selected_resources(pool,entries)
 if dest==pool or pool in dest.parents or dest in pool.parents:raise ValueError('View and pool must be separate directories')
 if dest.exists():
  result=verify_view(dest)
  existing=read_index(dest)
  if existing['entries']!=entries or (dest/existing['pool']).resolve()!=pool:raise FileExistsError('Existing view differs; retained without overwrite')
  return {**result,'status':'existing-identical-view','new_files_created':False}
 dest.parent.mkdir(parents=True,exist_ok=True);dest.mkdir(mode=0o700)
 # Any interrupted new view is retained for inspection; no existing path is removed.
 for e in entries:
  link=dest/e['path'];link.parent.mkdir(parents=True,exist_ok=True)
  link.symlink_to(os.path.relpath(resources[e['id']]['path'],link.parent))
 index={'schema':SCHEMA,'project_id':scope.selection()['id'],'pool':os.path.relpath(pool,dest),'access':'read-only-assets','entries':entries,
        'pinned':{rid:{'sha256':r['sha256'],'size':r['size']} for rid,r in resources.items()}}
 with (dest/INDEX).open('x') as f:json.dump(index,f,ensure_ascii=False,indent=2)
 os.chmod(dest/INDEX,0o600)
 return {**verify_view(dest),'status':'reference-view-created','new_files_created':True}

def read_index(dest):
 dest=view_location(dest);p,s=rp.safe_source(dest/INDEX);index=json.loads(p.read_text())
 if rp.signature(p.stat())!=rp.signature(s):raise ValueError('View index changed while reading')
 if not isinstance(index,dict) or index.get('schema')!=SCHEMA or index.get('access')!='read-only-assets':raise ValueError('Not a reference view')
 if index.get('project_id')!=scope.selection()['id']:raise ValueError('View belongs to another project')
 entries=normalize_entries(index.get('entries'))
 if entries!=index['entries']:raise ValueError('Unnormalized view index')
 if not isinstance(index.get('pool'),str) or Path(index['pool']).is_absolute():raise ValueError('Pool reference must be relative within this project')
 pool=(dest/index['pool']).resolve();scope.require_path(pool)
 if pool==dest or pool in dest.parents or dest in pool.parents:raise ValueError('View and pool overlap')
 return index

def check_entry(dest,index,e,r):
 if index.get('pinned',{}).get(e['id'])!={'sha256':r['sha256'],'size':r['size']}:raise ValueError('Pinned resource identity changed')
 link=dest/e['path'];rp.no_link_ancestors(link.parent)
 if not link.is_symlink() or os.readlink(link)!=os.path.relpath(r['path'],link.parent):raise ValueError('View link is missing, changed or points outside its pinned object')

def check_view(dest,index):
 pool,resources=selected_resources((dest/index['pool']).resolve(),index['entries'])
 expected={INDEX};unique={};logical=0
 for e in index['entries']:
  r=resources[e['id']];check_entry(dest,index,e,r)
  expected.add(e['path']);expected.update(str(p) for p in PurePosixPath(e['path']).parents if str(p)!='.')
  unique[r['sha256']]=r['size'];logical+=r['size']
 actual=set();allocated=0;regular_payload=0
 for current,dirs,files in os.walk(dest,followlinks=False):
  for name in dirs+files:
   p=Path(current)/name;actual.add(p.relative_to(dest).as_posix());s=p.lstat();allocated+=s.st_blocks*512
   if stat.S_ISREG(s.st_mode) and p.name!=INDEX:regular_payload+=s.st_size
 if actual!=expected or regular_payload:raise ValueError('Unexpected view content; retained for inspection')
 return {'status':'verified-reference-view','path':str(dest),'entries':len(index['entries']),'unique_content_objects':len(unique),'referenced_logical_bytes':logical,
         'unique_content_bytes':sum(unique.values()),'view_regular_payload_bytes':0,'view_metadata_allocated_bytes':allocated,'payload_bytes_copied':0,'originals_modified':0,
         'limits':'This counts references, not released space. Keep the pool with the view; exports and external drives need a verified self-contained copy. The owner can override read-only permissions.'}

def verify_view(value):
 dest=view_location(value);return check_view(dest,read_index(dest))

def resolve_view(value,name):
 dest=view_location(value);index=read_index(dest);name=logical_name(name)
 match=[e for e in index['entries'] if e['path']==name]
 if not match:raise FileNotFoundError('Logical resource is not in this view')
 pool,resources=selected_resources((dest/index['pool']).resolve(),match);r=resources[match[0]['id']]
 check_entry(dest,index,match[0],r)
 return {**r,'view_path':str(dest/name),'new_file_created':False}

def export_view(value,to,allow_copy=False):
 source=view_location(value);index=read_index(source);check_view(source,index)
 dest=view_location(to);pool,resources=selected_resources((source/index['pool']).resolve(),index['entries'])
 if any(dest==p or p in dest.parents or dest in p.parents for p in (pool,source)):raise ValueError('Export must be separate from its view and pool')
 expected=set()
 for e in index['entries']:
  expected.add(e['path']);expected.update(str(p) for p in PurePosixPath(e['path']).parents if str(p)!='.')
 def validate():
  actual=set()
  for current,dirs,files in os.walk(dest,followlinks=False):
   for name in dirs+files:
    p=Path(current)/name
    if p.is_symlink():raise ValueError('Export contains a link; retained without following')
    actual.add(p.relative_to(dest).as_posix())
  if actual!=expected:raise FileExistsError('Existing export differs; retained without overwrite')
  for e in index['entries']:
   target=dest/e['path'];r=resources[e['id']];rp.no_link_ancestors(target)
   if not target.is_file() or rp.sha_file(target)!=r['sha256']:raise ValueError('Exported content differs from its pinned object')
   a=target.stat();b=Path(r['path']).stat()
   if (a.st_dev,a.st_ino)==(b.st_dev,b.st_ino):raise ValueError('Export must use independent files, not writable hard links')
  return True
 existed=dest.exists()
 if existed:validate()
 else:
  dest.parent.mkdir(parents=True,exist_ok=True);dest.mkdir(mode=0o700)
  for e in index['entries']:rp.materialize(pool,e['id'],dest/e['path'],allow_copy)
  validate()
 return {'status':'existing-identical-export' if existed else 'self-contained-export-created','path':str(dest),'files':len(index['entries']),
         'logical_bytes':sum(resources[e['id']]['size'] for e in index['entries']),'symbolic_links':0,'independent_files':True,'new_files_created':not existed,
         'originals_modified':0,'limits':'Standalone files verified against pinned hashes. This is not a verified external-drive transfer or a guarantee that the consuming application works.'}

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--project-root');p.add_argument('--config');sub=p.add_subparsers(dest='cmd',required=True)
 a=sub.add_parser('create');a.add_argument('--pool',required=True);a.add_argument('--manifest',required=True);a.add_argument('--to',required=True);a.add_argument('--read-only-assets',action='store_true')
 a=sub.add_parser('verify');a.add_argument('--view',required=True)
 a=sub.add_parser('resolve');a.add_argument('--view',required=True);a.add_argument('--path',required=True)
 a=sub.add_parser('export');a.add_argument('--view',required=True);a.add_argument('--to',required=True);a.add_argument('--allow-copy',action='store_true')
 a=p.parse_args();scope.configure(a.project_root,a.config)
 try:
  if a.cmd=='create':
   source,st=rp.safe_source(a.manifest);spec=json.loads(source.read_text())
   if rp.signature(source.stat())!=rp.signature(st):raise ValueError('Manifest changed while reading')
   result=create_view(a.pool,spec['entries'],a.to,a.read_only_assets)
  elif a.cmd=='verify':result=verify_view(a.view)
  elif a.cmd=='resolve':result=resolve_view(a.view,a.path)
  else:result=export_view(a.view,a.to,a.allow_copy)
  print(json.dumps(result,ensure_ascii=False,indent=2));return 0
 except (OSError,ValueError,KeyError,TypeError,sqlite3.Error) as e:
  print(json.dumps({'status':'error','error':str(e),'originals_retained':True},ensure_ascii=False),file=sys.stderr);return 1
if __name__=='__main__':raise SystemExit(main())
