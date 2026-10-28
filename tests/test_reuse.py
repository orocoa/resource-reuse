"""Preserved synthetic artifacts; set RESOURCE_REUSE_TEST_ROOT outside the skill."""
import importlib.util,json,os,stat,sys,tempfile,unittest
from pathlib import Path
from unittest import mock
sys.dont_write_bytecode=True
SKILL=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(SKILL/'scripts'))
import reuse as rp
import scan as scanner
B=Path(os.environ.get('RESOURCE_REUSE_TEST_ROOT') or tempfile.mkdtemp(prefix='resource-reuse-tests-')).resolve()
if SKILL==B or SKILL in B.parents:raise ValueError('Keep generated tests outside the shareable skill')
B.mkdir(parents=True,exist_ok=True);(B/'helper-checks').mkdir(exist_ok=True)

class PoolTests(unittest.TestCase):
 def setUp(self):
  self.root=B/self._testMethodName;self.root.mkdir(exist_ok=False);rp.set_project_root(self.root);self.pool=self.root/'pool';rp.init_pool(self.pool)
  self.src=self.root/'asset.bin';self.src.write_bytes(b'original reusable resource\n'*300);os.chmod(self.src,0o755)
 def test_same_bytes_store_one_object_and_keep_sources(self):
  original=rp.sha_file(self.src);a=rp.add(self.pool,self.src,kind='test',key='test:v1')
  other=self.root/'other.bin';other.write_bytes(self.src.read_bytes());rp.add(self.pool,other,kind='test')
  v=rp.verify(self.pool);self.assertEqual(v['objects_checked'],1);self.assertEqual(v['resources'],2);self.assertTrue(v['verified']);self.assertEqual(rp.sha_file(self.src),original)
 def test_cow_materialization_is_independent_and_reuses_target(self):
  a=rp.add(self.pool,self.src,kind='test');target=self.root/'out.bin';r=rp.materialize(self.pool,a['id'],target)
  self.assertEqual(r['storage'],'apfs-cow');self.assertEqual(stat.S_IMODE(target.stat().st_mode),0o755)
  self.assertNotEqual(target.stat().st_ino,Path(a['object']).stat().st_ino)
  self.assertEqual(rp.materialize(self.pool,a['id'],target)['status'],'existing-identical')
  target.write_bytes(b'edited output');self.assertNotEqual(rp.sha_file(target),a['sha256']);self.assertEqual(rp.sha_file(self.src),a['sha256']);self.assertEqual(rp.sha_file(a['object']),a['sha256'])
 def test_existing_different_target_is_not_overwritten(self):
  a=rp.add(self.pool,self.src);target=self.root/'existing.bin';target.write_bytes(b'keep me')
  with self.assertRaises(FileExistsError):rp.materialize(self.pool,a['id'],target)
  self.assertEqual(target.read_bytes(),b'keep me')
 def test_version_key_conflict_cannot_silently_reuse(self):
  rp.add(self.pool,self.src,key='build:inputs-v1');other=self.root/'new.bin';other.write_bytes(b'different version')
  with self.assertRaises(ValueError):rp.add(self.pool,other,key='build:inputs-v1')
 def test_corrupt_cache_is_rejected_before_destination_creation(self):
  a=rp.add(self.pool,self.src);obj=Path(a['object']);os.chmod(obj,0o600);obj.write_bytes(b'corrupt cache');dest=self.root/'new-output.bin'
  with self.assertRaises(ValueError):rp.materialize(self.pool,a['id'],dest)
  self.assertFalse(dest.exists());self.assertTrue(self.src.exists())
 def test_symlink_sources_and_destination_ancestors_refused(self):
  link=self.root/'linked.bin';link.symlink_to(self.src)
  with self.assertRaises(ValueError):rp.add(self.pool,link)
  a=rp.add(self.pool,self.src);outside=self.root/'outside';outside.mkdir();alias=self.root/'alias';alias.symlink_to(outside)
  with self.assertRaises(ValueError):rp.materialize(self.pool,a['id'],alias/'new.bin')
  self.assertFalse((outside/'new.bin').exists())
 def test_lookup_miss_does_not_create_a_pool(self):
  absent=self.root/'not-created';self.assertEqual(rp.lookup([absent],'absent'),[]);self.assertFalse(absent.exists())
 def test_kind_cannot_escape_pool(self):
  with self.assertRaises(ValueError):rp.add(self.pool,self.src,kind='../../escape')
  self.assertFalse((self.root/'escape').exists())
 def test_tree_copy_keeps_relative_links_and_is_independent(self):
  source=self.root/'runtime';source.mkdir(mode=0o700);(source/'bin').mkdir();(source/'bin/tool').write_bytes(b'complete runtime');os.chmod(source/'bin/tool',0o755);(source/'tool').symlink_to('bin/tool')
  h=rp.tree_digest(rp.tree_inventory(source));dest=self.root/'runtime-copy';r=rp.clone_tree(source,dest,h)
  self.assertTrue(r['source_unchanged']);self.assertEqual(stat.S_IMODE(dest.stat().st_mode),0o700);self.assertEqual(os.readlink(dest/'tool'),'bin/tool');self.assertEqual(stat.S_IMODE((dest/'bin/tool').stat().st_mode),0o755)
  (dest/'bin/tool').write_bytes(b'changed copy');self.assertEqual((source/'bin/tool').read_bytes(),b'complete runtime')
 def test_tree_external_link_rejected_before_copy(self):
  source=self.root/'runtime';source.mkdir();(source/'outside').symlink_to('../asset.bin');dest=self.root/'runtime-copy'
  with self.assertRaises(ValueError):rp.clone_tree(source,dest)
  self.assertFalse(dest.exists())

