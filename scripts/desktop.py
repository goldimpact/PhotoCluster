"""Small local control window; no admin rights, phone changes or PID termination."""
import json
import os
from pathlib import Path
import queue
import subprocess
import sys
import threading
from urllib.request import Request, build_opener, ProxyHandler
import webbrowser

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from photocluster.runtime import workspace_id
from photocluster.config import DATA

COPY = {
    'title': ('PhotoCluster 控制窗口', 'PhotoCluster control'),
    'idle': ('尚未启动', 'Stopped'), 'starting': ('正在启动，请稍候…', 'Starting, please wait…'),
    'running': ('正在运行', 'Running'), 'stopping': ('正在退出，等待当前工作保存…', 'Exiting; waiting for current work…'),
    'unknown': ('连接中断；尚未确认进程已停止', 'Connection lost; process exit not confirmed'),
    'failed': ('启动失败，请查看日志或安装/修复依赖。', 'Startup failed. View logs or install/repair dependencies.'),
    'note': ('关闭浏览器不会退出。请使用这里或网页中的退出按钮。', 'Closing the browser does not quit. Use Exit here or in the page.'),
    'start': ('启动并打开', 'Start and open'), 'open': ('打开界面', 'Open interface'),
    'exit': ('退出程序', 'Exit application'), 'repair': ('安装 / 修复依赖', 'Install / repair dependencies'),
    'logs': ('查看日志', 'View logs'), 'port': ('端口', 'Port'),
    'confirm': ('退出前会停止分类、保存缓存并等待正在进行的文件操作。是否退出？', 'Stop classification, save caches and wait for active file operations, then exit?'),
    'external': ('检测到外部命令启动的实例，请在对应终端按 Ctrl+C。', 'An externally managed instance is running. Press Ctrl+C in its terminal.'),
    'conflict': ('此端口不是当前项目的可管理实例，请检查端口或旧版服务。', 'This port is not a manageable instance of this workspace. Check the port or an older service.'),
    'request_failed': ('未能确认退出，请检查连接后重试；不会强杀进程。', 'Exit could not be confirmed. Check the connection and retry; no process will be killed.'),
    'install': ('将从公开软件源下载 Python 依赖，不会上传媒体。继续？', 'Download Python dependencies from public package sources? Media will not be uploaded.'),
    'close_busy': ('当前仍在启动或安装，请等待完成后再退出。', 'Startup or installation is still running. Please wait before exiting.'),
    'installed': ('依赖安装完成，可以点击启动。', 'Dependencies installed. Click Start to continue.'),
}


