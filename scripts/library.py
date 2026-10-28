#!/usr/bin/env python3
"""Review a bounded asset scan, then stage a new reference view. No old-file apply mode."""
import argparse,hashlib,json,os,sqlite3,subprocess,sys
from pathlib import Path
sys.dont_write_bytecode=True
import reuse as rp
import scan
import views
import project_scope as scope
SCHEMA='resource-reuse-library-plan-v1'

def seal(plan):
 return hashlib.sha256(json.dumps({k:v for k,v in plan.items() if k!='plan_sha256'},sort_keys=True,separators=(',',':'),ensure_ascii=True).encode()).hexdigest()

def read_json(value):
 p,s=rp.safe_source(value);result=json.loads(p.read_text())
 if rp.signature(p.stat())!=rp.signature(s):raise ValueError('Input changed while reading')
 return result

def existing_resource(pool,h,size,kind):
 p,d=rp.pool_db(pool)
 try:
  return next((dict(r) for r in d.execute('SELECT * FROM resources WHERE sha256=? AND size=? AND kind=? ORDER BY created_at',(h,size,kind)) if views.reviewed_role(r['role'])),None)
 finally:d.close()

def make_plan(roots,pool,role,license,fclones=None,max_files=1000,max_bytes=536870912):
 if not views.reviewed_role(role) or not license:raise ValueError('Supply the reviewed purpose and permitted-use description')
 main=Path(scope.selection()['project_root']);pool,d=rp.pool_db(pool);d.close()
 roots=[scope.require_path(Path(p).expanduser().absolute()) for p in roots]
 for p in roots:p.relative_to(main)
 files,skips,issues=scan.eligible_files(roots);selected=[];ignored=0
 for raw in sorted(files):
  p=Path(raw);kind=rp.ASSETS.get(p.suffix.lower())
  if kind not in views.ASSET_KINDS:ignored+=1;continue
  p,s=rp.safe_source(p)
  if rp.quarantine_present(p):ignored+=1;continue
  selected.append((p,s,kind))
 if not selected:raise ValueError('No eligible ordinary read-only assets in selected roots')
 if len(selected)>max_files or sum(s.st_size for _,s,_ in selected)>max_bytes:raise ValueError('Asset scan exceeds the requested bounds; choose narrower roots or explicitly raise bounds')
 detected=scan.scan(roots,fclones,selected_paths=[p for p,_,_ in selected])
 if detected['changed_during_scan']:raise ValueError('Sources changed during duplicate scan; retain originals and rescan')
 entries=[];unique={}
 for p,s,kind in selected:
  h=rp.sha_file(p)
  if rp.signature(p.stat())!=rp.signature(s):raise ValueError('Source changed during plan hashing')
  name=views.logical_name(p.relative_to(main).as_posix());match=existing_resource(pool,h,s.st_size,kind)
  entries.append({'path':name,'source':str(p),'signature':list(rp.signature(s)),'sha256':h,'size':s.st_size,'kind':kind,'existing_resource_id':match['id'] if match else None})
  unique[h]=s.st_size
 plan={'schema':SCHEMA,'project_id':scope.selection()['id'],'project_root':str(main),'pool':str(pool),'roots':[str(p) for p in roots],
       'role':role,'license':license,'entries':entries,'summary':{'selected_files':len(entries),'unique_objects':len(unique),'logical_bytes':sum(e['size'] for e in entries),
       'unique_content_bytes':sum(unique.values()),'logical_duplicate_upper_bytes_not_reclaimable':sum(e['size'] for e in entries)-sum(unique.values()),
       'existing_library_matches':sum(e['existing_resource_id'] is not None for e in entries),'detector_groups':detected['duplicate_groups'],'detector':detected['backend'],
       'nonasset_or_quarantined_files_excluded':ignored,'metadata_skips':skips,'issues':issues},'originals_modified':0,
       'limits':'A plan or new view releases no existing space. Equal hashes do not establish purpose or rights. Stage only reviewed assets in a new directory; validate the consumer before any separately authorized old-copy replacement.'}
 plan['plan_sha256']=seal(plan);return plan

