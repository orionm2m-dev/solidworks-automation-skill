"""Exact-owner informational CAM OK helper; Windows UI, not native CAM API.

Never acquires the CAM/COM operation lock, activates a window, saves, cancels,
or retries a notification. The caller explicitly acknowledges the exact text.
"""
from __future__ import annotations
import hashlib,json,math,ntpath,os,time
from pathlib import Path

TITLE = 'Сообщение SOLIDWORKS CAM'
OK_LABELS = {'ОК','OK','&ОК','&OK'}


def require(ok,message):
    if not ok: raise ValueError(message)


from scripts.sw_executable_launch import _process_identity


def handle_information_prompt(process_id,*,expected_creation_time,expected_executable,expected_main_title,expected_text,
        receipt_path,action='inspect',acknowledge_information=False,gui=None,processes=None,read_identity=None,sleep=None):
    require(type(process_id)is int and 0<process_id<2**32,'Exact positive process ID required')
    require(type(expected_creation_time)in(int,float) and math.isfinite(expected_creation_time) and expected_creation_time>0,'Exact process creation time required')
    require(type(expected_executable)is str and ntpath.isabs(expected_executable) and ntpath.basename(expected_executable).casefold()=='sldworks.exe','Exact SOLIDWORKS executable path required')
    require(type(expected_main_title)is str and 1<=len(expected_main_title)<=2000 and expected_main_title.startswith('SOLIDWORKS ') and '\x00'not in expected_main_title,'Exact owned main document title required')
    require(type(expected_text)is str and 1<=len(expected_text)<=2000 and expected_text==expected_text.strip() and '\x00'not in expected_text,'Exact bounded informational text required')
    require(action in('inspect','acknowledge') and type(acknowledge_information)is bool,'Exact supported action/acknowledgement required')
    require(action!='acknowledge' or acknowledge_information is True,'Informational acknowledgement must be explicit')
    path=Path(receipt_path)
    require(path.is_absolute() and path.suffix.casefold()=='.json' and path.parent.is_dir() and not path.exists() and not path.is_symlink() and not path.parent.is_symlink() and not path.drive.startswith('\\'),'Fresh local receipt path required')
    if gui is None: import win32gui as gui
    if processes is None: import win32process as processes
    read_identity=_process_identity if read_identity is None else read_identity
    sleep=time.sleep if sleep is None else sleep
    report=dict(scope='EXACT_OWNED_CAM_INFORMATION_OK_V1',status='prepared',process_id=process_id,
        expected_creation_time=expected_creation_time,expected_executable=expected_executable,expected_title=TITLE,
        expected_text=expected_text,expected_main_title=expected_main_title,action=action,mechanism='windows_ui_helper',native_cam_api_used=False,
        COM_called=False,operation_lock_acquired=False,save_called=False,cancel_called=False,focus_changed=False,
        button_invocation_count=0,native_operation_success_verified=False,action_pending=False,
        post_returned=False,dismissal_confirmed=False,automatic_retry=False)
    last_digest=None
    def persist():
        nonlocal last_digest
        raw=json.dumps(report,ensure_ascii=False,allow_nan=False,indent=2).encode('utf-8')
        require(not path.is_symlink(),'Receipt became a symbolic link')
        if last_digest is None:
            with path.open('xb') as f:f.write(raw);f.flush();os.fsync(f.fileno())
        else:
            require(hashlib.sha256(path.read_bytes()).hexdigest()==last_digest,'Receipt changed outside this operation')
            temporary=path.with_name(path.name+'.pending.tmp')
            with temporary.open('xb') as f:f.write(raw);f.flush();os.fsync(f.fileno())
            os.replace(temporary,path)
        last_digest=hashlib.sha256(raw).hexdigest()
    def owned():
        got=read_identity(process_id)
        require(type(got)is dict and type(got.get('process_id'))is int and got['process_id']==process_id
            and got.get('alive')is True and type(got.get('create_time'))in(int,float) and got['create_time']==expected_creation_time
            and type(got.get('executable'))is str and ntpath.normcase(got['executable'])==ntpath.normcase(expected_executable),'Owned process identity changed')
        mains=[]
        def main_visit(handle,_):
            if processes.GetWindowThreadProcessId(handle)[1]==process_id and gui.IsWindowVisible(handle) and gui.GetClassName(handle)!='#32770' and gui.GetWindowText(handle)==expected_main_title:mains.append(handle)
            return True
        gui.EnumWindows(main_visit,None)
        require(len(mains)==1,'Exact owned main document window title missing or ambiguous')
        return dict(got,main_window_handle=mains[0],main_window_title=expected_main_title)
    def snapshot(handle):
        children=[]
        def child_visit(child,_):
            require(len(children)<32,'Unexpected informational control count')
            text=gui.GetWindowText(child);require(len(text)<=2000,'Unexpected control text length')
            children.append(dict(handle=child,text=text,window_class=gui.GetClassName(child),control_id=gui.GetDlgCtrlID(child),
                parent=gui.GetParent(child),process_id=processes.GetWindowThreadProcessId(child)[1],
                visible=bool(gui.IsWindowVisible(child)),enabled=bool(gui.IsWindowEnabled(child))))
            return True
        gui.EnumChildWindows(handle,child_visit,None)
        return dict(handle=handle,title=gui.GetWindowText(handle),window_class=gui.GetClassName(handle),
            process_id=processes.GetWindowThreadProcessId(handle)[1],visible=bool(gui.IsWindowVisible(handle)),
            enabled=bool(gui.IsWindowEnabled(handle)),controls=children)
    def button_for(prompt):
        if not(prompt['process_id']==process_id and prompt['window_class']=='#32770' and prompt['title']==TITLE and prompt['visible'] and prompt['enabled']):return None
        controls=prompt['controls']
        if any(c['process_id']!=process_id or c['parent']!=prompt['handle'] or c['window_class'].casefold()not in('button','static')for c in controls):return None
        if [c['text']for c in controls if c['window_class'].casefold()=='static' and c['text']]!=[expected_text]:return None
        buttons=[c for c in controls if c['window_class'].casefold()=='button']
        if len(buttons)!=1:return None
        b=buttons[0]
        return b if b['text']in OK_LABELS and b['visible'] and b['enabled'] and type(b['control_id'])is int and 0<b['control_id']<=65535 else None
    def collect():
        prompts=[];count=0
        def visit(handle,_):
            nonlocal count
            count+=1;require(count<=4096,'Unexpected top-level window count')
            if processes.GetWindowThreadProcessId(handle)[1]==process_id and gui.IsWindowVisible(handle) and gui.GetClassName(handle)=='#32770' and gui.GetWindowText(handle)==TITLE:
                require(len(prompts)<16,'Unexpected informational dialog count');prompts.append(snapshot(handle))
            return True
        gui.EnumWindows(visit,None)
        return prompts
    persist()
    try:
        report['process_identity_before']=owned();prompts=collect();report['prompts_before']=prompts
        candidates=[(p,button_for(p))for p in prompts if button_for(p)is not None]
        report['matching_prompt_count']=len(candidates)
        require(len(prompts)==len(candidates)==1,'Exactly one matching owned informational dialog required')
        prompt,button=candidates[0];owned()
        if action=='inspect':report.update(status='inspected',can_acknowledge=True);return report
        current=collect();require(current==prompts and snapshot(prompt['handle'])==prompt and gui.GetDlgItem(prompt['handle'],button['control_id'])==button['handle'],'Informational dialog changed before acknowledgement')
        report.update(status='dispatch_pending',action_pending=True,invocation=dict(dialog=prompt['handle'],button=button['handle'],command=button['control_id'],message='WM_COMMAND/BN_CLICKED'))
        persist();owned()
        require(snapshot(prompt['handle'])==prompt and gui.GetDlgItem(prompt['handle'],button['control_id'])==button['handle'],'Informational dialog changed after durable pending')
        report['button_invocation_count']=1
        gui.PostMessage(prompt['handle'],0x111,button['control_id'],button['handle'])
        report['post_returned']=True;persist()
        for index in range(21):
            report['process_identity_after']=owned()
            if not gui.IsWindow(prompt['handle']) or not gui.IsWindowVisible(prompt['handle']):
                after=collect();report['prompts_after']=after
                require(not any(button_for(p)is not None for p in after),'Matching informational dialog remains or was recreated')
                report.update(status='dismissed',dismissal_confirmed=True,action_pending=False);return report
            require(snapshot(prompt['handle'])==prompt,'Dialog identity changed after acknowledgement')
            if index<20:sleep(.1)
        raise ValueError('Dialog disappearance not confirmed; no retry')
    except Exception as exc:
        report.update(status='uncertain' if report['action_pending'] or report['button_invocation_count'] else 'blocked',
            issue=dict(type=type(exc).__name__,message=str(exc)[:1000]))
    finally:
        try:persist()
        except Exception as exc:report.update(status='uncertain',receipt_write_error=dict(type=type(exc).__name__,message=str(exc)[:1000]))
    return report
