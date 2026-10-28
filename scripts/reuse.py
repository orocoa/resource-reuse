#!/usr/bin/env python3
"""Local content-addressed resources. No source moves, deletion, or overwrites."""
import argparse,ctypes,hashlib,json,os,secrets,shutil,sqlite3,stat,sys,time
sys.dont_write_bytecode=True
from vendor.ecc_hash import compute_file_hash
import project_scope as scope
def set_project_root(root):scope.set_root(root)
CONFIG_PATH = None
from pathlib import Path

SCHEMA='resource-reuse-project-pool-v1'
DATALESS=getattr(stat,'UF_DATALESS',0x40000000)
ASSETS={'.ttf':'font','.otf':'font','.woff':'font','.woff2':'font','.png':'image','.jpg':'image','.jpeg':'image','.webp':'image','.gif':'image','.svg':'image','.mp4':'video','.mov':'video','.webm':'video','.m4v':'video','.mp3':'audio','.wav':'audio','.m4a':'audio','.flac':'audio','.pdf':'document','.docx':'document','.xlsx':'document','.pptx':'document','.zip':'archive','.gz':'archive','.xz':'archive','.tgz':'archive','.dmg':'archive','.pkg':'archive','.7z':'archive','.stl':'model','.obj':'model','.blend':'model','.3dm':'model'}
ASSETS.update({'.ttc':'font','.eot':'font','.ico':'image','.icns':'image','.heic':'image','.heif':'image','.avif':'image','.tif':'image','.tiff':'image','.bmp':'image','.eps':'design-source','.ai':'design-source','.psd':'design-source','.sketch':'design-source','.glb':'model','.gltf':'model','.fbx':'model','.step':'model','.stp':'model','.3mf':'model','.aif':'audio','.aiff':'audio','.ogg':'audio','.opus':'audio','.mkv':'video','.avi':'video'})
BLOCKED={'.git','node_modules','.pnpm','.venv','venv','.ssh','.gnupg','.aws'}

def sha_file(path):
 return compute_file_hash(Path(path))

def signature(s):return (s.st_dev,s.st_ino,s.st_size,s.st_mtime_ns,s.st_ctime_ns)

def no_link_ancestors(path):
 for p in [Path(path),*Path(path).parents]:
  if p.is_symlink():raise ValueError('Symlinked destination or pool ancestor is not allowed: '+str(p))

def safe_source(path):
 p=Path(path).expanduser().absolute();scope.require_path(p);no_link_ancestors(p);s=p.lstat()
 if p.is_symlink() or not stat.S_ISREG(s.st_mode):raise ValueError('Source must be a regular file, not a link')
 if getattr(s,'st_flags',0)&DATALESS or p.name.endswith('.icloud'):raise ValueError('Cloud placeholder is not downloaded; not read')
 if any(part in BLOCKED or part.endswith(('.app','.photoslibrary','.musiclibrary','.sparsebundle')) for part in p.resolve().parts):raise ValueError('Managed repository/package/application contents are not resource-pool inputs')
 if s.st_mode&(stat.S_ISUID|stat.S_ISGID):raise ValueError('Privileged executable metadata is not a resource-pool input')
 if p.suffix.lower() in ('.db','.sqlite','.sqlite3','.key','.pem','.p12') or p.name.startswith('.env') or p.name.lower() in ('auth.json','credentials','credentials.json','config.json'):
  raise ValueError('Credentials, databases and configuration are not resource-pool inputs')
 return p,s

def quarantine_present(path):
 if sys.platform!='darwin':return False
 lib=ctypes.CDLL('/usr/lib/libSystem.B.dylib',use_errno=True)
 lib.listxattr.argtypes=[ctypes.c_char_p,ctypes.c_void_p,ctypes.c_size_t,ctypes.c_int];lib.listxattr.restype=ctypes.c_ssize_t
 n=lib.listxattr(os.fsencode(path),None,0,1)
 if n<0:raise OSError(ctypes.get_errno(),'Cannot inspect source extended attributes')
 if not n:return False
 buf=ctypes.create_string_buffer(n)
 if lib.listxattr(os.fsencode(path),buf,n,1)!=n:raise ValueError('Source metadata changed')
 return b'com.apple.quarantine' in buf.raw.split(b'\0')

