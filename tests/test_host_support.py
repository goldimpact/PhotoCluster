import subprocess
from unittest.mock import Mock

from photocluster import adb, config


def test_native_adb_and_explicit_executable_paths(monkeypatch):
    monkeypatch.delenv('PHOTOCLUSTER_ADB', raising=False)
    monkeypatch.setattr(adb, 'is_wsl', lambda: False)
    monkeypatch.setattr(adb.shutil, 'which', lambda name: '/usr/bin/adb' if name == 'adb' else None)
    assert adb.executable() == '/usr/bin/adb'
    monkeypatch.setenv('PHOTOCLUSTER_ADB', '/some path/platform-tools/adb')
    command = Mock(return_value=subprocess.CompletedProcess([], 0, b'ok', b''))
    monkeypatch.setattr(adb.subprocess, 'run', command)
    assert adb.run(['devices']) == b'ok'
    assert command.call_args.args[0] == ['/some path/platform-tools/adb', 'devices']


def test_wsl_windows_adb_fallback_and_pull_destination(monkeypatch, tmp_path):
    monkeypatch.delenv('PHOTOCLUSTER_ADB', raising=False)
    monkeypatch.setattr(adb, 'is_wsl', lambda: True)
    monkeypatch.setattr(adb.shutil, 'which', lambda name: '/mnt/c/tools/adb.exe' if name == 'adb.exe' else None)
    assert adb.executable() == '/mnt/c/tools/adb.exe'
    destination = tmp_path / 'video with space.mp4'
    windows_path = r'\\wsl.localhost\Ubuntu\tmp\video with space.mp4'
    convert = Mock(return_value=subprocess.CompletedProcess([], 0, (windows_path + '\n').encode(), b''))
    run = Mock()
    monkeypatch.setattr(adb.subprocess, 'run', convert)
    monkeypatch.setattr(adb, 'run', run)
    adb.pull_file('mock', '/storage/emulated/0/中文.mp4', destination)
    assert convert.call_args.args[0] == ['wslpath', '-w', str(destination.resolve())]
    assert run.call_args.args[0] == ['-s', 'mock', 'pull', '/storage/emulated/0/中文.mp4', windows_path]


def test_native_pull_does_not_translate_local_path(monkeypatch, tmp_path):
    monkeypatch.setattr(adb, 'is_wsl', lambda: False)
    monkeypatch.setattr(adb.subprocess, 'run', Mock(side_effect=AssertionError('Unexpected conversion')))
    assert adb.local_destination(tmp_path / 'a.mp4') == str(tmp_path / 'a.mp4')


def test_data_roots_keep_windows_and_wsl_caches_separate(monkeypatch, tmp_path):
    monkeypatch.delenv('PHOTOCLUSTER_DATA_DIR', raising=False)
    monkeypatch.setattr(config, 'ROOT', tmp_path)
    monkeypatch.setattr(config, 'is_wsl', lambda: False)
    assert config.data_directory() == tmp_path / 'data'
    monkeypatch.setattr(config, 'is_wsl', lambda: True)
    assert config.data_directory() == tmp_path / 'data/wsl'
    monkeypatch.setenv('PHOTOCLUSTER_DATA_DIR', str(tmp_path / 'private'))
    assert config.data_directory() == tmp_path / 'private'


def test_adb_binary_output_is_not_newline_translated(monkeypatch):
    payload = b'\x00\xff\r\n\x1a\n'
    command = Mock(return_value=subprocess.CompletedProcess([], 0, payload, b''))
    monkeypatch.setattr(adb.subprocess, 'run', command)
    assert adb.read_photo('mock', '/storage/emulated/0/a.jpg') == payload
    assert not command.call_args.kwargs.get('text')


def test_missing_adb_has_actionable_message(monkeypatch):
    import pytest
    monkeypatch.setattr(adb.subprocess, 'run', Mock(side_effect=FileNotFoundError))
    with pytest.raises(RuntimeError, match='PHOTOCLUSTER_ADB'):
        adb.devices()