class ReuseCompletionTests(unittest.TestCase):
 def setUp(self):
  self.root=B/'helper-checks'/self._testMethodName;self.root.mkdir();rp.set_project_root(self.root)
  self.pool=self.root/'pool';rp.init_pool(self.pool)
  self.file=self.root/'asset.dat';self.file.write_bytes(b'reusable bytes'*100)
  self.cfg={'pools':[str(self.pool)],'trees':[]}
 def make_tree(self):
  p=self.root/'runtime';(p/'bin').mkdir(parents=True);(p/'bin/tool').write_bytes(b'locked runtime');os.chmod(p/'bin/tool',0o755)
  h=rp.tree_digest(rp.tree_inventory(p));self.cfg['trees']=[{'name':'runtime-v1','path':str(p),'sha256':h,'reuse_key':'runtime:v1:params-sha'}];return p,h
 def test_resolve_existing_file_returns_same_inode_without_new_copy(self):
  a=rp.add(self.pool,self.file,key='input-v1');st=Path(a['object']).stat()
  r=rp.resolve_resource(key='input-v1',config=self.cfg)
  self.assertTrue(r['verified']);self.assertFalse(r['new_file_created']);self.assertEqual(Path(r['path']).stat().st_ino,st.st_ino)
  self.assertEqual(rp.resolve_resource(pool=self.pool,rid=a['id'],config=self.cfg)['sha256'],a['sha256'])
 def test_resolve_miss_does_not_generate_anything(self):
  before=sorted(str(p) for p in self.root.rglob('*'))
  with self.assertRaises(FileNotFoundError):rp.resolve_resource(key='not-here',config=self.cfg)
  self.assertEqual(before,sorted(str(p) for p in self.root.rglob('*')))
 def test_ambiguous_key_requires_selection(self):
  a=rp.add(self.pool,self.file,key='same-key');other=self.root/'other';rp.init_pool(other);rp.add(other,self.file,key='same-key');self.cfg['pools'].append(str(other))
  with self.assertRaises(ValueError):rp.resolve_resource(key='same-key',config=self.cfg)
  self.assertTrue(rp.resolve_resource(key='same-key',pool=self.pool,config=self.cfg)['verified'])
 def test_corrupt_file_cannot_be_resolved(self):
  a=rp.add(self.pool,self.file,key='input-v1');p=Path(a['object']);os.chmod(p,0o600);p.write_bytes(b'changed')
  with self.assertRaises(ValueError):rp.resolve_resource(key='input-v1',config=self.cfg)
  self.assertEqual(self.file.read_bytes(),b'reusable bytes'*100)
 def test_tree_second_use_keeps_inode_and_mtime(self):
  p,h=self.make_tree();dest=self.root/'isolated';first=rp.materialize_tree('runtime:v1:params-sha',dest,config=self.cfg);st=(dest/'bin/tool').stat()
  r=rp.materialize_tree('runtime:v1:params-sha',dest,config=self.cfg)
  self.assertEqual(first['storage'],'apfs-cow');self.assertEqual(r['status'],'existing-identical-tree');self.assertFalse(r['new_file_created'])
  now=(dest/'bin/tool').stat();self.assertEqual((st.st_ino,st.st_mtime_ns),(now.st_ino,now.st_mtime_ns))
  (dest/'bin/tool').write_bytes(b'edit isolated');self.assertEqual((p/'bin/tool').read_bytes(),b'locked runtime')
 def test_different_existing_tree_is_preserved(self):
  self.make_tree();dest=self.root/'existing';dest.mkdir();(dest/'own.txt').write_text('retain')
  with self.assertRaises(FileExistsError):rp.materialize_tree('runtime:v1:params-sha',dest,config=self.cfg)
  self.assertEqual((dest/'own.txt').read_text(),'retain')
 def test_changed_runtime_prevents_materialization(self):
  p,h=self.make_tree();(p/'bin/tool').write_bytes(b'wrong runtime');dest=self.root/'absent'
  with self.assertRaises(ValueError):rp.materialize_tree('runtime:v1:params-sha',dest,config=self.cfg)
  self.assertFalse(dest.exists())
 def test_tree_destination_inside_pool_is_rejected(self):
  self.make_tree()
  with self.assertRaises(ValueError):rp.materialize_tree('runtime:v1:params-sha',self.pool/'not-an-object',config=self.cfg)
  self.assertFalse((self.pool/'not-an-object').exists())
 def test_file_key_cannot_be_used_as_runtime_tree(self):
  rp.add(self.pool,self.file,key='file-v1')
  with self.assertRaises(ValueError):rp.materialize_tree('file-v1',self.root/'new',config=self.cfg)