def pool_db(pool,write=False):
 pool=Path(pool).expanduser().absolute()
 no_link_ancestors(pool)
 marker=pool/'resource-pool.json'
 if marker.is_symlink() or not marker.is_file() or json.loads(marker.read_text()).get('schema')!=SCHEMA:raise ValueError('Not an initialized resource pool')
 scope.assert_pool(json.loads(marker.read_text()),pool)
 if pool.is_symlink() or (pool/'index.sqlite').is_symlink():raise ValueError('Pool or index must not be a symlink')
 d=sqlite3.connect(str(pool/'index.sqlite') if write else 'file:'+str(pool/'index.sqlite')+'?mode=ro',uri=not write)
 d.row_factory=sqlite3.Row
 return pool,d

def init_pool(pool):
 p=Path(pool).expanduser().absolute();scope.require_path(p,write=True)
 no_link_ancestors(p)
 if any(part in BLOCKED or part.endswith(('.app','.photoslibrary','.musiclibrary')) for part in p.parts):raise ValueError('Shared pools belong outside application/package/repository internals')
 if p.exists() and p.is_symlink():raise ValueError('Pool path cannot be a symlink')
 p.mkdir(parents=True,mode=0o700,exist_ok=True)
 marker=p/'resource-pool.json'
 if marker.exists():
  pool_db(p)[1].close();return {'status':'existing','pool':str(p)}
 if any(p.iterdir()):raise ValueError('New pool directory is not empty')
 (p/'objects').mkdir(mode=0o700);(p/'by-name').mkdir(mode=0o700);(p/'tmp').mkdir(mode=0o700)
 marker.write_text(json.dumps({'schema':SCHEMA,'id':secrets.token_hex(12),'created_at':time.time(),'project_root':scope.selection()['project_root'],'project_id':scope.selection()['id']},ensure_ascii=False,indent=2))
 d=sqlite3.connect(p/'index.sqlite')
 d.execute('CREATE TABLE resources(id TEXT PRIMARY KEY,sha256 TEXT,name TEXT,kind TEXT,size INTEGER,mode INTEGER,mtime_ns INTEGER,reuse_key TEXT,role TEXT,license TEXT,created_at REAL,UNIQUE(sha256,name,kind))')
 d.execute('CREATE INDEX resources_key ON resources(reuse_key)')
 d.execute('CREATE TABLE reuse_keys(reuse_key TEXT,resource_id TEXT,PRIMARY KEY(reuse_key,resource_id))')
 d.execute('CREATE TABLE origins(resource_id TEXT,path TEXT,dev INTEGER,ino INTEGER,size INTEGER,mtime_ns INTEGER,ctime_ns INTEGER,seen_at REAL,PRIMARY KEY(resource_id,path))')
 d.execute('CREATE TABLE events(at REAL,operation TEXT,resource_id TEXT,logical_bytes INTEGER,detail TEXT)');d.commit();d.close()
 os.chmod(p/'index.sqlite',0o600)
 (p/'.gitignore').write_text('*\n!.gitignore\n')
 return {'status':'created','pool':str(p)}

