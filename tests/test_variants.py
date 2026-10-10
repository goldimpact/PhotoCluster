import cv2
import numpy as np
import pytest
from PIL import Image, ImageOps

from photocluster import variants
from test_vision import scene, feature


def transformed(image, kind):
    rgb=np.array(image); h,w=rgb.shape[:2]
    if kind=='upside_down': return image.rotate(180)
    if kind=='mirror': return ImageOps.mirror(image)
    if kind=='vertical_flip': return ImageOps.flip(image)
    if kind=='caption':
        cv2.rectangle(rgb,(10,360),(630,440),(255,255,255),-1)
        cv2.putText(rgb,'NEW CAPTION',(30,415),cv2.FONT_HERSHEY_SIMPLEX,1.5,(0,0,0),3)
    elif kind=='affine':
        rgb=cv2.warpAffine(rgb,np.float32([[.87,.16,0],[-.06,.9,35]]),(w,h),borderValue=(255,255,255))
    elif kind=='perspective':
        matrix=cv2.getPerspectiveTransform(np.float32([[0,0],[w,0],[w,h],[0,h]]),np.float32([[45,30],[w-25,0],[w-5,h-55],[0,h]]))
        rgb=cv2.warpPerspective(rgb,matrix,(w,h),borderValue=(255,255,255))
    elif kind=='warp':
        y,x=np.mgrid[:h,:w].astype(np.float32)
        rgb=cv2.remap(rgb,x+7*np.sin(y/43),y+5*np.sin(x/70),cv2.INTER_LINEAR,borderMode=cv2.BORDER_REFLECT)
    return Image.fromarray(rgb)


@pytest.mark.parametrize('kind',['upside_down','mirror','vertical_flip','caption','affine','perspective','warp'])
def test_same_source_transforms_and_retrieval(tmp_path,kind):
    a=feature(scene(),tmp_path/'a.jpg')
    b=feature(transformed(scene(),kind),tmp_path/'b.jpg')
    groups=variants.cluster([a,b],'all',lambda *args:None,lambda:False,rules={'warp':True})
    assert len(groups)==1,kind
    assert all('variant_path' in p for p in groups[0])


def test_reject_similar_style_different_source(tmp_path):
    photos=[feature(scene(seed),tmp_path/f'{seed}.jpg') for seed in (12,123,222,777)]
    prepared=[variants.prepare(p) for p in photos]
    for p in prepared[1:]:
        assert variants.compare(prepared[0],p) is None
    assert variants.cluster(photos,'all',lambda *args:None,lambda:False)==[]


def test_temporal_requires_two_shared_frames(tmp_path):
    a=feature(scene(),tmp_path/'a.jpg'); b=feature(scene(123),tmp_path/'b.jpg')
    for p, seeds in ((a,[12,222,777]),(b,[12,123,456])):
        path=tmp_path/(p['key']+'.frames.npz')
        np.savez_compressed(path,frames=np.stack([np.array(scene(n).resize((256,256))) for n in seeds]))
        p.update(frame_path=str(path),media_type='video')
    assert variants.compare(variants.prepare(a),variants.prepare(b)) is None


def test_cross_format_shared_transformed_frames(tmp_path):
    still=feature(scene(),tmp_path/'still.jpg')
    moving=[]
    for name,kind in [('gif','affine'),('video','perspective')]:
        photo=feature(transformed(scene(),kind),tmp_path/(name+'.jpg'))
        path=tmp_path/(name+'.frames.npz')
        np.savez_compressed(path,frames=np.stack([np.array(transformed(scene(seed),kind).resize((256,256))) for seed in (12,222,777)]))
        photo.update(frame_path=str(path),animated=name=='gif',media_type='video' if name=='video' else 'image')
        moving.append(variants.prepare(photo))
    assert variants.compare(variants.prepare(still),moving[0]) is not None
    assert variants.compare(moving[0],moving[1]) is not None


@pytest.mark.parametrize('angle',[90,180,270,23])
@pytest.mark.parametrize('flip',['horizontal','vertical'])
def test_mirror_then_rotation(tmp_path,angle,flip):
    original=scene()
    mirrored=ImageOps.mirror(original) if flip=='horizontal' else ImageOps.flip(original)
    changed=mirrored.rotate(angle,expand=True,fillcolor='white')
    a=feature(original,tmp_path/'original.jpg');b=feature(changed,tmp_path/'changed.jpg')
    # No perspective or nonlinear warp is needed for a reflected rotation.
    rules=dict(mirror=True,perspective=False,warp=False)
    assert variants.compare(variants.prepare(a),variants.prepare(b),rules=rules) is not None
    groups=variants.cluster([a,b],'all',lambda *args:None,lambda:False,rules=rules)
    assert len(groups)==1 and len(groups[0])==2
