"""Direct NUP controls. Workers never call Tk; outputs commit exclusively."""
from pathlib import Path
import os, queue, subprocess, sys, threading, time
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import engine, nup_tools as tools
from artwork import ArtworkSelection, ARTWORK_FILETYPES, IMAGE_EXTENSIONS
from crop_dialog import CropDialog
from nup_format import PRESETS, KINDS, Archive
from ui import BG,PANEL,TEXT,MUTED,Button,Entry,Check,Panel,Progress,ui_font,AmbientFrame,AmbientLabel

OPERATIONS=('Folder → NUP','NSP → NUP','NUP → Folder','NUP → NSP','Inspect / Verify')
INCLUDE_GROUPS={'Base':(0,),'Updates':(1,),'DLC':(2,3)}

def automatic_output(path,operation):
    """Place results beside the input; never overwrite a previous result."""
    source=Path(path).absolute()
    if source.name.lower() in ('exefs','romfs') and operation==OPERATIONS[0]:source=source.parent
    if operation==OPERATIONS[4]:return ''
    stem=source.name if operation==OPERATIONS[0] else source.stem
    suffix='.nup' if operation in OPERATIONS[:2] else ('-NSP' if operation==OPERATIONS[3] else '-extracted')
    candidate=source.parent/(stem+suffix);number=2
    while candidate.exists():
        candidate=source.parent/(f'{stem} ({number})'+suffix);number+=1
    return str(candidate)