class PortableTests(unittest.TestCase):
 def setUp(self):
  self.root=B/self._testMethodName;self.root.mkdir();rp.set_project_root(self.root);self.pool=self.root/'pool';rp.init_pool(self.pool)
  self.src=self.root/'source.dat';self.src.write_bytes(b'ordered deterministic input')
 def test_two_recipe_keys_share_one_resource_and_object(self):
  a=rp.add(self.pool,self.src,key='recipe-A');b=rp.add(self.pool,self.src,key='recipe-B')
  self.assertEqual(a['id'],b['id']);self.assertEqual(rp.verify(self.pool)['objects_checked'],1)
  cfg={'pools':[str(self.pool)],'trees':[]}
  for key in ['recipe-A','recipe-B']:
   self.assertEqual(len(rp.lookup([self.pool],key=key)),1)
   self.assertEqual(rp.lookup([self.pool],key=key)[0]['reuse_key'],key)
   self.assertEqual(rp.resolve_resource(key=key,config=cfg)['reuse_key'],key)
   self.assertEqual(rp.resolve_resource(key=key,config=cfg)['sha256'],a['sha256'])
 def test_recipe_is_path_independent_and_parameter_sensitive(self):
  other=self.root/'renamed.dat';other.write_bytes(self.src.read_bytes())
  base=rp.recipe_key([self.src],'tool','v1','platform',{'size':10})['reuse_key']
  self.assertEqual(base,rp.recipe_key([other],'tool','v1','platform',{'size':10})['reuse_key'])
  for tool,version,platform,params in [('different','v1','platform',{'size':10}),('tool','v2','platform',{'size':10}),('tool','v1','other',{'size':10}),('tool','v1','platform',{'size':11})]:
   self.assertNotEqual(base,rp.recipe_key([other],tool,version,platform,params)['reuse_key'])
 def test_recipe_preserves_input_order(self):
  other=self.root/'different.dat';other.write_bytes(b'different input')
  a=rp.recipe_key([self.src,other],'t','1','p',{})['reuse_key'];b=rp.recipe_key([other,self.src],'t','1','p',{})['reuse_key'];self.assertNotEqual(a,b)
 def test_cache_internal_symlink_cannot_write_outside_pool(self):
  outside=self.root/'outside';outside.mkdir();h=rp.sha_file(self.src);(self.pool/'objects'/h[:2]).symlink_to(outside)
  with self.assertRaises(ValueError):rp.add(self.pool,self.src)
  self.assertEqual(list(outside.iterdir()),[]);self.assertEqual(self.src.read_bytes(),b'ordered deterministic input')
 def test_unsupported_cow_requires_explicit_copy(self):
  dest=self.root/'new.dat'
  with mock.patch.object(rp.sys,'platform','unsupported'):
   with self.assertRaises(ValueError):rp.cow_clone(self.src,dest)
   self.assertFalse(dest.exists());self.assertEqual(rp.cow_clone(self.src,dest,True),'physical-copy-explicit')
  self.assertEqual(dest.read_bytes(),self.src.read_bytes())
 def test_external_config_cli_and_key_aliases(self):
  import subprocess
  a=rp.add(self.pool,self.src,key='alias');cfg=self.root/'user-config.json';cfg.write_text(json.dumps({'pools':[str(self.pool)],'trees':[]}))
  r=json.loads(subprocess.check_output([sys.executable,'-B',str(SKILL/'scripts/reuse.py'),'--project-root',str(self.root),'--config',str(cfg),'resolve','--key','alias']))
  self.assertTrue(r['verified']);self.assertEqual(r['sha256'],a['sha256'])
 def test_real_scan_excludes_managed_secrets_cloud_and_links(self):
  binary=os.environ.get('FCLONES_BINARY')
  if not binary:self.skipTest('Set FCLONES_BINARY for actual backend integration')
  root=self.root/'inputs';root.mkdir();(root/'a.txt').write_bytes(b'duplicate');(root/'b.txt').write_bytes(b'duplicate');(root/'linked').symlink_to('a.txt');(root/'odd\nname.txt').write_bytes(b'duplicate');(root/'pending.icloud').write_bytes(b'duplicate');(root/'.env').write_bytes(b'duplicate')
  (root/'node_modules').mkdir();(root/'node_modules/keep.txt').write_bytes(b'duplicate');(root/'alias-hardlink').hardlink_to(root/'a.txt') if hasattr(Path,'hardlink_to') else os.link(root/'a.txt',root/'alias-hardlink')
  before={str(p):rp.signature(p.lstat()) for p in root.rglob('*')}
  result=scanner.scan([root],binary)
  self.assertEqual(result['duplicate_groups'],1);self.assertEqual(result['groups'][0]['independent_inodes'],2);self.assertEqual(result['logical_duplicate_upper_bytes'],len(b'duplicate'))
  self.assertGreaterEqual(result['skips']['managed-or-secret-directory'],1);self.assertGreaterEqual(result['skips']['cloud-file'],1);self.assertGreaterEqual(result['skips']['newline-in-path-not-supported'],1)
  self.assertEqual(before,{str(p):rp.signature(p.lstat()) for p in root.rglob('*')});self.assertFalse(result['changed_during_scan'])
 def test_real_full_hash_distinguishes_same_prefix_and_suffix(self):
  binary=os.environ.get('FCLONES_BINARY')
  if not binary:self.skipTest('Set FCLONES_BINARY for actual backend integration')
  root=self.root/'inputs';root.mkdir()
  (root/'first').write_bytes(b'A'*20000+b'B'*50000+b'Z'*20000);(root/'second').write_bytes(b'A'*20000+b'C'*50000+b'Z'*20000)
  self.assertEqual(scanner.scan([root],binary)['duplicate_groups'],0)
 def test_missing_scanner_never_falls_back_or_mutates(self):
  with mock.patch.object(scanner.shutil,'which',return_value=None):
   with self.assertRaises(FileNotFoundError):scanner.scan([self.root])
  self.assertEqual(self.src.read_bytes(),b'ordered deterministic input')

