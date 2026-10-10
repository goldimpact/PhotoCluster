import hashlib
from unittest.mock import Mock

import pytest

from photocluster.adb import parse_inventory
from photocluster.operations import Operations
from photocluster.service import Service


def test_inventory_special_paths():
    text = "Row: 0 _id=1, _data=/storage/emulated/0/中文/it's, photo.jpg, _size=10, date_modified=3, width=4, height=5, bucket_id=-2, bucket_display_name=中文\r\n"
    photo = parse_inventory(text)[0]
    assert photo['path'].endswith("it's, photo.jpg")
    with pytest.raises(RuntimeError):
        parse_inventory('Permission denied')


@pytest.fixture
def setup(tmp_path, monkeypatch):
    service = Service(tmp_path)
    p = dict(key='a', path='/storage/emulated/0/a/a.jpg', album='/storage/emulated/0/a', album_name='a',
             size=3, modified=123, sha256=hashlib.sha256(b'abc').hexdigest())
    q = dict(p, key='b', path='/storage/emulated/0/b/b.jpg', album='/storage/emulated/0/b')
    service.catalog = dict(serial='serial', photos=[dict(p),dict(q)])
    service.result = dict(summary={'serial':'serial'}, groups=[dict(id=1,photos=[dict(p),dict(q)],potential_bytes=3)])
    commands=[]
    def shell(serial, command):
        commands.append(command)
        return 'yes' if command.startswith('if test') else ''
    monkeypatch.setattr('photocluster.operations.shell', shell)
    monkeypatch.setattr('photocluster.operations.adb.read_photo', lambda *args:b'abc')
    monkeypatch.setattr('photocluster.operations.sync_media', lambda *args:None)
    return service, Operations(service), commands


def test_delete_real_file(setup,monkeypatch):
    s,ops,commands=setup
    monkeypatch.setattr('photocluster.operations.exists', lambda *args:False)
    plan=ops.prepare(['a'],'delete')
    assert commands==[] # Preview cannot mutate the device.
    result=ops.execute(plan['token'])
    assert result['succeeded']==1
    assert 'rm -- /storage/emulated/0/a/a.jpg' in commands
    assert [p['key'] for p in s.catalog['photos']]==['b']
    with pytest.raises(ValueError): ops.execute(plan['token'])


def test_reject_virtual_destination_and_add(setup):
    _,ops,_=setup
    with pytest.raises(ValueError): ops.prepare(['a'],'move','virtual-group-1')
    with pytest.raises(ValueError): ops.prepare(['a'],'add')


def test_changed_content_never_deleted(setup,monkeypatch):
    _,ops,commands=setup
    monkeypatch.setattr('photocluster.operations.adb.read_photo', lambda *args:b'changed')
    assert ops.execute(ops.prepare(['a'],'delete')['token'])['succeeded']==0
    assert not any(c.startswith('rm ') for c in commands)


def test_collision_never_overwrites(setup,monkeypatch):
    _,ops,commands=setup
    monkeypatch.setattr('photocluster.operations.exists', lambda *args:True)
    assert ops.execute(ops.prepare(['a'],'move','/storage/emulated/0/b')['token'])['succeeded']==0
    assert not any(c.startswith('mv ') for c in commands)


def test_move_updates_real_path_keeps_virtual_group(setup,monkeypatch):
    s,ops,commands=setup
    checks=iter([False,False,True])
    monkeypatch.setattr('photocluster.operations.exists',lambda *args:next(checks))
    result=ops.execute(ops.prepare(['a'],'move','/storage/emulated/0/b')['token'])
    assert result['succeeded']==1
    assert s.result['groups'][0]['photos'][0]['path']=='/storage/emulated/0/b/a.jpg'
    assert s.result['groups'][0]['id']==1
