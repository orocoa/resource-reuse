"""Batch planning, consumer handoff and standalone export, using retained fixtures."""
import json,os,subprocess,sys,tempfile,unittest
from pathlib import Path
sys.dont_write_bytecode=True
SKILL=Path(__file__).resolve().parents[1];sys.path.insert(0,str(SKILL/'scripts'))
import reuse as rp
import views
import library
B=Path(os.environ.get('RESOURCE_LIBRARY_TEST_ROOT') or tempfile.mkdtemp(prefix='resource-library-tests-')).resolve();B.mkdir(parents=True,exist_ok=True)
if SKILL==B or SKILL in B.parents:raise ValueError('Tests belong outside the skill')

class LibraryWorkflowTests(unittest.TestCase):
 def setUp(self):
  self.root=B/self._testMethodName;self.root.mkdir();rp.scope.configure(self.root);self.pool=self.root/'shared-resources';rp.init_pool(self.pool)
  self.assets=self.root/'assets';self.assets.mkdir()
  for name,data in [('a.svg',b'<svg/>'),('b.svg',b'<svg/>'),('c.png',b'synthetic image')]:(self.assets/name).write_bytes(data)
  (self.assets/'source.py').write_text('source remains outside the asset library')
  self.dest=self.root/'new-view';self.backend=os.environ.get('FCLONES_BINARY')
 def plan(self):
  if not self.backend:self.skipTest('Set FCLONES_BINARY to exercise the actual duplicate detector')
  return library.make_plan([self.assets],self.pool,'reviewed-local-test','synthetic',self.backend)
 def stage(self):return library.stage_plan(self.plan(),self.dest,True)
 def test_scan_plan_register_and_repeat_without_new_payload(self):
  before={str(p):rp.signature(p.stat()) for p in self.assets.iterdir()};plan=self.plan()
  self.assertEqual(plan['summary']['selected_files'],3);self.assertEqual(plan['summary']['unique_objects'],2);self.assertEqual(plan['summary']['detector_groups'],1)
  r=library.stage_plan(plan,self.dest,True);self.assertEqual(r['payload_bytes_copied'],0);self.assertEqual(rp.verify(self.pool)['objects_checked'],2)
  snapshot={str(p):rp.signature(p.lstat()) for p in self.dest.rglob('*')};self.assertEqual(library.stage_plan(plan,self.dest,True)['status'],'existing-identical-view')
  self.assertEqual(snapshot,{str(p):rp.signature(p.lstat()) for p in self.dest.rglob('*')});self.assertEqual(before,{str(p):rp.signature(p.stat()) for p in self.assets.iterdir()})
 def test_changed_source_refuses_before_pool_or_view_writes(self):
  p=self.plan();(self.assets/'a.svg').write_bytes(b'changed original')
  with self.assertRaises(ValueError):library.stage_plan(p,self.dest,True)
  self.assertEqual(rp.verify(self.pool)['resources'],0);self.assertFalse(self.dest.exists())
 def test_tampered_plan_refused(self):
  p=self.plan();p['entries'][0]['sha256']='0'*64
  with self.assertRaises(ValueError):library.stage_plan(p,self.dest,True)
  self.assertFalse(self.dest.exists())
 def test_scan_bounds_stop_before_registering(self):
  with self.assertRaises(ValueError):library.make_plan([self.assets],self.pool,'reviewed-test','synthetic',self.backend,max_files=1)
  self.assertEqual(rp.verify(self.pool)['resources'],0)
 def test_foreign_roots_and_foreign_plan_rejected(self):
  p=self.plan();foreign=B/(self._testMethodName+'-other');foreign.mkdir();rp.scope.configure(foreign);other=foreign/'shared-resources';rp.init_pool(other)
  with self.assertRaises(ValueError):library.make_plan([self.assets],other,'reviewed-test','synthetic',self.backend)
  with self.assertRaises(ValueError):library.stage_plan(p,foreign/'view',True)
 def test_unreviewed_historical_role_is_not_accepted(self):
  for role in ('needs-review','historical-resource-needs-review','unreviewed-import','unassigned',''):
   self.assertFalse(views.reviewed_role(role))
  r=rp.add(self.pool,self.assets/'a.svg',role='historical-resource-needs-review')
  with self.assertRaises(ValueError):views.create_view(self.pool,[{'path':'a.svg','id':r['id']}],self.dest,True)
 def test_explicit_new_purpose_preserves_unreviewed_history_record(self):
  old=rp.add(self.pool,self.assets/'a.svg',role='historical-resource-needs-review');self.stage()
  p,d=rp.pool_db(self.pool)
  try:self.assertEqual(d.execute('SELECT role FROM resources WHERE id=?',(old['id'],)).fetchone()[0],'historical-resource-needs-review')
  finally:d.close()
  self.assertTrue(views.resolve_view(self.dest,'assets/a.svg')['verified']);self.assertEqual(rp.verify(self.pool)['objects_checked'],2)
 def test_existing_different_target_is_retained_before_registration(self):
  p=self.plan();self.dest.mkdir();(self.dest/'keep.txt').write_text('retain')
  with self.assertRaises((OSError,ValueError)):library.stage_plan(p,self.dest,True)
  self.assertEqual(rp.verify(self.pool)['resources'],0);self.assertEqual((self.dest/'keep.txt').read_text(),'retain')
 def test_export_contains_independent_regular_files_and_is_idempotent(self):
  self.stage();dest=self.root/'self-contained';r=views.export_view(self.dest,dest)
  self.assertEqual(r['files'],3);self.assertEqual(r['symbolic_links'],0)
  self.assertTrue(all(not p.is_symlink() for p in dest.rglob('*')))
  before={str(p):rp.signature(p.stat()) for p in dest.rglob('*')};self.assertEqual(views.export_view(self.dest,dest)['status'],'existing-identical-export')
  self.assertEqual(before,{str(p):rp.signature(p.stat()) for p in dest.rglob('*')})
  (dest/'assets/a.svg').write_bytes(b'edit export');self.assertEqual((self.dest/'assets/a.svg').read_bytes(),b'<svg/>');self.assertEqual((self.assets/'a.svg').read_bytes(),b'<svg/>')
 def test_export_refuses_changed_existing_folder_without_overwrite(self):
  self.stage();dest=self.root/'self-contained';dest.mkdir();(dest/'notes.txt').write_text('retain')
  with self.assertRaises(FileExistsError):views.export_view(self.dest,dest)
  self.assertEqual((dest/'notes.txt').read_text(),'retain')
 def test_export_refuses_foreign_project_and_nested_pool(self):
  self.stage();foreign=B/(self._testMethodName+'-other');foreign.mkdir();rp.scope.configure(foreign);rp.init_pool(foreign/'shared-resources');rp.scope.configure(self.root)
  for target in (foreign/'export',self.pool/'export',self.dest/'export'):
   with self.assertRaises(ValueError):views.export_view(self.dest,target)
   self.assertFalse(target.exists())
 def test_plan_cannot_be_written_inside_scanned_sources(self):
  p=self.plan()
  with self.assertRaises(ValueError):library.write_plan(p,self.assets/'plan.json')
  self.assertFalse((self.assets/'plan.json').exists())
 def test_generic_cli_plan_stage_export(self):
  if not self.backend:self.skipTest('Set FCLONES_BINARY')
  plan=self.root/'review-plan.json';base=[sys.executable,'-B',str(SKILL/'scripts/library.py'),'--project-root',str(self.root)]
  r=json.loads(subprocess.check_output(base+['plan','--root',str(self.assets),'--pool',str(self.pool),'--role','reviewed-test','--license','synthetic','--fclones',self.backend,'--out',str(plan)]));self.assertEqual(r['selected_files'],3)
  self.assertEqual(json.loads(subprocess.check_output(base+['stage','--plan',str(plan),'--to',str(self.dest),'--read-only-assets']))['source_files_replaced'],0)
  output=self.root/'export';r=json.loads(subprocess.check_output([sys.executable,'-B',str(SKILL/'scripts/views.py'),'--project-root',str(self.root),'export','--view',str(self.dest),'--to',str(output)]));self.assertEqual(r['files'],3)

if __name__=='__main__':unittest.main(verbosity=2)
