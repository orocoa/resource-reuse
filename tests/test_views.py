"""Reference views use synthetic assets only; preserve every test artifact."""
import json,os,stat,subprocess,sys,tempfile,unittest
from pathlib import Path
sys.dont_write_bytecode=True
SKILL=Path(__file__).resolve().parents[1];sys.path.insert(0,str(SKILL/'scripts'))
import reuse as rp
import views as v
import scan
B=Path(os.environ.get('RESOURCE_VIEW_TEST_ROOT') or tempfile.mkdtemp(prefix='resource-view-tests-')).resolve();B.mkdir(parents=True,exist_ok=True)
if SKILL==B or SKILL in B.parents:raise ValueError('Keep test artifacts outside the skill')

class ReferenceViewTests(unittest.TestCase):
 def setUp(self):
  self.root=B/self._testMethodName;self.root.mkdir();rp.scope.configure(self.root);self.pool=self.root/'shared-resources';rp.init_pool(self.pool)
  self.src=self.root/'asset.png';self.src.write_bytes(b'synthetic read-only content'*100)
  self.resource=rp.add(self.pool,self.src,role='reviewed-local-test',license='synthetic',kind='image')
  self.entries=[{'path':'images/one.png','id':self.resource['id']},{'path':'images/two.png','id':self.resource['id']}]
  self.dest=self.root/'new-view'
 def create(self):return v.create_view(self.pool,self.entries,self.dest,True)
 def test_one_object_multiple_names_no_payload_copy_and_original_retained(self):
  before=rp.signature(self.src.stat());r=self.create()
  self.assertEqual(r['unique_content_objects'],1);self.assertEqual(r['entries'],2);self.assertEqual(r['view_regular_payload_bytes'],0);self.assertEqual(r['payload_bytes_copied'],0)
  self.assertEqual((self.dest/'images/one.png').read_bytes(),self.src.read_bytes());self.assertEqual((self.dest/'images/one.png').resolve(),Path(self.resource['object']))
  self.assertEqual(rp.signature(self.src.stat()),before)
 def test_second_request_keeps_view_inode_and_mtime(self):
  self.create();before={str(p):rp.signature(p.lstat()) for p in self.dest.rglob('*')}
  r=self.create();self.assertEqual(r['status'],'existing-identical-view');self.assertFalse(r['new_files_created'])
  self.assertEqual(before,{str(p):rp.signature(p.lstat()) for p in self.dest.rglob('*')})
 def test_multiple_views_refer_to_same_object(self):
  self.create();second=self.root/'another-view';v.create_view(self.pool,self.entries,second,True)
  self.assertEqual((second/'images/two.png').stat().st_ino,(self.dest/'images/one.png').stat().st_ino)
  self.assertEqual(rp.verify(self.pool)['objects_checked'],1)
 def test_duplicate_scan_skips_private_reference_view_indexes(self):
  self.create();files,skips,issues=scan.eligible_files([self.root])
  self.assertTrue(all(self.dest not in Path(p).parents for p in files));self.assertGreaterEqual(skips['managed-or-secret-directory'],2)
  self.assertIn(str(self.src),files)
 def test_explicit_read_only_use_is_required(self):
  with self.assertRaises(ValueError):v.create_view(self.pool,self.entries,self.dest)
  self.assertFalse(self.dest.exists())
 def test_editable_materialization_does_not_change_pool_or_source(self):
  self.create();r=v.resolve_view(self.dest,'images/one.png');target=self.root/'editable.png';rp.materialize(r['pool'],r['id'],target)
  target.write_bytes(b'edited independent result')
  self.assertEqual((self.dest/'images/one.png').read_bytes(),self.src.read_bytes());self.assertNotEqual(target.read_bytes(),self.src.read_bytes())
 def test_unreviewed_purpose_refused(self):
  a=rp.add(self.pool,self.src,name='unreviewed.png',role='needs-review')
  with self.assertRaises(ValueError):v.create_view(self.pool,[{'path':'a.png','id':a['id']}],self.dest,True)
  self.assertFalse(self.dest.exists())
 def test_source_code_is_not_shared_as_editable_view(self):
  a=rp.add(self.pool,self.src,name='source.py',kind='other',role='test')
  with self.assertRaises(ValueError):v.create_view(self.pool,[{'path':'source.py','id':a['id']}],self.dest,True)
 def test_writable_pool_object_refused_without_modifying_original(self):
  os.chmod(self.resource['object'],0o600)
  with self.assertRaises(ValueError):self.create()
  self.assertFalse(self.dest.exists());self.assertTrue(self.src.exists())
 def test_corrupt_object_refused_before_any_view_creation(self):
  p=Path(self.resource['object']);os.chmod(p,0o600);p.write_bytes(b'changed');os.chmod(p,0o400)
  with self.assertRaises(ValueError):self.create()
  self.assertFalse(self.dest.exists())
 def test_existing_unrelated_folder_is_retained(self):
  self.dest.mkdir();(self.dest/'keep.txt').write_text('keep')
  with self.assertRaises((OSError,ValueError)):self.create()
  self.assertEqual((self.dest/'keep.txt').read_text(),'keep')
 def test_changed_requested_entry_does_not_replace_existing_view(self):
  self.create();self.entries[0]['path']='different.png'
  with self.assertRaises(FileExistsError):self.create()
  self.assertFalse((self.dest/'different.png').exists());self.assertTrue((self.dest/'images/one.png').is_symlink())
 def test_unsafe_case_and_file_directory_collisions_refused(self):
  for names in [('a.png','A.png'),('a','a/b.png'),('../escape.png',),('/absolute.png',),('node_modules/a.png',),('NODE_MODULES/a.png',),('.resource-view.json',),('.RESOURCE-VIEW.JSON',),('e\u0301.png','é.png')]:
   with self.subTest(names=names),self.assertRaises(ValueError):v.create_view(self.pool,[{'path':p,'id':self.resource['id']} for p in names],self.dest,True)
  self.assertFalse(self.dest.exists())
 def test_changed_link_is_rejected_without_following_it(self):
  self.create();link=self.dest/'images/one.png';link.unlink();link.symlink_to(self.root/'absent')
  with self.assertRaises(ValueError):v.verify_view(self.dest)
  self.assertFalse((self.root/'absent').exists())
 def test_resolve_checks_selected_object_without_reading_unrelated_content(self):
  from unittest.mock import patch
  other=self.root/'other.png';other.write_bytes(b'other asset')
  a=rp.add(self.pool,other,role='reviewed-test',kind='image');self.entries.append({'path':'other.png','id':a['id']});self.create()
  called=[];original=rp.resolve_resource
  def selected(*args,**kwargs):called.append(kwargs['rid']);return original(*args,**kwargs)
  with patch.object(rp,'resolve_resource',side_effect=selected):self.assertTrue(v.resolve_view(self.dest,'other.png')['verified'])
  self.assertEqual(called,[a['id']])
 def test_unexpected_material_in_view_is_not_deleted(self):
  self.create();extra=self.dest/'notes.txt';extra.write_text('keep my note')
  with self.assertRaises(ValueError):v.verify_view(self.dest)
  self.assertEqual(extra.read_text(),'keep my note')
 def test_foreign_project_pool_and_destination_refused(self):
  foreign=B/(self._testMethodName+'-foreign');foreign.mkdir();rp.scope.configure(foreign);other=foreign/'shared-resources';rp.init_pool(other);rp.scope.configure(self.root)
  with self.assertRaises(ValueError):v.create_view(other,self.entries,self.dest,True)
  with self.assertRaises(ValueError):v.create_view(self.pool,self.entries,foreign/'new-view',True)
  self.assertFalse(self.dest.exists());self.assertFalse((foreign/'new-view').exists())
 def test_foreign_pool_in_tampered_index_refused(self):
  self.create();foreign=B/(self._testMethodName+'-foreign');foreign.mkdir();rp.scope.configure(foreign);other=foreign/'shared-resources';rp.init_pool(other);rp.scope.configure(self.root)
  index=json.loads((self.dest/v.INDEX).read_text());index['pool']=os.path.relpath(other,self.dest);(self.dest/v.INDEX).write_text(json.dumps(index))
  with self.assertRaises(ValueError):v.verify_view(self.dest)
 def test_cli_create_resolve_and_repeated_request(self):
  spec=self.root/'view-spec.json';spec.write_text(json.dumps({'entries':self.entries}))
  base=[sys.executable,'-B',str(SKILL/'scripts/views.py'),'--project-root',str(self.root)]
  command=base+['create','--pool',str(self.pool),'--manifest',str(spec),'--to',str(self.dest),'--read-only-assets']
  self.assertEqual(json.loads(subprocess.check_output(command))['status'],'reference-view-created')
  r=json.loads(subprocess.check_output(base+['resolve','--view',str(self.dest),'--path','images/two.png']));self.assertTrue(r['verified'])
  self.assertEqual(json.loads(subprocess.check_output(command))['status'],'existing-identical-view')
 def test_fclones_to_pool_to_reference_view_full_flow(self):
  backend=os.environ.get('FCLONES_BINARY')
  if not backend:self.skipTest('Set FCLONES_BINARY for actual detector integration')
  folder=self.root/'inputs';folder.mkdir();a=folder/'same-a.png';b=folder/'same-b.png';a.write_bytes(b'exact same synthetic bytes');b.write_bytes(a.read_bytes())
  original={str(p):rp.signature(p.stat()) for p in (a,b)};report=scan.scan([folder],backend)
  self.assertEqual(report['duplicate_groups'],1)
  registered=[rp.add(self.pool,Path(p),role='reviewed-local-test',license='synthetic') for p in report['groups'][0]['paths']]
  entries=[{'path':Path(p).name,'id':r['id']} for p,r in zip(report['groups'][0]['paths'],registered)]
  result=v.create_view(self.pool,entries,self.dest,True)
  self.assertEqual(result['unique_content_objects'],1);self.assertEqual(result['view_regular_payload_bytes'],0)
  self.assertEqual(original,{str(p):rp.signature(p.stat()) for p in (a,b)})

if __name__=='__main__':unittest.main(verbosity=2)
