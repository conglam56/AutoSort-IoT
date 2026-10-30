"""Apply explicit reviewed labels to a new dataset without changing v1."""
import argparse
from collections import Counter
import copy
import hashlib
import json
import math
from pathlib import Path
import shutil
import zipfile

from train_detection import verify_dataset


def checked_boxes(boxes):
    if not isinstance(boxes, list) or not boxes:
        raise ValueError('Reviewed images need whole-fruit annotations')
    for box in boxes:
        values = box.get('box', [])
        if type(box.get('class')) is not int or box['class'] not in range(3):
            raise ValueError('Invalid reviewed class')
        if len(values) != 4 or not all(isinstance(v, (int, float)) and math.isfinite(v) for v in values):
            raise ValueError('Invalid reviewed coordinates')
        x, y, width, height = values
        if width <= 0 or height <= 0 or min(x-width/2, y-height/2) < -1e-6 or max(x+width/2, y+height/2) > 1+1e-6:
            raise ValueError('Reviewed box outside normalized image')
    return copy.deepcopy(boxes)


def refine_dataset(source, destination, review_path, supplement_archive=None, supplement_review=None):
    source, destination, review_path = map(lambda p: Path(p).resolve(), (source, destination, review_path))
    if destination.exists() or destination.is_relative_to(source) or source.is_relative_to(destination):
        raise ValueError('Destination must be new and separate from source')
    _, original = verify_dataset(source)
    for item in original['quarantine']:
        path = (source/item['file']).resolve()
        if not path.is_relative_to(source) or hashlib.sha256(path.read_bytes()).hexdigest()!=item['sha256']:
            raise ValueError('Invalid original quarantine image')
    source_bytes = (source/'manifest.json').read_bytes()
    review_bytes = review_path.read_bytes()
    review = json.loads(review_bytes)
    if review.get('source_manifest_sha256') != hashlib.sha256(source_bytes).hexdigest():
        raise ValueError('Review refers to a different source manifest')
    by_hash = {i['sha256']: i for i in original['images']}
    changes = {}
    for change in review['changes']:
        key = change['sha256']
        if key not in by_hash or key in changes or not change.get('reason', '').strip():
            raise ValueError('Unknown, duplicate, or unexplained review change')
        if change['action'] == 'relabel':
            checked_boxes(change['boxes'])
        elif change['action'] != 'quarantine':
            raise ValueError('Unsupported review action')
        changes[key] = change
    quarantine_groups = {by_hash[k]['group'] for k,c in changes.items() if c['action']=='quarantine'}
    supplement = None
    supplemental_files = []
    if bool(supplement_archive) != bool(supplement_review):
        raise ValueError('Supply both supplement archive and reviewed annotations')
    if supplement_archive:
        supplement = json.loads(Path(supplement_review).read_text(encoding='utf-8'))
        archive_bytes = Path(supplement_archive).read_bytes()
        if hashlib.sha256(archive_bytes).hexdigest()!=supplement['archive_sha256'] or supplement['split']!='train':
            raise ValueError('Supplement checksum mismatch or evaluation split requested')
        seen=set(by_hash)|{i['sha256'] for i in original['quarantine']}
        with zipfile.ZipFile(supplement_archive) as archive:
            for entry in supplement['accepted']:
                data=archive.read(entry['archive_member'])
                key=hashlib.sha256(data).hexdigest()
                if key!=entry['sha256'] or key in seen:
                    raise ValueError('Supplement hash mismatch or duplicate image')
                seen.add(key)
                boxes=checked_boxes([{'class':entry['class'],'box':entry['box']}])
                supplemental_files.append((entry,data,boxes))
    result = copy.deepcopy(original)
    result['images'] = []
    result['label_review'] = {k:v for k,v in review.items() if k!='changes'}
    result['label_review']['review_sha256'] = hashlib.sha256(review_bytes).hexdigest()
    result['limitations'] = list(dict.fromkeys(original['limitations'] + review['limitations']))
    if supplement:
        result['limitations']+=supplement['limitations']
        result['supplement_review']={k:v for k,v in supplement.items() if k not in ('accepted','quarantine')}
        result['supplement_review']['accepted_images']=len(supplemental_files)
        result['sources'].append(supplement['source']|{'archive_sha256':supplement['archive_sha256']})
    counts = {s: {'images':0, 'boxes':{c:0 for c in result['classes']}} for s in ('train','val','test')}
    # All review validation finishes before creating any output.
    destination.mkdir(parents=True)
    for item in result['quarantine']:
        src = (source/item['file']).resolve()
        dest = destination/item['file'];dest.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(src,dest)
    applied=[]
    for original_item in original['images']:
        item=copy.deepcopy(original_item);change=changes.get(item['sha256'])
        if item['group'] in quarantine_groups:
            item['reason'] = 'v2_visual_review_uncertain'
            item['review_reason'] = change['reason'] if change and change['action']=='quarantine' else 'Near-duplicate group contains a quarantined review image'
            item['original_file']=item['file']
            item['file']='review/'+Path(item['file']).name
            result['quarantine'].append(item)
            applied.append({'sha256':item['sha256'],'split':item['split'],'action':'quarantine','reason':item['review_reason']})
        else:
            if change:
                item['boxes']=checked_boxes(change['boxes'])
                applied.append({'sha256':item['sha256'],'split':item['split'],'action':'relabel','before':original_item['boxes'],'after':item['boxes'],'reason':change['reason']})
            result['images'].append(item)
            counts[item['split']]['images']+=1
            for b in item['boxes']:counts[item['split']]['boxes'][result['classes'][b['class']]]+=1
            label=destination/'labels'/item['split']/(Path(item['file']).stem+'.txt')
            label.parent.mkdir(parents=True,exist_ok=True)
            label.write_text('\n'.join('%d '%b['class']+' '.join(f'{v:.10f}' for v in b['box']) for b in item['boxes'])+'\n',encoding='utf-8')
        dest=destination/item['file'];dest.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(source/original_item['file'],dest)
    for entry,data,boxes in supplemental_files:
        key=entry['sha256'];relative='images/train/'+key+'.jpg'
        item={'sha256':key,'group':'public-orange-v2-all-training','split':'train','file':relative,
              'dimensions':entry['dimensions'],'boxes':boxes,
              'sources':[{'dataset':'public-orange-v2','file':entry['archive_member'],'split':'train','annotation_method':entry['annotation_method']}],
              'review_reason':entry['reason']}
        result['images'].append(item)
        (destination/relative).write_bytes(data)
        label=destination/'labels/train'/(key+'.txt')
        label.write_text('\n'.join('%d '%b['class']+' '.join(f'{v:.10f}' for v in b['box']) for b in boxes)+'\n',encoding='utf-8')
        counts['train']['images']+=1
        for b in boxes:counts['train']['boxes'][result['classes'][b['class']]]+=1
        applied.append({'sha256':key,'split':'train','action':'supplement','after':boxes,'reason':entry['reason']})
    result['counts']=counts
    result['quarantine_reasons']=dict(Counter(i['reason'] for i in result['quarantine']))
    result['review_changes']=applied
    (destination/'manifest.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    (destination/'review_changes.json').write_bytes(review_bytes)
    (destination/'data.yaml').write_text('path: .\ntrain: images/train\nval: images/val\ntest: images/test\nnames:\n  0: GREEN\n  1: RIPE\n  2: REJECT\n',encoding='utf-8')
    if (source/'ATTRIBUTION.txt').exists():shutil.copyfile(source/'ATTRIBUTION.txt',destination/'ATTRIBUTION.txt')
    if supplement:
        (destination/'supplement_review.json').write_text(json.dumps(supplement,indent=2)+'\n',encoding='utf-8')
        with (destination/'ATTRIBUTION.txt').open('a',encoding='utf-8') as file:
            info=supplement['source']
            file.write('\nSupplement: '+info['title']+' V2, '+', '.join(info['authors'])+'\n'+info['url']+'\n'+info['license']+' '+info['license_url']+'\nChanges: selected images, provisional whole-fruit detection annotations and class mapping; training only. No endorsement implied.\n')
    verify_dataset(destination)
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source',type=Path,required=True)
    parser.add_argument('--destination',type=Path,required=True)
    parser.add_argument('--review',type=Path,required=True)
    parser.add_argument('--supplement-archive',type=Path)
    parser.add_argument('--supplement-review',type=Path)
    args=parser.parse_args()
    result=refine_dataset(args.source,args.destination,args.review,args.supplement_archive,args.supplement_review)
    print(json.dumps({'counts':result['counts'],'quarantine':result['quarantine_reasons']}))
