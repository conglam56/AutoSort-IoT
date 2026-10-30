"""Protect source data and held-out splits when applying reviewed annotations."""
import hashlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
import zipfile

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'training'))
from refine_detection_dataset import refine_dataset
from train_detection import verify_dataset


class DetectionRefinementTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.source=self.root/'v1'
        self.images=[]
        for split_id,split in enumerate(('train','val','test')):
            for class_id in range(3):
                buffer=io.BytesIO()
                Image.new('RGB',(64,64),(40+class_id*60,50+split_id*60,40)).save(buffer,format='JPEG')
                data=buffer.getvalue();key=hashlib.sha256(data).hexdigest()
                relative=f'images/{split}/{key}.jpg'
                path=self.source/relative;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(data)
                label=self.source/'labels'/split/(key+'.txt');label.parent.mkdir(parents=True,exist_ok=True)
                label.write_text(f'{class_id} 0.5000000000 0.5000000000 0.8000000000 0.8000000000\n')
                self.images.append({'sha256':key,'file':relative,'split':split,'group':key,'dimensions':[64,64],'boxes':[{'class':class_id,'box':[.5,.5,.8,.8]}]})
        self.manifest={'classes':['GREEN','RIPE','REJECT'],'images':self.images,'quarantine':[],'sources':[],'limitations':[]}
        self.save_manifest()
        (self.source/'data.yaml').write_text('path: .\ntrain: images/train\nval: images/val\ntest: images/test\nnames:\n  0: GREEN\n  1: RIPE\n  2: REJECT\n')
        self.review=self.root/'review.json'

    def save_manifest(self):
        (self.source/'manifest.json').write_text(json.dumps(self.manifest))

    def write_review(self,changes):
        self.review.write_text(json.dumps({'source_manifest_sha256':hashlib.sha256((self.source/'manifest.json').read_bytes()).hexdigest(),'limitations':[],'changes':changes}))

    def test_relabels_new_copy_and_preserves_source_and_split(self):
        before={p.relative_to(self.source):p.read_bytes() for p in self.source.rglob('*') if p.is_file()}
        original=self.images[1]
        self.write_review([{'sha256':original['sha256'],'action':'relabel','boxes':[{'class':2,'box':[.5,.5,.8,.8]}],'reason':'Visible skin scar on whole fruit'}])
        result=refine_dataset(self.source,self.root/'v2',self.review)
        changed=next(i for i in result['images'] if i['sha256']==original['sha256'])
        self.assertEqual(changed['boxes'][0]['class'],2)
        self.assertEqual(changed['split'],'train')
        self.assertEqual({i['sha256']:i['split'] for i in result['images']},{i['sha256']:i['split'] for i in self.images})
        for name,data in before.items():self.assertEqual((self.source/name).read_bytes(),data)
        verify_dataset(self.root/'v2')
        with self.assertRaisesRegex(ValueError,'new and separate'):
            refine_dataset(self.source,self.root/'v2',self.review)

    def test_quarantines_entire_existing_duplicate_group(self):
        self.images[1]['group']=self.images[0]['group'];self.save_manifest()
        self.write_review([{'sha256':self.images[0]['sha256'],'action':'quarantine','reason':'Unclear stem or scar'}])
        result=refine_dataset(self.source,self.root/'v2',self.review)
        self.assertEqual(len(result['quarantine']),2)
        self.assertEqual(len(result['images']),7)
        self.assertTrue(all((self.root/'v2'/i['file']).is_file() for i in result['quarantine']))
        self.assertTrue(all((self.source/i['file']).is_file() for i in self.images))

    def test_rejects_stale_unknown_duplicate_and_invalid_review_before_output(self):
        key=self.images[0]['sha256']
        valid={'sha256':key,'action':'quarantine','reason':'Uncertain'}
        cases=[[dict(valid,sha256='unknown')],[valid,valid],[dict(valid,reason='')],
               [dict(valid,action='relabel',boxes=[{'class':2,'box':[.9,.5,.8,.8]}])],
               [dict(valid,action='relabel',boxes=[{'class':3,'box':[.5,.5,.8,.8]}])]]
        for number,changes in enumerate(cases):
            with self.subTest(number=number):
                self.write_review(changes);dest=self.root/f'bad-{number}'
                with self.assertRaises(ValueError):refine_dataset(self.source,dest,self.review)
                self.assertFalse(dest.exists())
        self.write_review([])
        review=json.loads(self.review.read_text());review['source_manifest_sha256']='stale';self.review.write_text(json.dumps(review))
        with self.assertRaisesRegex(ValueError,'different source'):refine_dataset(self.source,self.root/'stale',self.review)
        self.assertFalse((self.root/'stale').exists())

    def make_supplement(self):
        buffer=io.BytesIO();Image.new('RGB',(80,64),(251,125,21)).save(buffer,format='JPEG');data=buffer.getvalue()
        archive=self.root/'public.zip'
        with zipfile.ZipFile(archive,'w') as file:file.writestr('dataset/rotten.jpg',data)
        info={'archive_sha256':hashlib.sha256(archive.read_bytes()).hexdigest(),'split':'train',
              'source':{'title':'Fixture','authors':['Test'],'url':'https://example.com/fixture','license':'CC BY 4.0','license_url':'https://creativecommons.org/licenses/by/4.0/'},
              'limitations':['Training-only fixture'],
              'accepted':[{'archive_member':'dataset/rotten.jpg','sha256':hashlib.sha256(data).hexdigest(),'class':2,'box':[.5,.5,.8,.8],'dimensions':[80,64],'annotation_method':'Manual fixture','reason':'Fixture defect'}]}
        path=self.root/'supplement.json';path.write_text(json.dumps(info))
        return archive,path,info

    def test_supplement_stays_train_only_and_requires_matching_archive(self):
        self.write_review([]);archive,path,info=self.make_supplement()
        result=refine_dataset(self.source,self.root/'v2',self.review,archive,path)
        added=[i for i in result['images'] if i['group']=='public-orange-v2-all-training']
        self.assertEqual(len(added),1);self.assertEqual(added[0]['split'],'train')
        self.assertEqual(result['counts']['test']['images'],3)
        self.assertEqual(result['counts']['val']['images'],3)
        for field,value in [('split','test'),('archive_sha256','bad')]:
            bad=dict(info,**{field:value});path.write_text(json.dumps(bad));dest=self.root/f'bad-{field}'
            with self.assertRaisesRegex(ValueError,'checksum mismatch or evaluation'):
                refine_dataset(self.source,dest,self.review,archive,path)
            self.assertFalse(dest.exists())


if __name__=='__main__':unittest.main()
