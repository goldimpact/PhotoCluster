from photocluster import vision,semantic
import numpy as np


def test_geometry_reports_each_completed_file_including_exact_duplicates(monkeypatch):
    photos=[dict(key=str(i),sha256='same',width=100,height=100,size=10,sharpness=1,hashes=[0],album='/a') for i in range(7)]
    progress=[]
    vision.cluster(photos,progress=lambda done,total:progress.append((done,total)))
    assert progress==[(i,7) for i in range(1,8)]


def test_semantic_reports_each_completed_file_including_exact_duplicates(tmp_path,monkeypatch):
    photos=[dict(key=str(i),sha256='same',width=100,height=100,size=10,sharpness=1,album='/a') for i in range(7)]
    v=np.zeros((1,512),np.float32);v[0,0]=1
    monkeypatch.setattr(semantic,'load_vectors',lambda *args:[v]*7)
    progress=[]
    semantic.cluster(photos,tmp_path,progress=lambda done,total,phase:progress.append((done,total,phase)))
    assert progress==[(i,7,'content_match') for i in range(1,8)]