def main():
    try:
        import tkinter as tk
        from tkinter import ttk, messagebox
    except ImportError:
        raise SystemExit('Desktop controls require Tk: install python3-tk (or tkinter for your Python distribution). CLI: bash start.sh')
    root = tk.Tk(); root.title('PhotoCluster'); root.geometry('610x390'); root.minsize(560,360)
    language = tk.StringVar(value='zh'); port = tk.StringVar(value='8765')
    events = queue.Queue(); state = {'phase':'idle','snapshot':None,'child':None,'log':None,'busy':False,'quit':False,'exit_sent':False,'seen':False,'polling':False,'repair':False,'ended':False}
    text = lambda key: COPY[key][language.get() == 'en']
    frame=ttk.Frame(root,padding=24);frame.pack(fill='both',expand=True)
    title=ttk.Label(frame,font=('',18,'bold'));title.pack(anchor='w')
    status=ttk.Label(frame,font=('',13));status.pack(anchor='w',pady=(20,8))
    note=ttk.Label(frame,wraplength=550);note.pack(anchor='w')
    settings=ttk.Frame(frame);settings.pack(fill='x',pady=18)
    port_label=ttk.Label(settings);port_label.pack(side='left')
    entry=ttk.Entry(settings,textvariable=port,width=8);entry.pack(side='left',padx=10)
    selector=ttk.Combobox(settings,textvariable=language,values=['zh','en'],state='readonly',width=6);selector.pack(side='right')
    ttk.Label(settings,text='语言 / Language').pack(side='right',padx=8)
    buttons=ttk.Frame(frame);buttons.pack(fill='x',pady=8)
    start=ttk.Button(buttons);start.pack(side='left',padx=(0,8))
    opened=ttk.Button(buttons);opened.pack(side='left',padx=8)
    stopped=ttk.Button(buttons);stopped.pack(side='left',padx=8)
    support=ttk.Frame(frame);support.pack(fill='x',pady=12)
    repair=ttk.Button(support);repair.pack(side='left',padx=(0,8))
    logs=ttk.Button(support);logs.pack(side='left',padx=8)
    address=ttk.Label(frame);address.pack(anchor='w',pady=8)
    def url():
        value=int(port.get())
        if not 1 <= value <= 65535:raise ValueError('port')
        return f'http://127.0.0.1:{value}'
    def request(base, path, token=None):
        req=Request(base+path, data=b'' if token else None, headers={'X-PhotoCluster-Token':token} if token else {})
        with build_opener(ProxyHandler({})).open(req,timeout=3) as response:return json.load(response)
    def render(*_):
        title.config(text=text('title'));status.config(text=text(state['phase']));note.config(text=text('note'))
        for button,key in [(start,'start'),(opened,'open'),(stopped,'exit'),(repair,'repair'),(logs,'logs')]:button.config(text=text(key))
        port_label.config(text=text('port'))
        active=state['phase'] in ('starting','stopping','running','external') or bool(state['child'])
        start.config(state='disabled' if active or state['busy'] else 'normal')
        repair.config(state='disabled' if active or state['busy'] else 'normal')
        opened.config(state='normal' if state['snapshot'] and not state['snapshot'].get('stopping') else 'disabled')
        stopped.config(state='normal' if state['snapshot'] and state['snapshot'].get('managed') and state['phase']!='stopping' else 'disabled')
        entry.config(state='disabled' if active or state['busy'] else 'normal')
        try:address.config(text=url())
        except ValueError:address.config(text='')
    def launch(install=False):
        if state['busy'] or state['child'] or state['snapshot']:return
        try:url()
        except ValueError:messagebox.showerror('PhotoCluster','Port: 1–65535');return
        if install and not messagebox.askyesno('PhotoCluster',text('install')):return
        DATA.mkdir(parents=True,exist_ok=True)
        logfile=(DATA/'launcher.log').open('ab');state['log']=logfile
        interpreter=ROOT/('.venv/Scripts/python.exe' if os.name=='nt' else '.venv-linux/bin/python')
        python=str(interpreter) if interpreter.exists() else sys.executable
        if os.name=='nt' and python.lower().endswith('pythonw.exe'):python=python[:-11]+'python.exe'
        args=[python,str(ROOT/'scripts/start.py'),'--port',port.get(),'--no-browser']
        if interpreter.exists() and not install:args.append('--no-install')
        if install:args.append('--check')
        try:
            state['child']=subprocess.Popen(args,cwd=ROOT,stdout=logfile,stderr=logfile,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
            state.update(phase='starting',busy=True,seen=False,exit_sent=False,repair=install,ended=False)
        except OSError:logfile.close();state.update(phase='failed',log=None)
        render()
    def exit_application(close_window=False):
        snapshot=state['snapshot']
        if not snapshot:
            if state['child'] or state['busy']:messagebox.showinfo('PhotoCluster',text('close_busy'));return
            if close_window:root.destroy()
            return
        if not snapshot.get('managed'):messagebox.showinfo('PhotoCluster',text('external'));return
        if state['phase']=='stopping':return
        if not messagebox.askyesno('PhotoCluster',text('confirm')):return
        state['quit']=close_window
        base=url()
        def send():
            try:request(base,'/api/runtime/exit',snapshot['token']);events.put(('exit',None))
            except Exception:events.put(('exit-error',None))
        threading.Thread(target=send,daemon=True).start()
    def log_window():
        win=tk.Toplevel(root);win.title(text('logs'));win.geometry('760x450')
        view=tk.Text(win,wrap='word');view.pack(fill='both',expand=True)
        try:
            with (DATA/'launcher.log').open('rb') as handle:
                handle.seek(0,2);handle.seek(max(0,handle.tell()-60000));value=handle.read().decode('utf-8','replace')
        except OSError:value='No log / 暂无日志'
        view.insert('1.0',value);view.config(state='disabled')
    def poll():
        if not state['polling']:
            state['polling']=True
            try:base=url()
            except ValueError:base=None
            def read():
                try:events.put(('status',request(base,'/api/runtime') if base else None))
                except Exception:events.put(('status',None))
            threading.Thread(target=read,daemon=True).start()
        while not events.empty():
            kind,data=events.get()
            if kind=='exit':state.update(exit_sent=True,phase='stopping')
            elif kind=='exit-error':state['quit']=False;messagebox.showerror('PhotoCluster',text('request_failed'))
            else:
                state['polling']=False
                if data and (data.get('application')!='PhotoCluster' or data.get('workspace')!=workspace_id()):
                    state.update(phase='conflict',snapshot=None)
                elif data:
                    state['snapshot']=data
                    state['phase']='stopping' if data['stopping'] else 'running' if data['managed'] else 'external'
                    if state['child'] and not state['seen'] and not state['repair'] and not data['stopping']:
                        webbrowser.open(url());state['seen']=True
                else:
                    state['snapshot']=None
                    if not state['child'] and state['phase'] in ('running','stopping','external'):
                        state['phase']='idle' if state['ended'] else 'unknown'
                        if state['quit'] and state['ended']:root.destroy();return
        child=state['child']
        if child and child.poll() is not None:
            code=child.returncode;state['log'].close();state.update(child=None,log=None,busy=False,ended=code==0)
            if not state['snapshot']:
                state['phase']=('installed' if state['repair'] else 'idle') if code==0 else 'failed'
                if state['quit'] and code==0:root.destroy();return
        render();root.after(600,poll)
    start.config(command=lambda:launch());repair.config(command=lambda:launch(True))
    opened.config(command=lambda:webbrowser.open(url()));stopped.config(command=lambda:exit_application())
    logs.config(command=log_window);selector.bind('<<ComboboxSelected>>',render)
    root.protocol('WM_DELETE_WINDOW',lambda:exit_application(True));render();poll();root.mainloop()


if __name__=='__main__':
    try:main()
    except Exception as exc:
        try:
            from tkinter import messagebox
            messagebox.showerror('PhotoCluster',f'Launcher could not start / 启动器无法打开:\n{exc}')
        finally:raise