class NupPanel(AmbientFrame):
    def __init__(self,parent):
        super().__init__(parent,bg=BG);self.app=parent;self.motion=parent.motion
        self.events=queue.Queue();self.cancel_event=threading.Event();self.busy=False;self.last_output=None;self.catalog=[];self.prepared=None;self.catalog_source=None
        self.operation=tk.StringVar(self,value=OPERATIONS[0]);self.input=tk.StringVar(self);self.output=tk.StringVar(self)
        self.preset=tk.StringVar(self,value='Balanced');self.large_raw=tk.BooleanVar(self,value=True);self.verify=tk.BooleanVar(self,value=True)
        self.latest_snapshot=tk.BooleanVar(self,value=True)
        self.includes={name:tk.BooleanVar(self,value=True) for name in ('Base','Updates','DLC')}
        self.title_text=tk.StringVar(self);self.art_selection=None;self.art_bytes=None;self._art_editor=None
        self.art_name=tk.StringVar(self,value='Optional · square cover');self.reveal_height=0
        self.status=tk.StringVar(self,value='Choose a folder or package to begin.')
        self.destination=tk.StringVar(self,value='Saved beside your source · existing outputs are kept')
        self.controls=[];self._layout();self.job=self.after(90,self.poll)
        self.input.trace_add('write',self.input_changed)

    def label(self,parent,text=None,variable=None,color=MUTED,size=9,**kw):
        cls=AmbientLabel if isinstance(parent,AmbientFrame) else tk.Label
        return cls(parent,text=text,textvariable=variable,bg=parent.cget('bg'),fg=color,font=ui_font(size),**kw)

    def _layout(self):
        modes=AmbientFrame(self);modes.pack(fill='x',padx=20,pady=(0,10));self.op_buttons=[]
        for i,op in enumerate(OPERATIONS):
            modes.grid_columnconfigure(i,weight=1,uniform='modes')
            button=Button(modes,op,lambda value=op:self.choose_operation(value),self.motion,width=120,height=39,quiet=True)
            button.grid(row=0,column=i,sticky='ew',padx=(0,6) if i<4 else 0);self.op_buttons.append(button)
        area=AmbientFrame(self);area.pack(fill='both',expand=True,padx=20,pady=(0,12));self.area=area
        area.grid_columnconfigure(0,weight=1);area.grid_columnconfigure(1,minsize=310);area.grid_rowconfigure(1,weight=1)
        source=Panel(area,height=150,fluid_resize=True);source.grid(row=0,column=0,sticky='nsew',padx=(0,12),pady=(0,12));self.source_panel=source
        self.app.heading(source.inner,'NUP source','package-folder')
        row=tk.Frame(source.inner,bg=PANEL);row.pack(fill='x')
        self.input_entry=Entry(row,textvariable=self.input,placeholder='Folder, NSP or NUP path')
        self.input_entry.pack(side='left',fill='x',expand=True);self.input_entry.bind('<Return>',lambda e:self.scan())
        self.browse_button=Button(row,'Browse',self.pick_input,self.motion,width=100,height=41,kind='folder');self.browse_button.pack(side='right',padx=(8,0))
        self.controls.extend((self.input_entry,self.browse_button))
        self.label(source.inner,'Drop a source here · original files stay untouched').pack(anchor='w',pady=(7,0))
        # Animate a clipped viewport and its card together to keep layout fluid.
        self.reveal=tk.Frame(source.inner,bg=PANEL,height=0);self.reveal.pack(fill='x');self.reveal.pack_propagate(False)
        self.presentation_row=tk.Frame(self.reveal,bg=PANEL);self.presentation_row.place(x=0,y=14,relwidth=1)
        self.presentation_row.grid_columnconfigure(0,weight=1)
        self.label(self.presentation_row,'Title').grid(row=0,column=0,sticky='w',pady=(9,5))
        self.label(self.presentation_row,'Artwork').grid(row=0,column=1,columnspan=2,sticky='w',padx=(10,0),pady=(9,5))
        self.title_entry=Entry(self.presentation_row,textvariable=self.title_text,placeholder='Detected automatically');self.title_entry.grid(row=1,column=0,sticky='ew')
        self.art_button=Button(self.presentation_row,'Add cover',self.pick_art,self.motion,width=128,height=39,kind='crop');self.art_button.grid(row=1,column=1,padx=(10,0))
        self.clear_art_button=Button(self.presentation_row,'Clear',self.clear_art,self.motion,width=58,height=39,quiet=True);self.clear_art_button.grid(row=1,column=2,padx=(4,0))
        self.label(self.presentation_row,variable=self.art_name,size=8).grid(row=2,column=0,columnspan=3,sticky='w',pady=(4,0))
        self.controls.extend((self.title_entry,self.art_button,self.clear_art_button))
        packages=Panel(area,fluid_resize=True);packages.grid(row=1,column=0,sticky='nsew',padx=(0,12))
        self.app.heading(packages.inner,'Include in output','game-details')
        self.include_area=tk.Frame(packages.inner,bg=PANEL)
        kinds=tk.Frame(self.include_area,bg=PANEL);kinds.pack(fill='x',pady=(0,10));self.include_row=kinds;self.include_checks=[]
        for i,(name,var) in enumerate(self.includes.items()):
            kinds.grid_columnconfigure(i,weight=1,uniform='kinds')
            control=Check(kinds,name,var);control.configure(width=95);control.grid(row=0,column=i,sticky='ew')
            self.include_checks.append(control);self.controls.append(control);var.trace_add('write',lambda *a:self.selection_changed())
        self.snapshot_options=tk.Frame(self.include_area,bg=PANEL)
        self.snapshot_check=Check(self.snapshot_options,'Keep latest game snapshot only (smaller)',self.latest_snapshot,kind='package-folder');self.snapshot_check.pack(anchor='w',fill='x')
        self.snapshot_hint=self.label(self.snapshot_options,'Merge base + newest update; keep base-only files.',justify='left');self.snapshot_hint.pack(anchor='w',pady=(4,10))
        self.report=tk.Text(packages.inner,bg=PANEL,fg=TEXT,insertbackground=TEXT,relief='flat',bd=0,highlightthickness=0,font=ui_font(10),wrap='word',height=6,state='disabled')
        scroll=ttk.Scrollbar(packages.inner,command=self.report.yview);scroll.pack(side='right',fill='y');self.report.configure(yscrollcommand=scroll.set);self.report.pack(fill='both',expand=True)
        self.report_text('Choose a source to see its packages.\n\nBase, Updates and DLC control what goes into the output. Updates are merged only when selected.\n\nUse Inspect / Verify to check a NUP without creating another copy.')
        options=Panel(area);options.grid(row=0,column=1,rowspan=2,sticky='nsew')
        self.app.heading(options.inner,'Build options','save-output')
        self.label(options.inner,'Compression').pack(anchor='w',pady=(0,6))
        presets=tk.Frame(options.inner,bg=PANEL);presets.pack(fill='x');self.preset_buttons=[]
        for i,name in enumerate(PRESETS):
            presets.grid_columnconfigure(i,weight=1,uniform='presets')
            button=Button(presets,name,lambda value=name:self.choose_preset(value),self.motion,width=80,height=36,quiet=True)
            button.grid(row=0,column=i,sticky='ew',padx=(0,4) if i<2 else 0);self.preset_buttons.append(button)
        self.label(options.inner,'Fast 1 · Balanced 3 · Smaller 9').pack(anchor='w',pady=(5,14))
        self.large_check=Check(options.inner,'Keep files > 256 MiB raw',self.large_raw,kind='package-folder');self.large_check.pack(anchor='w',fill='x')
        self.label(options.inner,'Recommended for Eglantine: avoids expanding compressed large files to temporary disk storage.',wraplength=275,justify='left').pack(anchor='w',pady=(6,14))
        self.verify_check=Check(options.inner,'Verify after building',self.verify,kind='verify');self.verify_check.pack(anchor='w',fill='x')
        self.controls.extend((self.verify_check,self.large_check,self.snapshot_check))
        self.label(options.inner,'Extraction always checks hashes. Inspect / Verify uses this option for full verification.',wraplength=275,justify='left').pack(anchor='w',pady=(6,14))
        self.label(options.inner,'Output · automatic',color=TEXT,size=10).pack(anchor='w',pady=(2,6))
        self.output_label=self.label(options.inner,variable=self.destination,wraplength=275,justify='left',size=9);self.output_label.pack(anchor='w',pady=(0,14))
        self.label(options.inner,'NUP compatibility',color='#b9d8ff',size=10).pack(anchor='w',pady=(2,6))
        self.label(options.inner,'Plaintext inputs only. Requires a NUP-capable emulator.\n\nDLC mounting depends on the emulator; convert DLC to NSP to install it where needed.',wraplength=275,justify='left').pack(anchor='w')
        self.panels=[source,packages,options]
        self.progress=Progress(self,self.motion);self.progress.pack(fill='x')
        footer=AmbientFrame(self);footer.pack(fill='x',padx=24,pady=(12,18))
        self.label(footer,variable=self.status,wraplength=360,justify='left').pack(side='left',fill='x',expand=True)
        self.start_button=Button(footer,'Run operation',self.start,self.motion,width=160,height=47,primary=True,kind='build');self.start_button.pack(side='right',padx=(10,0))
        self.cancel_button=Button(footer,'Cancel',self.cancel,self.motion,width=100,height=47,kind='cancel',state='disabled');self.cancel_button.pack(side='right',padx=(10,0))
        self.open_button=Button(footer,'Open output',self.open_output,self.motion,width=148,height=47,kind='open-output',state='disabled');self.open_button.pack(side='right',padx=(10,0))
        self.changed()

    def report_text(self,text):
        self.report.configure(state='normal');self.report.delete('1.0','end');self.report.insert('1.0',text);self.report.configure(state='disabled')
    def source_key(self):return (self.operation.get(),self.input.get().strip())
    def input_changed(self,*args):
        self.prepared=None;self.catalog=[];self.catalog_source=None;self.update_destination();self.update_controls()
        if not self.busy:
            self.status.set('Press Enter to inspect this source.' if self.input.get().strip() else 'Choose a folder or package to begin.')
            self.report_text('Choose and inspect a source to see its available Base, Updates and DLC content.')
    def update_destination(self):
        value=automatic_output(self.input.get().strip(),self.operation.get()) if self.input.get().strip() else ''
        self.output.set(value)
        self.destination.set(('Beside source · '+Path(value).name) if value else ('No output file · source is checked in place' if self.operation.get()==OPERATIONS[4] else 'Saved beside your source · existing outputs are kept'))
    def choose_operation(self,value):
        if self.busy:return
        self.operation.set(value);self.changed()
        path=Path(self.input.get()) if self.input.get().strip() else None
        if path and ((value==OPERATIONS[0] and path.is_dir()) or (value==OPERATIONS[1] and path.suffix.lower()=='.nsp') or (value in OPERATIONS[2:] and path.suffix.lower()=='.nup')):self.scan()
    def choose_preset(self,value):self.preset.set(value);self.update_controls()
    def changed(self):
        if self.busy:return
        self.catalog=[];self.catalog_source=None;self.prepared=None;self.update_destination();self.update_controls()
        def step(height):
            self.reveal_height=height
            pixels=round(height)
            if getattr(self,'_reveal_pixels',None)!=pixels:
                self._reveal_pixels=pixels;self.reveal.configure(height=pixels);self.source_panel.configure(height=150+pixels)
            # Keep text and native editors steady while their viewport opens.
            # Moving both the row and its clipping edge caused visible judder.
            self.presentation_row.place_configure(y=0)
        self.motion.to((id(self),'presentation'),self.reveal_height,104 if self.operation.get()==OPERATIONS[0] else 0,.42,step,
                       easing=lambda t:t*t*t*(t*(t*6-15)+10))
    def selected_kinds(self):
        available=self.available_kinds()
        return {kind for name,var in self.includes.items() if var.get() for kind in INCLUDE_GROUPS[name] if kind in available}
    def available_kinds(self):
        return {KINDS.index(p['kind']) for p in self.catalog} if self.catalog_source==self.source_key() else set()
    def refresh_includes(self):
        available=self.available_kinds()
        visible=bool(available) and self.operation.get()!=OPERATIONS[4]
        if visible:self.include_area.pack(fill='x',before=self.report)
        else:self.include_area.pack_forget()
        for col,((name,kinds),control) in enumerate(zip(INCLUDE_GROUPS.items(),self.include_checks)):
            present=bool(available.intersection(kinds))
            self.include_row.grid_columnconfigure(col,weight=int(present),uniform='kinds' if present else '')
            if present:control.grid()
            else:control.grid_remove()
        if visible and self.operation.get()==OPERATIONS[0] and 1 in available:
            self.snapshot_options.pack(fill='x')
            self.snapshot_hint.configure(text='Merge base + newest update; keep base-only files.' if 0 in self.selected_kinds() else 'Keep the newest update snapshot; no base fallback.')
        else:self.snapshot_options.pack_forget()
    def selection_changed(self):
        if not self.busy:
            self.update_controls()
            if self.catalog:self.status.set(f'{sum(KINDS.index(p["kind"]) in self.selected_kinds() for p in self.catalog)} package(s) selected · originals unchanged.')
    def update_controls(self):
        packing=self.operation.get() in OPERATIONS[:2];folder=self.operation.get()==OPERATIONS[0]
        self.refresh_includes()
        for op,button in zip(OPERATIONS,self.op_buttons):button.configure(state='disabled' if self.busy else 'normal');button.set_selected(op==self.operation.get())
        for name,button in zip(PRESETS,self.preset_buttons):button.configure(state='normal' if packing and not self.busy else 'disabled');button.set_selected(name==self.preset.get())
        self.large_check.configure(state='normal' if packing and not self.busy else 'disabled')
        self.snapshot_check.configure(state='normal' if folder and not self.busy and self.includes['Updates'].get() else 'disabled')
        for control in self.include_checks:control.configure(state='disabled' if self.busy or self.operation.get()==OPERATIONS[4] else 'normal')
        for control in (self.title_entry,self.art_button,self.clear_art_button):control.configure(state='normal' if folder and not self.busy else 'disabled')
    def pick_input(self):
        if self.operation.get()==OPERATIONS[0]:path=filedialog.askdirectory(parent=self,title='Choose extracted game or base/updates/dlc bundle')
        else:path=filedialog.askopenfilename(parent=self,title='Choose package',filetypes=[('NSP packages','*.nsp *.NSP'),('All files','*')] if self.operation.get()==OPERATIONS[1] else [('NUP archives','*.nup *.NUP'),('All files','*')])
        if path:self.input.set(path);self.scan()
    def receive_drop(self,path):
        if self.busy or self._art_editor is not None:return
        path=Path(path)
        if path.suffix.lower() in IMAGE_EXTENSIONS:
            if self.operation.get()==OPERATIONS[0]:self.set_art(path)
            else:self.status.set('Artwork is available for Folder → NUP.')
            return
        if path.is_dir():self.operation.set(OPERATIONS[0])
        elif path.suffix.lower()=='.nsp':self.operation.set(OPERATIONS[1])
        elif path.suffix.lower()=='.nup':
            if self.operation.get() not in OPERATIONS[2:]:self.operation.set(OPERATIONS[4])
        else:self.status.set('Drop an extracted folder, .nsp or .nup.');return
        self.input.set(str(path));self.changed();self.scan()
    def pick_art(self):
        if self.busy or self._art_editor is not None:return
        if self.art_selection:self.set_art(self.art_selection.path,self.art_selection)
        else:
            path=filedialog.askopenfilename(parent=self,title='Choose NUP artwork',filetypes=ARTWORK_FILETYPES)
            if path:self.set_art(Path(path))
    def set_art(self,path,selection=None):
        try:
            self._art_editor=CropDialog(self.app,selection or ArtworkSelection(Path(path)))
            result=self._art_editor.show()
            if result is not None:
                data=engine.artwork_bytes(result);self.art_selection=result;self.art_bytes=data
                self.art_name.set('256 × 256 · '+Path(path).name[:42]);self.art_button.configure(text='Edit cover')
        except Exception as error:messagebox.showerror('Cannot crop artwork',str(error),parent=self.app)
        finally:self._art_editor=None
    def clear_art(self):
        if self.busy:return
        self.art_selection=None;self.art_bytes=None;self.art_name.set('Optional · square cover');self.art_button.configure(text='Add cover')
    def set_busy(self,value):
        self.busy=value
        for c in self.controls+[self.start_button]:c.configure(state='disabled' if value else 'normal')
        self.cancel_button.configure(state='normal' if value else 'disabled');self.update_controls()
    def worker(self,call,kind):
        self.set_busy(True);self.cancel_event.clear();self.progress['value']=0;self.last_progress=0;last=[0]
        def notify(stage,value):
            now=time.monotonic()
            if now-last[0]>.1 or value>=100:self.events.put(('progress',(stage,value)));last[0]=now
        def run():
            try:self.events.put((kind,call(notify)))
            except InterruptedError:self.events.put(('cancelled',None))
            except Exception as error:self.events.put(('error',str(error)))
        threading.Thread(target=run,daemon=True).start()
    def scan(self):
        if self.busy or not self.input.get().strip():return
        path=self.input.get().strip();op=self.operation.get();source_key=self.source_key();self.status.set('Inspecting source…')
        self.catalog=[];self.catalog_source=None;self.prepared=None
        def call(notify):
            if op==OPERATIONS[0]:
                prepared=tools.prepare_folder(path,self.cancel_event,notify);packages=prepared.packages
                return {'packages_info':[{'index':i,'title_id':f'{p.title_id:016X}','kind':KINDS[p.kind],'version':p.version,'files':len(p.files)} for i,p in enumerate(packages)],'uncompressed':sum(s.size for p in packages for s in p.files.values()),'_prepared':prepared}
            if op==OPERATIONS[1]:
                with tools.nsp_packages(path,self.cancel_event,notify,deep=False) as packages:return {'packages_info':[{'index':i,'title_id':f'{p.title_id:016X}','kind':KINDS[p.kind],'version':p.version,'files':len(p.files)} for i,p in enumerate(packages)],'validation':'Package index only; full source integrity checked during conversion.'}
            return tools.inspect(path,cancel=self.cancel_event)
        def indexed(notify):
            data=call(notify);data['_source_key']=source_key;return data
        self.worker(indexed,'scan')
    def start(self):
        if self.busy or self._art_editor is not None:return
        path=self.input.get().strip();op=self.operation.get();verify=self.verify.get();kinds=self.selected_kinds()
        if not path:self.status.set('Choose an input first.');return
        if op!=OPERATIONS[4] and self.catalog_source!=self.source_key():self.scan();return
        if op!=OPERATIONS[4] and not kinds:self.status.set('Select at least one of Base, Updates or DLC.');return
        self.update_destination();output=self.output.get()
        level=PRESETS[self.preset.get()];large=self.large_raw.get();latest=self.latest_snapshot.get();prepared=self.prepared
        title=self.title_text.get();artwork=self.art_bytes;self.status.set('Preparing operation…')
        candidate=Path(path).resolve()
        if candidate.name.lower() in ('exefs','romfs'):candidate=candidate.parent
        if prepared is not None and prepared.root!=candidate:prepared=None
        def call(notify):
            common={'notify':notify,'cancel':self.cancel_event}
            if op==OPERATIONS[0]:return tools.pack_folder(path,output,level=level,large_raw=large,latest_snapshot=latest,prepared=prepared,verify=verify,include_kinds=kinds,title=title,artwork=artwork,**common)
            if op==OPERATIONS[1]:return tools.nsp_to_nup(path,output,level=level,large_raw=large,verify=verify,include_kinds=kinds,**common)
            if op==OPERATIONS[2]:
                with Archive(path,self.cancel_event) as archive:selection=[i for i,p in enumerate(archive.packages) if p.kind in kinds]
                return tools.extract(path,output,selection=selection,**common)
            if op==OPERATIONS[3]:return tools.nup_to_nsp(path,output,include_kinds=kinds,verify=verify,**common)
            return tools.inspect(path,verify=verify,**common)
        self.worker(call,'done')
    def show_report(self,data):
        lines=[]
        for p in data.get('packages_info',[]):lines.append(f'{p["index"]+1}. {p["kind"].upper()}  ·  {p["title_id"]}\n    Version {p["version"]:,}  ·  {p["files"]:,} files'+(('  ·  '+p['title']) if p.get('title') else ''))
        for key,label in (('uncompressed','Original file bytes'),('stored','Unique stored extents'),('archive_size','Archive size'),('size','Output size'),('source_size','Original file bytes'),('saved_bytes','Bytes saved')):
            if key in data:lines.append(f'{label}: {data[key]:,} bytes ({data[key]/1024**2:.2f} MiB)')
        if 'compressed_files' in data:lines.append(f'Compressed: {data["compressed_files"]:,}  ·  Raw: {data["raw_files"]:,}  ·  Unique extents: {data["unique_extents"]:,}')
        if 'source_size' in data and data['source_size']:lines.append(f'Size change: {(1-data["size"]/data["source_size"])*100:.1f}% smaller (includes container overhead)')
        if 'verified' in data:lines.append('Integrity: '+('verified' if data['verified'] else 'structure checked / full readback skipped'))
        if 'output' in data:lines.append('\n'+data['output'])
        if 'validation' in data:lines.append(data['validation'])
        if data.get('latest_snapshot'):lines.append('Latest selected game snapshot · superseded versions omitted; selected base-only files retained.')
        if 'omitted_version_bytes' in data:lines.append(f'Superseded data omitted: {data["omitted_version_bytes"]/1024**2:.2f} MiB')
        if 'duplicate_files_skipped' in data:lines.append(f'Duplicate files reused without compression: {data["duplicate_files_skipped"]:,}')
        self.report_text('\n\n'.join(lines))
    def poll(self):
        try:
            while True:
                kind,data=self.events.get_nowait()
                if kind=='progress':
                    stage,value=data;self.last_progress=max(self.last_progress,value);self.progress['value']=self.last_progress
                    if not self.cancel_event.is_set():self.status.set(f'{stage} · {value:.0f}%')
                elif kind in ('done','scan'):
                    self.set_busy(False)
                    if kind=='scan' and data['_source_key']!=self.source_key():
                        self.status.set('Source changed · inspect it again.');continue
                    self.show_report(data)
                    if kind=='scan':
                        self.prepared=data.get('_prepared');self.catalog=data.get('packages_info',[]);self.catalog_source=data['_source_key']
                        self.update_controls();self.status.set(f'{len(self.catalog)} package(s) found · choose what to include.')
                    else:
                        self.progress['value']=100;self.status.set('Operation complete · '+('integrity verified' if data.get('verified') else 'verification skipped'))
                        self.last_output=Path(data['output']);self.open_button.configure(state='normal')
                elif kind=='error':self.set_busy(False);self.status.set(data)
                elif kind=='cancelled':self.set_busy(False);self.status.set('Cancelled · unfinished output removed; sources unchanged.')
        except queue.Empty:pass
        self.job=self.after(90,self.poll)
    def cancel(self):self.cancel_event.set();self.cancel_button.configure(state='disabled');self.status.set('Cancelling and cleaning up…')
    def open_output(self):
        if not self.last_output:return
        path=self.last_output if self.last_output.is_dir() else self.last_output.parent
        try:
            if sys.platform=='win32':os.startfile(str(path))
            else:subprocess.Popen(['xdg-open',str(path)])
        except OSError as e:self.status.set(str(e))
    def close(self):
        if self._art_editor is not None and self._art_editor.winfo_exists():self._art_editor.close()
        if self.busy:self.cancel();return False
        if self.job:self.after_cancel(self.job);self.job=None
        return True
