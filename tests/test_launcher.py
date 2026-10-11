"""Launcher wiring without installing software or opening a real server."""
import pytest

from scripts import start


def test_existing_environment_no_install_is_loopback_and_keeps_options(tmp_path, monkeypatch):
    monkeypatch.setattr(start, 'ROOT', tmp_path)
    folder = tmp_path / ('.venv' if start.os.name == 'nt' else '.venv-linux')
    interpreter = folder / ('Scripts/python.exe' if start.os.name == 'nt' else 'bin/python')
    interpreter.parent.mkdir(parents=True)
    interpreter.touch()
    calls = []
    monkeypatch.setattr(start.subprocess, 'run', lambda command, **kw: calls.append((command, kw)))
    monkeypatch.setattr(start.sys, 'argv', ['start.py', '--no-install', '--port', '8766', '--accelerator', 'cpu',
                                          '--adb', '/tools with spaces/adb', '--data-dir', str(tmp_path / 'private')])
    # monkeypatch restores cwd even though the launcher changes it.
    monkeypatch.chdir(tmp_path)
    start.main()
    commands = [command for command, _ in calls]
    assert not any('pip' in command or 'venv' in command for command in commands)
    assert commands[-1][-4:] == ['--host', '127.0.0.1', '--port', '8766']
    assert all(kw['env']['PHOTOCLUSTER_ADB'] == '/tools with spaces/adb' for _, kw in calls)
    assert all(kw['env']['PHOTOCLUSTER_DATA_DIR'] == str(tmp_path / 'private') for _, kw in calls)


def test_check_never_starts_server(tmp_path, monkeypatch):
    monkeypatch.setattr(start, 'ROOT', tmp_path)
    folder = tmp_path / ('.venv' if start.os.name == 'nt' else '.venv-linux')
    interpreter = folder / ('Scripts/python.exe' if start.os.name == 'nt' else 'bin/python')
    interpreter.parent.mkdir(parents=True)
    interpreter.touch()
    calls = []
    monkeypatch.setattr(start.subprocess, 'run', lambda command, **kw: calls.append(command))
    monkeypatch.setattr(start.sys, 'argv', ['start.py', '--no-install', '--check'])
    monkeypatch.chdir(tmp_path)
    start.main()
    assert calls[-1][-2:] == ['-m', 'photocluster.doctor']
    assert not any('photocluster.app:app' in command for command in calls)


def test_no_install_rejects_missing_environment(tmp_path, monkeypatch):
    monkeypatch.setattr(start, 'ROOT', tmp_path)
    monkeypatch.setattr(start.sys, 'argv', ['start.py', '--no-install'])
    monkeypatch.chdir(tmp_path)
    with pytest.raises(SystemExit) as exc:
        start.main()
    assert exc.value.code == 2