def cow_clone(source,temp,allow_copy=False):
 """Clone an already-open source inode. No fallback physical copy by default."""
 source=Path(source);temp=Path(temp);no_link_ancestors(temp)
 if temp.exists() or temp.is_symlink():raise FileExistsError(str(temp))
 fd=os.open(source,os.O_RDONLY|getattr(os,"O_NOFOLLOW",0));parent=None
 try:
  st=os.fstat(fd)
  if not stat.S_ISREG(st.st_mode) or getattr(st,'st_flags',0)&DATALESS:raise ValueError('Source is not a downloaded regular file')
  if sys.platform=='darwin':
   lib=ctypes.CDLL('/usr/lib/libSystem.B.dylib',use_errno=True)
   lib.fclonefileat.argtypes=[ctypes.c_int,ctypes.c_int,ctypes.c_char_p,ctypes.c_int];lib.fclonefileat.restype=ctypes.c_int
   parent=os.open(temp.parent,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
   if lib.fclonefileat(fd,parent,os.fsencode(temp.name),0)==0:
    if signature(os.fstat(fd))!=signature(st):raise ValueError('Source changed during clone')
    if temp.stat().st_ino==st.st_ino and temp.stat().st_dev==st.st_dev:raise ValueError('Clone must have an independent inode')
    return 'apfs-cow'
   code=ctypes.get_errno()
   if not allow_copy:raise OSError(code,'COW unavailable; physical-copy fallback requires --allow-copy')
  elif not allow_copy:raise ValueError('COW backend not enabled on this platform; explicit --allow-copy required')
  shutil.copy2(source,temp)
  if signature(os.fstat(fd))!=signature(st):raise ValueError('Source changed during copy')
  return 'physical-copy-explicit'
 finally:
  os.close(fd)
  if parent is not None:os.close(parent)

def publish_new(temp,dest):
 """No-clobber atomic publication; the temporary link is removed immediately."""
 try:os.link(temp,dest,follow_symlinks=False)
 except FileExistsError:return False
 os.unlink(temp)
 return True

def add(pool,source,name=None,kind=None,key=None,role='needs-review',license='unverified',expected=None,allow_copy=False):
 pool,d=pool_db(pool,True);p,s=safe_source(source)
 if quarantine_present(p):raise ValueError('Quarantined original retained; use its original indexed location and normal OS approval flow')
 name=name or p.name;kind=kind or ASSETS.get(p.suffix.lower(),'other')
 if not name or '/' in name or '\\' in name or '\0' in name:raise ValueError('Name must be a single filename')
 if not kind or kind in ('.','..') or '/' in kind or '\\' in kind or '\0' in kind:raise ValueError('Kind must be a safe single folder name')
 h=sha_file(p)
 if expected and h.lower()!=expected.lower():raise ValueError('Source differs from the audited content hash')
 if signature(p.stat())!=signature(s):raise ValueError('Source changed while reading')
 if key:
  conflict=d.execute('SELECT r.sha256 FROM resources r JOIN reuse_keys k ON k.resource_id=r.id WHERE k.reuse_key=? AND r.sha256!=?',(key,h)).fetchone()
  if conflict:raise ValueError('Reuse key already maps to different bytes; include version/inputs/tool parameters in key')
 obj=pool/'objects'/h[:2]/h;no_link_ancestors(obj);obj.parent.mkdir(mode=0o700,exist_ok=True)
 method='existing-object'
 if obj.exists():
  if obj.is_symlink() or sha_file(obj)!=h:raise ValueError('Existing pool object failed integrity check; retained for inspection')
 else:
  temp=pool/'tmp'/(secrets.token_hex(16)+'.part')
  method=cow_clone(p,temp,allow_copy)
  if sha_file(temp)!=h or signature(p.stat())!=signature(s):raise ValueError('Source or cloned bytes changed; original retained')
  os.chmod(temp,stat.S_IMODE(s.st_mode)&~0o222)
  if not publish_new(temp,obj):
   if sha_file(obj)!=h:raise ValueError('Concurrent object publication differs')
   temp.unlink()
  if sha_file(obj)!=h:raise ValueError('Published object failed readback')
 rid=hashlib.sha256((h+'\0'+name+'\0'+kind).encode()).hexdigest()[:24]
 d.execute('INSERT OR IGNORE INTO resources VALUES(?,?,?,?,?,?,?,?,?,?,?)',(rid,h,name,kind,s.st_size,stat.S_IMODE(s.st_mode),s.st_mtime_ns,key,role,license,time.time()))
 if key:
  d.execute('UPDATE resources SET reuse_key=coalesce(reuse_key,?) WHERE id=?',(key,rid))
  d.execute('INSERT OR IGNORE INTO reuse_keys VALUES(?,?)',(key,rid))
 d.execute('INSERT OR REPLACE INTO origins VALUES(?,?,?,?,?,?,?,?)',(rid,str(p),s.st_dev,s.st_ino,s.st_size,s.st_mtime_ns,s.st_ctime_ns,time.time()))
 d.execute('INSERT INTO events VALUES(?,?,?,?,?)',(time.time(),'add',rid,s.st_size,method));d.commit();d.close()
 aliasdir=pool/'by-name'/kind;no_link_ancestors(aliasdir);aliasdir.mkdir(mode=0o700,exist_ok=True)
 alias=aliasdir/(Path(name).stem+'__'+h[:12]+Path(name).suffix)
 relative=os.path.relpath(obj,aliasdir)
 if not alias.exists() and not alias.is_symlink():alias.symlink_to(relative)
 elif not alias.is_symlink() or os.readlink(alias)!=relative:raise ValueError('Human-readable alias conflict; original alias retained')
 return {'status':'registered','id':rid,'sha256':h,'name':name,'kind':kind,'pool':str(pool),'object':str(obj),'browse_path':str(alias),'storage':method,'logical_bytes':s.st_size,'role':role}

def configured_pools():
 return configuration().get('pools',[])

def configuration():
 return scope.selection()

def tree_inventory(source):
 root=Path(source).absolute()
 if getattr(root.lstat(),'st_flags',0)&DATALESS:raise ValueError('Cloud directory not downloaded')
 if root.is_symlink() or not root.is_dir():raise ValueError('Tree source must be a real directory')
 result={}
 def walk_error(error):raise error
 for current,dirs,files in os.walk(root,followlinks=False,onerror=walk_error):
  for name in sorted(dirs+files):
   p=Path(current)/name;rel=p.relative_to(root).as_posix();s=p.lstat()
   if getattr(s,'st_flags',0)&DATALESS:raise ValueError('Tree contains an undownloaded cloud entry')
   e={'mode':stat.S_IMODE(s.st_mode),'mtime_ns':s.st_mtime_ns,'signature':signature(s)}
   if p.is_symlink():
    target=os.readlink(p)
    if os.path.isabs(target):raise ValueError('Tree contains an absolute link: '+rel)
    try:p.resolve().relative_to(root.resolve())
    except (ValueError,RuntimeError):raise ValueError('Tree contains an external/cyclic link: '+rel)
    e.update(kind='link',target=target)
   elif p.is_dir():e.update(kind='dir')
   elif p.is_file():e.update(kind='file',size=s.st_size,sha256=sha_file(p))
   else:raise ValueError('Tree contains a special file: '+rel)
   result[rel]=e
 return result

def tree_digest(inv):
 view={p:{k:v for k,v in e.items() if k not in ('signature','mtime_ns')} for p,e in inv.items()}
 return hashlib.sha256(json.dumps(view,sort_keys=True,ensure_ascii=True,separators=(',',':')).encode()).hexdigest()

def clone_tree(source,to,expected=None,allow_copy=False):
 source=Path(source).expanduser().absolute();dest=Path(to).expanduser().absolute();scope.require_path(source);scope.require_path(dest,write=True);no_link_ancestors(source);no_link_ancestors(dest)
 if dest.exists() or dest.is_symlink():raise FileExistsError('Tree destination must not exist')
 if source==dest or source in dest.parents or source.resolve() in dest.resolve().parents:raise ValueError('Tree destination must be outside source')
 root_metadata=source.stat();before=tree_inventory(source);h=tree_digest(before)
 if expected and h!=expected:raise ValueError('Tree differs from required content/version')
 dest.mkdir(parents=True)
 for rel,e in sorted(before.items(),key=lambda x:(x[0].count('/'),x[0])):
  p=source/rel;q=dest/rel
  if e['kind']=='dir':q.mkdir(exist_ok=True)
  elif e['kind']=='link':q.symlink_to(e['target'])
  else:
   q.parent.mkdir(parents=True,exist_ok=True);cow_clone(p,q,allow_copy)
   os.chmod(q,e['mode']);os.utime(q,ns=(time.time_ns(),e['mtime_ns']))
   if sha_file(q)!=e['sha256']:raise ValueError('Tree file readback mismatch: '+rel)
 for rel,e in sorted(before.items(),key=lambda x:x[0].count('/'),reverse=True):
  if e['kind']=='dir':os.chmod(dest/rel,e['mode']);os.utime(dest/rel,ns=(time.time_ns(),e['mtime_ns']))
 os.chmod(dest,stat.S_IMODE(root_metadata.st_mode));os.utime(dest,ns=(time.time_ns(),root_metadata.st_mtime_ns))
 after=tree_inventory(source)
 if before!=after:raise ValueError('Tree source changed during materialization; retained copy needs inspection')
 result=tree_inventory(dest)
 if tree_digest(result)!=h:raise ValueError('Full tree content or modes differ')
 return {'status':'tree-materialized','source':str(source),'path':str(dest),'sha256':h,'entries':len(before),'files':sum(e['kind']=='file' for e in before.values()),'logical_bytes_reused':sum(e.get('size',0) for e in before.values()),'storage':'apfs-cow' if sys.platform=='darwin' and not allow_copy else 'inspect-per-platform','source_unchanged':True}

def lookup(pools,query='',key=None,limit=30):
 results=[]
 for p in pools:
  if not Path(p).exists():continue
  pool,d=pool_db(p)
  sql='SELECT r.* FROM resources r JOIN reuse_keys k ON k.resource_id=r.id WHERE k.reuse_key=?' if key else 'SELECT * FROM resources WHERE instr(lower(name||" "||kind||" "||coalesce(reuse_key,"")),lower(?))>0 ORDER BY created_at DESC'
  rows=d.execute(sql,(key if key else query,)).fetchmany(limit)
  for row in rows:
   r=dict(row)
   if key:r['reuse_key']=key
   r.update(pool=str(pool),object=str(pool/'objects'/r['sha256'][:2]/r['sha256']),status='pool-entry-verify-on-use');results.append(r)
  d.close()
 return results[:limit]

def materialize(pool,rid,to,allow_copy=False):
 pool,d=pool_db(pool,True);row=d.execute('SELECT * FROM resources WHERE id=?',(rid,)).fetchone()
 if row is None:raise ValueError('Resource ID not found')
 r=dict(row);obj=pool/'objects'/r['sha256'][:2]/r['sha256'];dest=Path(to).expanduser().absolute()
 scope.require_path(dest,write=True);no_link_ancestors(dest)
 if pool==dest or pool in dest.parents:raise ValueError('Destination must be outside this pool')
 if dest.is_symlink():raise ValueError('Existing destination link is retained; not followed')
 if dest.exists():
  if dest.is_file() and sha_file(dest)==r['sha256']:
   d.execute('INSERT INTO events VALUES(?,?,?,?,?)',(time.time(),'reuse-existing',rid,r['size'],str(dest)));d.commit();d.close();return {'status':'existing-identical','path':str(dest),'new_file_created':False}
  raise FileExistsError('Destination differs; no overwrite: '+str(dest))
 if sha_file(obj)!=r['sha256']:raise ValueError('Pool object corrupt; no destination created')
 dest.parent.mkdir(parents=True,exist_ok=True)
 temp=dest.parent/('.resource-reuse-'+secrets.token_hex(12)+'.part');method=cow_clone(obj,temp,allow_copy)
 os.chmod(temp,r['mode']);os.utime(temp,ns=(time.time_ns(),r['mtime_ns']))
 if sha_file(temp)!=r['sha256']:raise ValueError('Materialized content verification failed')
 if not publish_new(temp,dest):
  if dest.is_file() and not dest.is_symlink() and sha_file(dest)==r['sha256']:temp.unlink();return {'status':'concurrent-identical','path':str(dest)}
  raise FileExistsError('Destination appeared during materialization; retained')
 if dest.stat().st_ino==obj.stat().st_ino and dest.stat().st_dev==obj.stat().st_dev:raise ValueError('Destination must be independent of cache object')
 d.execute('INSERT INTO events VALUES(?,?,?,?,?)',(time.time(),'materialize',rid,r['size'],method));d.commit();d.close()
 return {'status':'materialized','path':str(dest),'storage':method,'sha256':r['sha256'],'independent_inode':True,'logical_bytes_reused':r['size']}

def verify(pool):
 pool,d=pool_db(pool);rows=d.execute('SELECT DISTINCT sha256,size FROM resources').fetchall();errors=[]
 for r in rows:
  p=pool/'objects'/r['sha256'][:2]/r['sha256']
  if not p.is_file() or p.is_symlink() or p.stat().st_size!=r['size'] or sha_file(p)!=r['sha256']:errors.append(r['sha256'])
 result={'pool':str(pool),'objects_checked':len(rows),'resources':d.execute('SELECT count(*) FROM resources').fetchone()[0],'origins':d.execute('SELECT count(*) FROM origins').fetchone()[0],'verified':not errors,'errors':errors};d.close();return result

def resolve_resource(key=None,pool=None,rid=None,config=None):
 """Verify a selected exact key/id for direct read-only use by a producer."""
 cfg=configuration() if config is None else config
 if bool(key)==bool(rid):raise ValueError('Select exactly one --key or --id')
 if rid and not pool:raise ValueError('--id requires --pool')
 trees=[r for r in cfg.get('trees',[]) if key and r.get('reuse_key')==key and not pool]
 rows=[]
 for item in ([pool] if pool else cfg.get('pools',[])):
  if not Path(item).exists():continue
  p,d=pool_db(item)
  try:
   sql='SELECT * FROM resources WHERE id=?' if rid else 'SELECT r.* FROM resources r JOIN reuse_keys k ON k.resource_id=r.id WHERE k.reuse_key=?'
   for row in d.execute(sql,(rid or key,)):
    r=dict(row)
    if key:r['reuse_key']=key
    r.update(pool=str(p),object=str(p/'objects'/r['sha256'][:2]/r['sha256']));rows.append(r)
  finally:d.close()
 if len(trees)+len(rows)==0:raise FileNotFoundError('Exact resource not found; no generation/download performed')
 # A duplicated key can have distinct purpose, permissions or platform metadata.
 # Require the caller to choose a pool/id rather than guessing between them.
 if len(trees)+len(rows)!=1:raise ValueError('Ambiguous resource key; select a pool/id or a unique tree key')
 if trees:
  r=trees[0];p=Path(r['path']).absolute();scope.require_path(p);no_link_ancestors(p)
  before=tree_inventory(p)
  if tree_digest(before)!=r['sha256']:raise ValueError('Selected tree changed; no reuse')
  return {**r,'status':'verified-existing','resource_type':'tree','path':str(p),'verified':True,'new_file_created':False,'usage':'Use read-only; materialize-tree for writable isolation'}
 r=rows[0];p=Path(r['object']);no_link_ancestors(p);s=p.lstat()
 if not stat.S_ISREG(s.st_mode) or getattr(s,'st_flags',0)&DATALESS:raise ValueError('Pool object is not a downloaded regular file')
 if quarantine_present(p):raise ValueError('Quarantined pool object retained; no reuse')
 if s.st_size!=r['size'] or sha_file(p)!=r['sha256'] or signature(p.stat())!=signature(s):raise ValueError('Selected object changed or is corrupt; no reuse')
 return {**r,'status':'verified-existing','resource_type':'file','path':str(p),'verified':True,'new_file_created':False,'usage':'Use read-only; materialize for writable isolation'}

def materialize_tree(key,to,allow_copy=False,config=None):
 r=resolve_resource(key=key,config=config)
 if r['resource_type']!='tree':raise ValueError('Selected key is a file; use materialize')
 dest=Path(to).expanduser().absolute();scope.require_path(dest,write=True);no_link_ancestors(dest)
 cfg=configuration() if config is None else config
 for p in cfg.get('pools',[]):
  p=Path(p).absolute()
  if dest==p or p in dest.parents:raise ValueError('Destination must be outside resource pools')
 if dest.exists():
  if not dest.is_dir() or tree_digest(tree_inventory(dest))!=r['sha256']:raise FileExistsError('Existing tree differs; retained without overwrite')
  return {'status':'existing-identical-tree','path':str(dest),'sha256':r['sha256'],'new_file_created':False}
 return clone_tree(r['path'],dest,r['sha256'],allow_copy)

def recipe_key(inputs,tool,version,platform,params):
 hashes=[]
 for value in inputs:
  path,before=safe_source(value)
  hashes.append(sha_file(path))
  if signature(path.stat())!=signature(before):raise ValueError('Input changed while deriving cache key')
 recipe={'schema':'resource-reuse-recipe-v2','project_scope':scope.selection()['id'],'input_hashes_in_order':hashes,'tool':tool,'version':version,'platform':platform,'parameters':params}
 h=hashlib.sha256(json.dumps(recipe,sort_keys=True,separators=(',',':'),ensure_ascii=True).encode()).hexdigest()
 return {'reuse_key':'recipe:sha256:'+h,'recipe':recipe}

def main():
 global CONFIG_PATH
 p=argparse.ArgumentParser(description=__doc__);p.add_argument("--project-root",help="Verified main project folder; never a global material pool");p.add_argument("--config",help="External user-owned JSON; never bundle actual pools or indexes");sub=p.add_subparsers(dest='cmd',required=True)
 a=sub.add_parser('init');a.add_argument('--pool',required=True)
 a=sub.add_parser('add');a.add_argument('--pool',required=True);a.add_argument('--source',required=True);a.add_argument('--name');a.add_argument('--kind');a.add_argument('--key');a.add_argument('--role',default='needs-review');a.add_argument('--license',default='unverified');a.add_argument('--expected-sha256');a.add_argument('--allow-copy',action='store_true')
 a=sub.add_parser('lookup');a.add_argument('--pool',action='append');a.add_argument('--query',default='');a.add_argument('--key');a.add_argument('--limit',type=int,default=30)
 a=sub.add_parser('materialize');a.add_argument('--pool',required=True);a.add_argument('--id',required=True);a.add_argument('--to',required=True);a.add_argument('--allow-copy',action='store_true')
 a=sub.add_parser('verify');a.add_argument('--pool',required=True)
 a=sub.add_parser('clone-tree');a.add_argument('--source',required=True);a.add_argument('--to',required=True);a.add_argument('--expected-sha256');a.add_argument('--allow-copy',action='store_true')
 a=sub.add_parser('resolve',help='Verify an exact existing resource for direct read-only use; never generates or downloads')
 s=a.add_mutually_exclusive_group(required=True);s.add_argument('--key');s.add_argument('--id');a.add_argument('--pool')
 a=sub.add_parser('materialize-tree',help='Reuse an identical existing destination or make one independent COW tree')
 a.add_argument('--key',required=True);a.add_argument('--to',required=True);a.add_argument('--allow-copy',action='store_true')
 a=sub.add_parser('key',help='Derive a path-independent key including tool/version/platform/parameters');a.add_argument('--input',action='append',required=True);a.add_argument('--tool',required=True);a.add_argument('--version',required=True);a.add_argument('--platform',required=True);a.add_argument('--params-json',default='{}')
 args=p.parse_args()
 CONFIG_PATH=args.config
 scope.configure(args.project_root,args.config)
 try:
  if args.cmd=='key':r=recipe_key(args.input,args.tool,args.version,args.platform,json.loads(args.params_json))
  elif args.cmd=='init':r=init_pool(args.pool)
  elif args.cmd=='add':r=add(args.pool,args.source,args.name,args.kind,args.key,args.role,args.license,args.expected_sha256,args.allow_copy)
  elif args.cmd=='lookup':
   rows=lookup(args.pool or configured_pools(),args.query,args.key,args.limit)
   trees=[r for r in configuration().get('trees',[]) if (args.key and r.get('reuse_key')==args.key) or (not args.key and args.query.casefold() in (' '.join([r.get('name',''),r.get('reuse_key',''),(r.get('validation') or {}).get('version_output','')])).casefold())]
   r={'status':'hit' if rows or trees else 'miss','matches':rows,'tree_matches':trees,'note':'Filename match is not proof of the required version or license. Select a resource ID and materialize without overwrite.'}
  elif args.cmd=='materialize':r=materialize(args.pool,args.id,args.to,args.allow_copy)
  elif args.cmd=='clone-tree':r=clone_tree(args.source,args.to,args.expected_sha256,args.allow_copy)
  elif args.cmd=='resolve':r=resolve_resource(args.key,args.pool,args.id)
  elif args.cmd=='materialize-tree':r=materialize_tree(args.key,args.to,args.allow_copy)
  else:r=verify(args.pool)
  print(json.dumps(r,ensure_ascii=False,indent=2));return 0
 except (ValueError,OSError,sqlite3.Error,KeyError) as e:
  print(json.dumps({'status':'error','error':str(e),'originals_retained':True},ensure_ascii=False),file=sys.stderr);return 1
if __name__=='__main__':raise SystemExit(main())
