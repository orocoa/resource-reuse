"""Project ownership, never a global content search. No bundled user registry."""
import hashlib,json,os
from pathlib import Path
ROOT=None
CONFIG=None
_cache=None
POOL_DIR_NAMES=('shared-resources','\u5171\u4eab\u8d44\u6e90')

def norm(path):return Path(os.path.abspath(os.path.expanduser(str(path))))
def within(path,root):
 p=norm(path);r=norm(root);return p==r or r in p.parents
def configure(project_root=None,config=None):
 global ROOT,CONFIG,_cache
 ROOT=norm(project_root) if project_root else None;CONFIG=config;_cache=None
def set_root(root):
 global ROOT
 ROOT=norm(root) if root else None
def raw_config():
 global _cache
 path=CONFIG or os.environ.get('RESOURCE_REUSE_CONFIG')
 if not path:return {}
 p=norm(path);s=p.stat();key=(str(p),s.st_mtime_ns,s.st_size)
 if _cache and _cache[0]==key:return _cache[1]
 d=json.loads(p.read_text())
 if not isinstance(d,dict):raise ValueError('Project configuration must be an object')
 _cache=(key,d);return d
def identifier(root):return 'project:'+hashlib.sha256(str(norm(root)).encode()).hexdigest()[:24]
def records(raw):
 if 'projects' in raw:
  if not isinstance(raw['projects'],list):raise ValueError('projects must be a list')
  return raw['projects']
 if raw.get('project_root'):return [{**raw,'root':raw['project_root'],'id':raw.get('project_id') or identifier(raw['project_root'])}]
 return []
def source_roots(project):return [project['root'],*project.get('aliases',[]),*project.get('source_roots',[])]
def owner(path,raw=None):
 candidates=[]
 for project in records(raw if raw is not None else raw_config()):
  for root in source_roots(project):
   if within(path,root):candidates.append((len(norm(root).parts),3 if norm(root)==norm(project['root']) else 1,project))
 # A neighbouring project remains a boundary even without a registry.
 p=norm(path)
 for parent in [p,*p.parents]:
  if candidates and len(parent.parts)<max(x[0] for x in candidates):break
  for pool_name in POOL_DIR_NAMES:
   marker=parent/pool_name/'resource-pool.json'
   if marker.is_file() and not marker.is_symlink():
    d=json.loads(marker.read_text())
    if d.get('project_root'):
     record={'id':d.get('project_id') or identifier(d['project_root']),'root':d['project_root'],'pools':[str(marker.parent)],'trees':[]}
     local=marker.parent/'project-config.json'
     if local.is_file() and not local.is_symlink():
      extra=json.loads(local.read_text())
      if extra.get('project_id')==record['id'] and norm(extra.get('project_root',''))==norm(record['root']):
       record.update({k:extra[k] for k in ['source_roots','aliases','trees'] if k in extra})
     candidates.append((len(parent.parts),4,record))
 return max(candidates,key=lambda x:(x[0],x[1]))[2] if candidates else None
def selection():
 raw=raw_config();chosen=ROOT
 project=owner(chosen or Path.cwd(),raw)
 if chosen:
  # An explicit nested root defines an independent scope, not access to its parent.
  if project and norm(chosen) not in [norm(project['root']),*[norm(x) for x in project.get('aliases',[])]]:
   project=None
  if project is None:project={'id':identifier(chosen),'root':str(chosen)}
 elif project is None:raise ValueError('Project is unresolved; supply --project-root. Global content lookup is disabled')
 result={**project,'project_root':str(norm(project['root']))}
 result['id']=project.get('id') or identifier(project['root'])
 if not records(raw):
  result.update({k:raw[k] for k in ['pools','trees','source_roots','aliases'] if k in raw})
 result.setdefault('pools',[]);result.setdefault('trees',[])
 return result
def require_path(path,write=False):
 project=selection();p=norm(path);candidate=owner(p)
 for parent in [p,*p.parents]:
  if (parent/'.resource-reuse-retired.json').is_file():raise ValueError('Recovery/unassigned cache is retired from resource reuse')
 if candidate and (candidate.get('id') or identifier(candidate['root']))!=project['id']:
  if not (within(project['project_root'],candidate['root']) and within(p,project['project_root'])):
   raise ValueError('Cross-project resource access refused')
 roots=[project['project_root'],*project.get('aliases',[])] if write else source_roots(project)
 if not any(within(p,r) for r in roots):raise ValueError('Path is outside the selected project boundary')
 return p
def assert_pool(marker,pool):
 project=selection();require_path(pool,write=True)
 if marker.get('project_id')!=project['id'] or norm(marker.get('project_root',''))!=norm(project['project_root']):
  raise ValueError('Pool belongs to a different project or lacks verified ownership')