class ProjectScopeTests(unittest.TestCase):
 def setUp(self):
  self.root=B/self._testMethodName;self.root.mkdir();self.a=self.root/'project-a';self.b=self.root/'project-b';self.a.mkdir();self.b.mkdir()
  self.pa=self.a/'shared-resources';self.pb=self.b/'shared-resources'
  rp.scope.configure(self.a);rp.init_pool(self.pa)
  rp.scope.configure(self.b);rp.init_pool(self.pb)
  self.fa=self.a/'asset.txt';self.fb=self.b/'asset.txt';self.fa.write_bytes(b'identical project content');self.fb.write_bytes(b'identical project content')
  rp.scope.configure(self.a)
 def test_foreign_pool_lookup_is_rejected(self):
  with self.assertRaises(ValueError):rp.lookup([self.pb],query='asset')
 def test_foreign_source_cannot_be_added(self):
  with self.assertRaises(ValueError):rp.add(self.pa,self.fb)
  self.assertEqual(rp.verify(self.pa)['resources'],0)
 def test_foreign_target_cannot_be_materialized(self):
  a=rp.add(self.pa,self.fa)
  with self.assertRaises(ValueError):rp.materialize(self.pa,a['id'],self.b/'new.txt')
  self.assertFalse((self.b/'new.txt').exists())
 def test_foreign_root_cannot_be_laundered_through_source_alias(self):
  cfg=self.root/'bad-alias-config.json';cfg.write_text(json.dumps({'project_root':str(self.a),'project_id':rp.scope.identifier(self.a),'pools':[str(self.pa)],'source_roots':[str(self.b)]}))
  rp.scope.configure(self.a,cfg)
  with self.assertRaises(ValueError):rp.add(self.pa,self.fb)
 def test_identical_inputs_have_distinct_project_recipe_keys(self):
  a=rp.recipe_key([self.fa],'tool','1','platform',{})['reuse_key'];rp.scope.configure(self.b)
  b=rp.recipe_key([self.fb],'tool','1','platform',{})['reuse_key'];self.assertNotEqual(a,b)
 def test_project_registry_never_combines_content_lookups(self):
  rp.scope.configure(self.b);rp.add(self.pb,self.fb,key='only-in-b')
  cfg=self.root/'registry.json';cfg.write_text(json.dumps({'projects':[{'id':rp.scope.identifier(self.a),'root':str(self.a),'pools':[str(self.pa)]},{'id':rp.scope.identifier(self.b),'root':str(self.b),'pools':[str(self.pb)]}]}))
  rp.scope.configure(self.a,cfg);self.assertEqual(rp.configured_pools(),[str(self.pa)]);self.assertEqual(rp.lookup(rp.configured_pools(),key='only-in-b'),[])
 def test_nested_project_marker_blocks_parent_without_global_registry(self):
  child=self.a/'child';child.mkdir();cp=child/'shared-resources';rp.scope.configure(child);rp.init_pool(cp);f=child/'asset.txt';f.write_text('child')
  rp.scope.configure(self.a)
  with self.assertRaises(ValueError):rp.add(self.pa,f)
 def test_legacy_unicode_pool_keeps_project_boundary(self):
  child=self.a/'legacy-child';child.mkdir();pool=child/'\u5171\u4eab\u8d44\u6e90';rp.scope.configure(child);rp.init_pool(pool)
  asset=child/'\u56fe\u7247.svg';asset.write_text('<svg/>');rp.scope.configure(self.a)
  with self.assertRaises(ValueError):rp.add(self.pa,asset)
  rp.scope.configure(child);r=rp.add(pool,asset,kind='image',role='reviewed-test');self.assertTrue(rp.resolve_resource(pool=pool,rid=r['id'])['verified'])
 def test_default_english_pool_is_discovered_without_registry(self):
  rp.add(self.pa,self.fa,role='reviewed-test');rp.scope.configure()
  from unittest.mock import patch
  with patch.object(rp.scope.Path,'cwd',return_value=self.a):
   selected=rp.configuration();self.assertEqual(selected['project_root'],str(self.a));self.assertEqual(selected['pools'],[str(self.pa)])
 def test_project_tree_cannot_be_cloned_into_other_project(self):
  runtime=self.a/'runtime';runtime.mkdir();(runtime/'data').write_text('locked')
  with self.assertRaises(ValueError):rp.clone_tree(runtime,self.b/'runtime')
  self.assertFalse((self.b/'runtime').exists())
 def test_same_bytes_still_have_independent_project_objects(self):
  a=rp.add(self.pa,self.fa);rp.scope.configure(self.b);b=rp.add(self.pb,self.fb)
  self.assertEqual(a['sha256'],b['sha256']);self.assertNotEqual(Path(a['object']).stat().st_ino,Path(b['object']).stat().st_ino)
 def test_retired_recovery_data_is_not_reusable(self):
  archive=self.a/'old-cache';archive.mkdir();(archive/'.resource-reuse-retired.json').write_text('{}');f=archive/'asset.txt';f.write_text('keep')
  with self.assertRaises(ValueError):rp.add(self.pa,f)
  self.assertEqual(f.read_text(),'keep')
 def test_scan_rejects_mixed_project_roots(self):
  with self.assertRaises(ValueError):scanner.eligible_files([self.a,self.b])
 def test_scan_report_cannot_be_written_into_another_project(self):
  import subprocess
  out=self.b/'report.json'
  p=subprocess.run([sys.executable,'-B',str(SKILL/'scripts/scan.py'),'--project-root',str(self.a),'--root',str(self.a),'--out',str(out),'--fclones','not-executed'],capture_output=True,text=True)
  self.assertNotEqual(p.returncode,0);self.assertFalse(out.exists());self.assertIn('project',p.stderr)
 def test_unresolved_context_does_not_fall_back_to_global(self):
  from unittest.mock import patch
  rp.scope.configure()
  with patch.object(rp.scope.Path,'cwd',return_value=Path('/__resource_reuse_unowned_test__')):
   with self.assertRaises(ValueError):rp.configuration()

if __name__=='__main__':unittest.main(verbosity=2)
