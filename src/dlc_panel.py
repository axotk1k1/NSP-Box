"""Extracted DLC tab. Packaging never edits a game or an emulator profile."""
from pathlib import Path
import os, queue, subprocess, sys, threading, time
import tkinter as tk
from tkinter import filedialog, messagebox
import dlc
from ui import BG, PANEL, TEXT, MUTED, Button, Entry, Combo, Check, Panel, Progress, ui_font, AmbientFrame, AmbientLabel


class DlcPanel(AmbientFrame):
    def __init__(self, parent):
        super().__init__(parent, bg=BG)
        self.app = parent
        self.motion = parent.motion
        self.events = queue.Queue()
        self.cancel_event = threading.Event()
        self.busy = False
        self.snapshots = []
        self.base_info = None
        self.last_output = None
        self.folder = tk.StringVar(self)
        self.base_game = tk.StringVar(self)
        self.title_id = tk.StringVar(self)
        self.version = tk.StringVar(self, value='0')
        self.choice = tk.StringVar(self)
        self.output = tk.StringVar(self)
        self.verify = tk.BooleanVar(self, value=True)
        self.mapping = tk.StringVar(self, value='The original DLC title ID is detected from its folder name.')
        self.status = tk.StringVar(self, value='Select an extracted DLC folder to begin.')
        self.controls = []
        self._layout()
        self.job = self.after(90, self.poll)

    def label(self, parent, text=None, variable=None, size=10, color=TEXT, **kwargs):
        label_type = AmbientLabel if isinstance(parent,AmbientFrame) else tk.Label
        return label_type(parent, text=text, textvariable=variable, bg=parent.cget('bg'), fg=color,
                        font=ui_font(size), bd=0, **kwargs)

    def path_field(self, parent, variable, placeholder, command):
        row = tk.Frame(parent, bg=PANEL); row.pack(fill='x', pady=(6, 8))
        entry = Entry(row, textvariable=variable, placeholder=placeholder)
        entry.pack(side='left', fill='x', expand=True)
        button = Button(row, 'Browse', command, self.motion, width=106, height=41, kind='folder')
        button.pack(side='right', padx=(9, 0))
        self.controls.extend([entry, button])
        return entry

    def _layout(self):
        area = AmbientFrame(self); area.pack(fill='both', expand=True, padx=20, pady=(0, 10))
        area.grid_columnconfigure(0, weight=1); area.grid_columnconfigure(1, minsize=300)
        area.grid_rowconfigure(0, weight=1, minsize=190)
        area.grid_rowconfigure(1, minsize=165); area.grid_rowconfigure(2, minsize=145)
        source = Panel(area); source.grid(row=0, column=0, sticky='nsew', padx=(0, 12), pady=(0, 10))
        self.app.heading(source.inner, 'DLC files', 'dlc')
        self.folder_entry = self.path_field(source.inner, self.folder, 'Choose dlc, title/version, or romfs folder', self.pick_folder)
        self.folder_entry.bind('<Return>', lambda event: self.scan())
        row = tk.Frame(source.inner, bg=PANEL); row.pack(fill='x', pady=(2, 5))
        self.combo = Combo(row, textvariable=self.choice, state='readonly')
        self.combo.pack(side='left', fill='x', expand=True)
        self.combo.bind('<<ComboboxSelected>>', lambda event: self.select())
        self.scan_button = Button(row, 'Scan folder', self.scan, self.motion, width=116, height=40)
        self.scan_button.pack(side='right', padx=(9, 0)); self.controls.append(self.scan_button)
        self.label(source.inner, 'RomFS-only DLC · no ExeFS or main.npdm required', size=9, color=MUTED).pack(anchor='w', pady=(5, 0))
        details = Panel(area); details.grid(row=1, column=0, sticky='nsew', padx=(0,12), pady=(0,10))
        self.app.heading(details.inner, 'DLC details', 'game-details')
        row = tk.Frame(details.inner, bg=PANEL); row.pack(fill='x')
        for col, (caption, variable) in enumerate([('Original DLC title ID', self.title_id), ('DLC version (numeric)', self.version)]):
            row.grid_columnconfigure(col, weight=1)
            field = tk.Frame(row, bg=PANEL); field.grid(row=0, column=col, sticky='ew', padx=(0,12) if col == 0 else 0)
            self.label(field, caption, color=MUTED, size=9).pack(anchor='w', pady=(0,5))
            entry = Entry(field, textvariable=variable); entry.pack(fill='x'); self.controls.append(entry)
        self.label(details.inner, variable=self.mapping, color=MUTED, size=9, anchor='w').pack(fill='x', pady=(8,0))
        output = Panel(area); output.grid(row=2, column=0, sticky='nsew', padx=(0,12))
        self.app.heading(output.inner, 'Output', 'file')
        row = tk.Frame(output.inner, bg=PANEL); row.pack(fill='x')
        self.output_entry = Entry(row, textvariable=self.output, placeholder='Save a separate DLC package')
        self.output_entry.pack(side='left', fill='x', expand=True)
        self.save_button = Button(row, '', self.pick_output, self.motion, kind='save-output', width=45, height=41)
        self.save_button.pack(side='right', padx=(8,0)); self.controls.extend([self.output_entry,self.save_button])
        self.verify_check = Check(output.inner, 'Verify after building', self.verify, kind='verify')
        self.verify_check.pack(anchor='w', pady=(10,0)); self.controls.append(self.verify_check)
        info = Panel(area); info.grid(row=0, column=1, rowspan=3, sticky='nsew')
        self.panels = [source, details, output, info]
        self.app.heading(info.inner, 'Base game & setup', 'game')
        self.label(info.inner, 'Base NSP (optional)', color=MUTED, size=9).pack(anchor='w')
        self.base_entry = self.path_field(info.inner, self.base_game, 'Check the base-game mapping', self.pick_base)
        self.base_entry.bind('<Return>', lambda event: self.scan())
        self.label(info.inner, 'Install DLC', size=12, color=TEXT).pack(anchor='w', pady=(12,8))
        self.label(info.inner, '1. Build the DLC package.\n\n'
                   '2. In the emulator, use File → Install Files to NAND (wording varies). Select the DLC NSP.\n\n'
                   '3. Open the base game’s Properties → Add-ons and enable the DLC. Restart the game.\n\n'
                   'DLC packages are add-ons, not bootable games.\n\n'
                   'The dump needs the game’s actual DLC data and original title ID. Packaging cannot add missing emulator services or guarantee the game detects it.',
                   color=MUTED, size=10, justify='left', wraplength=264).pack(anchor='w')
        self.label(info.inner, 'Minimal add-on metadata is generated. Original required-game-version information is not available in a RomFS-only dump. Use the matching game update.',
                   color='#adc8e8', size=9, wraplength=264, justify='left').pack(anchor='w', pady=(14,0))
        self.progress = Progress(self, self.motion); self.progress.pack(fill='x')
        footer = AmbientFrame(self); footer.pack(fill='x', padx=24, pady=(14,18))
        self.label(footer, variable=self.status, color=MUTED, size=9, wraplength=430, justify='left').pack(side='left', fill='x', expand=True)
        self.build_button = Button(footer, 'Build DLC NSP', self.start, self.motion, width=163, height=47, primary=True, kind='build')
        self.build_button.pack(side='right', padx=(10,0))
        self.cancel_button = Button(footer, 'Cancel', self.cancel, self.motion, width=105, height=47, kind='cancel', state='disabled')
        self.cancel_button.pack(side='right', padx=(10,0))
        self.open_button = Button(footer, 'Open output folder', self.open_output, self.motion, width=190, height=47, kind='open-output', state='disabled')
        self.open_button.pack(side='right', padx=(10,0))

    def pick_folder(self):
        folder = filedialog.askdirectory(parent=self, title='Choose extracted DLC folder')
        if folder:
            self.folder.set(folder); self.title_id.set(''); self.scan()

    def pick_base(self):
        path = filedialog.askopenfilename(parent=self, title='Choose the base-game NSP', filetypes=[('Game packages','*.nsp *.NSP'),('All files','*')])
        if path:
            self.base_game.set(path)
            if self.folder.get().strip(): self.scan()

    def pick_output(self):
        kind = 'NSP'; current = Path(self.output.get()) if self.output.get() else None
        path = filedialog.asksaveasfilename(parent=self, title='Save DLC '+kind, defaultextension='.'+kind.lower(),
                initialdir=str(current.parent) if current else None, initialfile=current.name if current else 'DLC.'+kind.lower(),
                filetypes=[(kind+' package','*.'+kind.lower())], confirmoverwrite=False)
        if path: self.output.set(path)

    def set_busy(self, value, cancellable=False):
        self.busy = value
        for c in self.controls + [self.build_button]: c.configure(state='disabled' if value else 'normal')
        for c in (self.combo,): c.configure(state='disabled' if value else 'readonly')
        self.cancel_button.configure(state='normal' if value and cancellable else 'disabled')

    def scan(self):
        if self.busy or not self.folder.get().strip(): return
        folder, tid, base = self.folder.get().strip(), self.title_id.get().strip(), self.base_game.get().strip()
        self.snapshots=[]; self.combo['values']=(); self.choice.set(''); self.base_info=None
        self.set_busy(True); self.status.set('Scanning extracted DLC and base-game headers…')
        def worker():
            try:
                items = dlc.find_snapshots(folder, tid or None)
                info = dlc.base_game_info(base) if base else None
                self.events.put(('scan', (items,info)))
            except Exception as e: self.events.put(('error',str(e)))
        threading.Thread(target=worker,daemon=True).start()

    def select(self):
        i = self.combo.current()
        if not 0 <= i < len(self.snapshots): return
        s = self.snapshots[i]; self.title_id.set(f'{s.title_id:016X}'); self.version.set(str(s.version))
        self.mapping.set(f'Base {s.base_id:016X}  ·  DLC index {s.title_id & 0x7ff}')
        name = (self.base_info or {}).get('title', 'Game')
        name = ''.join('_' if c in '<>:"/\\|?*' else c for c in name)[:90].rstrip('. ')
        self.output.set(str(s.root.parent/(f'{name} DLC [{s.title_id:016X}].nsp')))
        if self.base_info:
            try: dlc.validate_base(s,self.base_info)
            except ValueError as e: self.status.set(str(e)); return
        self.status.set('DLC found · '+('base-game mapping checked.' if self.base_info else 'base-game mapping not checked.'))

    def start(self):
        if self.busy: return
        i = self.combo.current()
        if not 0 <= i < len(self.snapshots):
            messagebox.showinfo('Choose DLC','Select and scan an extracted DLC folder first.',parent=self); return
        try:
            original = self.snapshots[i]
            tid = dlc.parse_id(self.title_id.get())
            if tid != original.title_id:
                raise ValueError('DLC ID changed. Scan again to validate it against the source folder.')
            s = dlc.DlcSnapshot(original.root,tid,dlc.parse_version(self.version.get()),original.label)
        except ValueError as e:
            self.status.set(str(e)); return
        if not self.output.get().strip(): self.pick_output(); return
        output, kind, verify, base = Path(self.output.get()), 'nsp', self.verify.get(), self.base_game.get().strip()
        self.set_busy(True,True); self.cancel_event.clear(); self.progress['value']=0; self.last_progress=0
        self.status.set('Preparing DLC package…'); self.open_button.configure(state='disabled')
        def worker():
            last = [0]
            def notify(stage,value):
                now=time.monotonic()
                if now-last[0] > .12 or value >= 100:
                    self.events.put(('progress',(stage,value))); last[0]=now
            try: self.events.put(('done',dlc.build(s,output,kind,verify,base or None,notify,self.cancel_event)))
            except InterruptedError: self.events.put(('cancelled',None))
            except Exception as e: self.events.put(('error',str(e)))
        threading.Thread(target=worker,daemon=True).start()

    def cancel(self):
        self.cancel_event.set(); self.cancel_button.configure(state='disabled'); self.status.set('Cancelling and removing unfinished DLC…')

    def poll(self):
        try:
            while True:
                kind, data = self.events.get_nowait()
                if kind == 'scan':
                    self.set_busy(False); self.snapshots,self.base_info=data
                    self.combo['values']=[f'{s.title_id:016X} · v{s.version} · {s.label}' for s in self.snapshots]
                    self.combo.current(0); self.select()
                elif kind == 'progress':
                    stage,value=data; self.last_progress=max(self.last_progress,value); self.progress['value']=self.last_progress
                    if not self.cancel_event.is_set(): self.status.set(f'{stage} · {value:.0f}%')
                elif kind == 'done':
                    self.set_busy(False); self.progress['value']=100; self.last_output=Path(data['output'])
                    self.open_button.configure(state='normal')
                    self.status.set(f'DLC {data["output_format"]} ready · {data["size"]/1e9:.2f} GB · '+('verified' if data['verified'] else 'verification skipped')+'\nInstall through the emulator, then launch the base game.')
                elif kind == 'cancelled':
                    self.set_busy(False); self.status.set('Build cancelled. Unfinished file removed.')
                elif kind == 'error':
                    self.set_busy(False); self.status.set(data)
        except queue.Empty: pass
        self.job=self.after(90,self.poll)

    def open_output(self):
        if self.last_output:
            try:
                if sys.platform=='win32': os.startfile(str(self.last_output.parent))
                else: subprocess.Popen(['xdg-open',str(self.last_output.parent)])
            except OSError as e: self.status.set(str(e))

    def close(self):
        if self.busy:
            self.cancel(); return False
        if self.job: self.after_cancel(self.job); self.job=None
        return True
