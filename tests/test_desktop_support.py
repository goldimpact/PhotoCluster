from photocluster.desktop_support import LogTail, browser_url, read_language, save_language


def test_launcher_language_is_explicit_and_remembered(tmp_path):
    path=tmp_path/'preferences.json'
    assert read_language(path)=='zh'
    save_language(path,'en');assert read_language(path)=='en'
    assert browser_url('http://127.0.0.1:8765','zh')=='http://127.0.0.1:8765/?lang=zh'
    assert browser_url('http://127.0.0.1:8765','en').endswith('?lang=en')
    save_language(path,'invalid');assert read_language(path)=='en'
    path.write_text('bad');assert read_language(path)=='zh'


def test_log_tail_is_incremental_bounded_and_handles_partial_utf8(tmp_path):
    path=tmp_path/'launcher.log';tail=LogTail(path,limit=10)
    assert tail.read()==(False,'')
    path.write_bytes(b'x'*30);assert tail.read()==(True,'x'*10)
    assert tail.read()==(False,'')
    char='中'.encode()
    with path.open('ab') as f:f.write(char[:2])
    assert tail.read()==(False,'')
    with path.open('ab') as f:f.write(char[2:]+b'\n')
    assert tail.read()==(False,'中\n')
    path.write_bytes(b'new');assert tail.read()==(True,'new')
    replacement=tmp_path/'new.log';replacement.write_bytes(b'replaced');replacement.replace(path)
    assert tail.read()==(True,'replaced')
