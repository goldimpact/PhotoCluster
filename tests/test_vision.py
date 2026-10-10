import io

import cv2
import numpy as np
import pytest
from PIL import Image, ImageFilter

from photocluster import vision


def scene(seed=12):
    rng = np.random.default_rng(seed)
    image = np.full((480, 640, 3), 210, np.uint8)
    for _ in range(100):
        x, y = rng.integers([0, 0], [640, 480])
        color = tuple(int(v) for v in rng.integers(0, 255, 3))
        cv2.circle(image, (x, y), int(rng.integers(3, 40)), color, -1)
    cv2.putText(image, 'PHOTO 2026', (40, 230), cv2.FONT_HERSHEY_SIMPLEX, 1.5, (0, 0, 0), 3)
    return Image.fromarray(image)


def feature(image, path, quality=90):
    buffer = io.BytesIO()
    image.save(buffer, 'JPEG', quality=quality)
    return dict(vision.features(buffer.getvalue(), path), key=path.stem, size=len(buffer.getvalue()), album='/a')


@pytest.mark.parametrize('transform', ['compressed', 'blur', 'resize', 'stretch', 'rotate90', 'rotate23', 'crop'])
def test_transforms(tmp_path, transform):
    original = scene()
    variants = dict(compressed=original, blur=original.filter(ImageFilter.GaussianBlur(1)),
                    resize=original.resize((320, 240)), stretch=original.resize((420, 480)),
                    rotate90=original.rotate(90, expand=True), rotate23=original.rotate(23, expand=True, fillcolor='white'),
                    crop=original.crop((25, 20, 620, 465)))
    a = feature(original, tmp_path/'a.jpg')
    b = feature(variants[transform], tmp_path/'b.jpg', 35 if transform=='compressed' else 90)
    assert vision.compare(a, b, 'strong') is not None, transform
    groups = vision.cluster([a, b], 'strong')
    assert len(groups) == 1, 'Candidate retrieval missed '+transform


def test_different_and_scope(tmp_path):
    a = feature(scene(), tmp_path/'a.jpg')
    b = feature(scene(123), tmp_path/'b.jpg')
    assert vision.compare(a, b, 'strong') is None
    c = dict(a, album='/b')
    assert len(vision.cluster([a, c], 'strong', 'all')) == 1
    assert vision.cluster([a, c], 'strong', 'album') == []


def test_no_transitive_chain(monkeypatch):
    photos = [dict(width=100-i, height=100, size=100, sharpness=10, hashes=[0], album='/a', n=i) for i in range(3)]
    monkeypatch.setattr(vision, 'compare', lambda a,b,mode: (.95,'match') if abs(a['n']-b['n'])==1 else None)
    result = vision.cluster(photos)
    assert [p['n'] for p in result[0]] == [0, 1]