def stage_plan(plan,to,read_only_assets=False):
 if not read_only_assets:raise ValueError('Review this plan for read-only asset use first')
 if not isinstance(plan,dict) or plan.get('schema')!=SCHEMA or seal(plan)!=plan.get('plan_sha256'):raise ValueError('Plan fingerprint is invalid')
 if plan['project_id']!=scope.selection()['id'] or plan['project_root']!=scope.selection()['project_root']:raise ValueError('Plan belongs to another project')
 if not views.reviewed_role(plan['role']):raise ValueError('Plan purpose is not reviewed')
 dest=views.view_location(to)
 for raw in plan['roots']:
  root=scope.require_path(raw)
  if dest==root or root in dest.parents:raise ValueError('Stage outside scanned source roots')
 pool,d=rp.pool_db(plan['pool']);d.close()
 # Validate every original before registering anything or creating a view.
 seen=set()
 for e in plan['entries']:
  p,s=rp.safe_source(e['source']);relative=p.relative_to(plan['project_root']).as_posix()
  if e['path']!=relative or relative in seen or e['kind']!=rp.ASSETS.get(p.suffix.lower()) or e['kind'] not in views.ASSET_KINDS:raise ValueError('Plan source/path/type mismatch')
  seen.add(relative);views.logical_name(relative)
  if not any(p==Path(r) or Path(r) in p.parents for r in plan['roots']):raise ValueError('Source lies outside planned roots')
  if list(rp.signature(s))!=e['signature'] or s.st_size!=e['size'] or rp.sha_file(p)!=e['sha256'] or rp.signature(p.stat())!=rp.signature(s):raise ValueError('Planned source changed; rescan before staging')
 if not seen:raise ValueError('Empty plan')
 if dest.exists():
  existing=views.read_index(dest);views.check_view(dest,existing)
  pinned={e['path']:existing['pinned'][e['id']]['sha256'] for e in existing['entries']}
  if (dest/existing['pool']).resolve()!=pool or pinned!={e['path']:e['sha256'] for e in plan['entries']}:raise FileExistsError('Existing view does not match this plan')
  return {**views.verify_view(dest),'status':'existing-identical-view','new_files_created':False,'plan_sha256':plan['plan_sha256'],'source_files_replaced':0,'old_space_released_bytes':0}
 selected={};entries=[]
 for e in plan['entries']:
  key=(e['sha256'],e['kind'])
  if key not in selected:
   match=existing_resource(pool,e['sha256'],e['size'],e['kind'])
   if match:r=rp.resolve_resource(pool=pool,rid=match['id'])
   else:
    # Preserve an unreviewed historical record; explicit new purpose gets new metadata,
    # while the content object remains shared. Logical view names do not change.
    source_name=Path(e['source']).name;p,d=rp.pool_db(pool)
    try:old=d.execute('SELECT role FROM resources WHERE sha256=? AND name=? AND kind=?',(e['sha256'],source_name,e['kind'])).fetchone()
    finally:d.close()
    if old and not views.reviewed_role(old['role']):
     tag=hashlib.sha256((plan['role']+'\0'+plan['license']).encode()).hexdigest()[:12]
     source_name=Path(source_name).stem+'__purpose-'+tag+Path(source_name).suffix
    r=rp.add(pool,e['source'],name=source_name,kind=e['kind'],role=plan['role'],license=plan['license'],expected=e['sha256'])
   if r['sha256']!=e['sha256']:raise ValueError('Registered content differs from the reviewed plan')
   selected[key]=r['id']
  entries.append({'path':e['path'],'id':selected[key]})
 result=views.create_view(pool,entries,dest,True)
 return {**result,'plan_sha256':plan['plan_sha256'],'source_files_replaced':0,'old_space_released_bytes':0}

def write_plan(value,out):
 p=views.view_location(out)
 for raw in value['roots']:
  root=Path(raw)
  if p==root or root in p.parents:raise ValueError('Write the plan outside scanned roots')
 p.parent.mkdir(parents=True,exist_ok=True)
 fd=os.open(p,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
 with os.fdopen(fd,'w') as f:json.dump(value,f,ensure_ascii=False,indent=2)

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--project-root');p.add_argument('--config');sub=p.add_subparsers(dest='cmd',required=True)
 a=sub.add_parser('plan');a.add_argument('--root',action='append',required=True);a.add_argument('--pool',required=True);a.add_argument('--role',required=True);a.add_argument('--license',required=True);a.add_argument('--fclones');a.add_argument('--max-files',type=int,default=1000);a.add_argument('--max-bytes',type=int,default=536870912);a.add_argument('--out',required=True)
 a=sub.add_parser('stage');a.add_argument('--plan',required=True);a.add_argument('--to',required=True);a.add_argument('--read-only-assets',action='store_true')
 a=p.parse_args();scope.configure(a.project_root,a.config)
 try:
  if a.cmd=='plan':
   result=make_plan(a.root,a.pool,a.role,a.license,a.fclones,a.max_files,a.max_bytes);write_plan(result,a.out)
   result={'status':'review-plan-created','plan':a.out,'plan_sha256':result['plan_sha256'],**result['summary'],'originals_modified':0}
  else:result=stage_plan(read_json(a.plan),a.to,a.read_only_assets)
  print(json.dumps(result,ensure_ascii=False,indent=2));return 0
 except (OSError,ValueError,KeyError,TypeError,sqlite3.Error,subprocess.SubprocessError,RuntimeError) as e:
  print(json.dumps({'status':'error','error':str(e),'originals_retained':True},ensure_ascii=False),file=sys.stderr);return 1
if __name__=='__main__':raise SystemExit(main())
