"""Native Windows/macOS desktop GUI for local clinical-note PHI redaction."""
from pathlib import Path
import os
import queue
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from tkinter.scrolledtext import ScrolledText
from datetime import datetime

from deid_core import Detector, SetupError, BatchError, Cancelled, column_names, records, run_batch, block_network

BASE = Path(__file__).resolve().parent
SAMPLE = 'Patient: Jane Smith\nMRN: AB1234567\nDOB: 03/12/1980\nAddress: 123 Main Street, Boston\nPhone: 212-555-1212\nEmail: jane.smith@example.com\nHistory of Fontan surgery. No evidence of ventricular dysfunction.'


class App:
    def __init__(self, root):
        self.root = root
        self.bus = queue.Queue()
        self.cancel = threading.Event()
        self.busy = False
        self.detector = None
        self.detector_key = None
        self.last_output = None
        self.mutable = []
        self.vars = {name:tk.StringVar(value=value) for name,value in {
            'source':'', 'output':'', 'text':'', 'patient':'', 'encoding':'utf-8-sig',
            'model':'en_core_web_lg', 'threshold':'0.35', 'rules':'',
        }.items()}
        root.title('Clinical Note Deidentifier • Local research workspace')
        root.geometry('1180x860')
        root.minsize(980, 740)
        root.configure(bg='#edf2f7')
        style = ttk.Style(root)
        style.theme_use('clam')
        font = 'Helvetica Neue' if sys.platform == 'darwin' else 'Segoe UI'
        style.configure('.', font=(font, 11), background='#edf2f7', foreground='#163047')
        style.configure('TButton', padding=(14, 8), background='#e1e9f2', foreground='#163047')
        style.configure('Primary.TButton', background='#17666b', foreground='white', font=(font, 11, 'bold'))
        style.map('Primary.TButton', background=[('active','#125459'),('disabled','#a7babb')])
        style.configure('Title.TLabel', font=(font, 25, 'bold'))
        style.configure('Sub.TLabel', foreground='#496477')
        outer = ttk.Frame(root, padding=22)
        outer.pack(fill='both', expand=True)
        ttk.Label(outer, text='Clinical Note Deidentifier', style='Title.TLabel').pack(anchor='w')
        ttk.Label(outer, text='Local processing  •  English notes  •  Original files preserved', style='Sub.TLabel').pack(anchor='w', pady=(3,12))
        note = tk.Label(outer, text='Research redaction tool: outputs require review. This does not certify HIPAA de-identification.', bg='#fff2d6', fg='#6f4c14', anchor='w', padx=12, pady=9)
        note.pack(fill='x', pady=(0,12))
        self.tabs = ttk.Notebook(outer)
        self.tabs.pack(fill='both', expand=True)
        self.batch = ttk.Frame(self.tabs, padding=16)
        self.preview = ttk.Frame(self.tabs, padding=16)
        self.setup = ttk.Frame(self.tabs, padding=16)
        self.tabs.add(self.batch, text='  Batch processing  ')
        self.tabs.add(self.preview, text='  Preview & review  ')
        self.tabs.add(self.setup, text='  Model & offline setup  ')
        self.build_batch()
        self.build_preview()
        self.build_setup()
        status = ttk.Frame(outer)
        status.pack(fill='x', pady=(12,0))
        self.status = tk.StringVar(value='Ready. Select an input file or folder, then check the local model.')
        self.stats = tk.StringVar(value='0 notes  •  0 candidate spans')
        ttk.Label(status, textvariable=self.status, wraplength=900).pack(anchor='w')
        ttk.Label(status, textvariable=self.stats, style='Sub.TLabel').pack(anchor='w', pady=(4,6))
        self.progress = ttk.Progressbar(status, mode='indeterminate')
        self.progress.pack(fill='x')
        root.protocol('WM_DELETE_WINDOW', self.close)
        root.after(100, self.poll)

    def button(self, parent, text, command, primary=False):
        control = ttk.Button(parent, text=text, command=command, style='Primary.TButton' if primary else 'TButton')
        self.mutable.append(control)
        return control

    def entry(self, parent, key):
        control = ttk.Entry(parent, textvariable=self.vars[key])
        self.mutable.append(control)
        return control

    def build_batch(self):
        self.batch.columnconfigure(1, weight=1)
        ttk.Label(self.batch, text='1  Choose notes', font=('Segoe UI',13,'bold')).grid(row=0,column=0,columnspan=3,sticky='w',pady=(0,10))
        ttk.Label(self.batch,text='Input file / folder').grid(row=1,column=0,sticky='w',padx=(0,12))
        self.entry(self.batch,'source').grid(row=1,column=1,sticky='ew')
        buttons = ttk.Frame(self.batch)
        buttons.grid(row=1,column=2,padx=(8,0))
        self.button(buttons,'File…',self.choose_file).pack(side='left')
        self.button(buttons,'TXT folder…',self.choose_folder).pack(side='left',padx=(5,0))
        ttk.Label(self.batch,text='CSV / TSV, optionally gzip compressed; TXT or a folder of TXT files.',style='Sub.TLabel').grid(row=2,column=1,columnspan=2,sticky='w',pady=(5,12))
        ttk.Label(self.batch,text='Note text column').grid(row=3,column=0,sticky='w')
        self.text_combo = ttk.Combobox(self.batch,textvariable=self.vars['text'],state='readonly')
        self.text_combo.grid(row=3,column=1,sticky='ew',pady=5)
        self.mutable.append(self.text_combo)
        self.button(self.batch,'Read headers',self.load_columns).grid(row=3,column=2,padx=(8,0),sticky='w')
        ttk.Label(self.batch,text='Patient ID column\n(optional)').grid(row=4,column=0,sticky='w')
        self.patient_combo = ttk.Combobox(self.batch,textvariable=self.vars['patient'],state='readonly')
        self.patient_combo.grid(row=4,column=1,sticky='ew',pady=5)
        self.mutable.append(self.patient_combo)
        ttk.Label(self.batch,text='Selected IDs become random pseudonyms. Other source columns are excluded.',style='Sub.TLabel',wraplength=650).grid(row=5,column=1,columnspan=2,sticky='w',pady=(3,16))
        ttk.Label(self.batch,text='2  Save a redacted copy',font=('Segoe UI',13,'bold')).grid(row=6,column=0,columnspan=3,sticky='w',pady=(0,10))
        ttk.Label(self.batch,text='New output folder').grid(row=7,column=0,sticky='w')
        self.entry(self.batch,'output').grid(row=7,column=1,sticky='ew')
        self.button(self.batch,'Choose parent…',self.choose_output).grid(row=7,column=2,padx=(8,0),sticky='w')
        ttk.Label(self.batch,text='Creates notes_redacted.csv, review.csv and audit.json. Existing folders are never overwritten.',style='Sub.TLabel',wraplength=780).grid(row=8,column=1,columnspan=2,sticky='w',pady=(6,14))
        self.review_ack = tk.BooleanVar(value=False)
        ack = ttk.Checkbutton(self.batch,text='I will review results locally; a completed run does not prove that all PHI was removed.',variable=self.review_ack)
        ack.grid(row=9,column=0,columnspan=3,sticky='w',pady=(0,12))
        self.mutable.append(ack)
        actions = ttk.Frame(self.batch)
        actions.grid(row=10,column=0,columnspan=3,sticky='w')
        self.button(actions,'Preview first note',self.preview_first).pack(side='left')
        self.button(actions,'Run batch redaction',self.run,True).pack(side='left',padx=8)
        self.cancel_button = ttk.Button(actions,text='Cancel run',command=self.cancel.set,state='disabled')
        self.cancel_button.pack(side='left')
        ttk.Button(actions,text='Open completed output',command=self.open_output).pack(side='left',padx=8)

    def build_preview(self):
        ttk.Label(self.preview,text='Compare text before processing the entire dataset.',font=('Segoe UI',13,'bold')).pack(anchor='w')
        ttk.Label(self.preview,text='Preview text stays in this window. It is not saved or written to logs.',style='Sub.TLabel').pack(anchor='w',pady=(4,10))
        actions = ttk.Frame(self.preview)
        actions.pack(fill='x',pady=(0,10))
        self.button(actions,'Load fictional example',self.sample).pack(side='left')
        self.button(actions,'Detect & redact preview',self.redact_preview,True).pack(side='left',padx=8)
        self.button(actions,'Clear preview',self.clear_preview).pack(side='left')
        panes = ttk.Panedwindow(self.preview,orient='horizontal')
        panes.pack(fill='both',expand=True)
        left, right = ttk.Frame(panes), ttk.Frame(panes)
        panes.add(left,weight=1)
        panes.add(right,weight=1)
        ttk.Label(left,text='Original note — may contain PHI').pack(anchor='w',pady=(0,6))
        ttk.Label(right,text='Redacted copy — review required').pack(anchor='w',pady=(0,6))
        self.original = ScrolledText(left,wrap='word',font=('Consolas',11),bg='white',fg='#163047',width=35,height=10)
        self.original.pack(fill='both',expand=True,padx=(0,8))
        self.redacted = ScrolledText(right,wrap='word',font=('Consolas',11),bg='#f2faf8',fg='#163047',width=35,height=10,state='disabled')
        self.redacted.pack(fill='both',expand=True)
        self.preview_info = tk.StringVar(value='No preview processed. Detected identifiers will be replaced with typed placeholders.')
        ttk.Label(self.preview,textvariable=self.preview_info,wraplength=1020).pack(anchor='w',pady=(12,0))

    def build_setup(self):
        self.setup.columnconfigure(1,weight=1)
        ttk.Label(self.setup,text='Local detection model',font=('Segoe UI',13,'bold')).grid(row=0,column=0,columnspan=3,sticky='w',pady=(0,12))
        for row,key,label in [(1,'model','Installed model / folder'),(2,'threshold','Detection threshold'),(3,'rules','Custom recognizers JSON'),(4,'encoding','Input text encoding')]:
            ttk.Label(self.setup,text=label).grid(row=row,column=0,sticky='w',padx=(0,12),pady=8)
            self.entry(self.setup,key).grid(row=row,column=1,sticky='ew',pady=8)
        self.button(self.setup,'Model folder…',self.choose_model).grid(row=1,column=2,padx=(8,0))
        self.button(self.setup,'Rules file…',self.choose_rules).grid(row=3,column=2,padx=(8,0))
        self.button(self.setup,'Check local model',self.check_model,True).grid(row=5,column=1,sticky='w',pady=(10,14))
        text = ('Run the included setup script once before use. The app never downloads models and blocks Python network connections.\n\n'
                'Windows offline kit: run Install_Offline_Windows.cmd, then Start_Windows.cmd.\n'
                'Source package / Mac: follow README.md to install Python, Presidio and the spaCy model beforehand.\n\n'
                'Threshold 0.35 is a starting setting, not a clinical validation threshold. Lower values can flag more text; higher values can miss identifiers.\n\n'
                'Built-in additions cover labeled MRNs, patient/account/accession IDs, common street-address formats and written ages above 89. Extend them to match your hospital.\n\n'
                'Names, places and dates use a general English NER model. Rare identifying narratives, initials, local identifiers and unusual date/address formats may be missed. Review detected spans that overlap clinical eponyms. No automatic clinical-term whitelist is applied.')
        ttk.Label(self.setup,text=text,justify='left',wraplength=900,style='Sub.TLabel').grid(row=6,column=0,columnspan=3,sticky='nw')

    def choose_file(self):
        path = filedialog.askopenfilename(filetypes=[('Clinical notes','*.csv *.tsv *.gz *.txt'),('All files','*')])
        if path:
            self.vars['source'].set(path)
            self.load_columns()

    def choose_folder(self):
        path = filedialog.askdirectory()
        if path:
            self.vars['source'].set(path)
            self.vars['text'].set('')
            self.vars['patient'].set('')
            self.text_combo.configure(values=[])
            self.patient_combo.configure(values=[''])

    def choose_output(self):
        path = filedialog.askdirectory(title='Choose a parent for a NEW output folder')
        if path:
            self.vars['output'].set(str(Path(path)/('redacted_notes_'+datetime.now().strftime('%Y%m%d_%H%M%S'))))

    def choose_model(self):
        path = filedialog.askdirectory(title='Choose a complete extracted spaCy model folder')
        if path: self.vars['model'].set(path)

    def choose_rules(self):
        path = filedialog.askopenfilename(filetypes=[('JSON recognizers','*.json')])
        if path: self.vars['rules'].set(path)

    def load_columns(self):
        try:
            source = Path(self.vars['source'].get())
            columns = [] if source.is_dir() else column_names(source,self.vars['encoding'].get())
            self.text_combo.configure(values=columns)
            self.patient_combo.configure(values=['']+columns)
            self.vars['text'].set(next((c for c in columns if c.lower() in ['text','note_text','clinical_note','note','report_text']),columns[0] if columns else ''))
            self.vars['patient'].set('')
            self.status.set('Headers loaded. Confirm the text column; choose an ID column only if linkage is needed.')
        except (BatchError, OSError, UnicodeError):
            messagebox.showerror('Cannot read headers','Check the input file, format and encoding. Table headers must be nonempty and unique.')

    def options(self):
        values = {k:v.get().strip() for k,v in self.vars.items()}
        # Column labels are exact schema names, including leading/trailing spaces.
        values['text'] = self.vars['text'].get()
        values['patient'] = self.vars['patient'].get()
        values['threshold'] = float(values['threshold'])
        if not 0 <= values['threshold'] <= 1:
            raise ValueError('Threshold must be between 0 and 1.')
        return values

    def get_detector(self, values):
        rules = values['rules']
        stamp = Path(rules).stat().st_mtime_ns if rules else None
        key = (values['model'],values['threshold'],rules,stamp)
        if key != self.detector_key:
            self.detector = Detector(values['model'],values['threshold'],rules or None)
            self.detector_key = key
        return self.detector

    def launch(self, job, values, text=None):
        if self.busy: return
        self.busy = True
        self.cancel.clear()
        for widget in self.mutable: widget.configure(state='disabled')
        self.original.configure(state='disabled')
        self.cancel_button.configure(state='normal' if job == 'batch' else 'disabled')
        self.progress.start(12)
        self.status.set('Loading local model… First load can take a little time.')
        threading.Thread(target=self.worker,args=(job,values,text),daemon=True).start()

    def worker(self, job, values, text):
        try:
            detector = self.get_detector(values)
            if job == 'check':
                self.bus.put(('done','Local model ready. Python network connections are blocked.'))
                return
            if job == 'first':
                first = next(records(values['source'],values['text'],values['patient'],values['encoding']),None)
                if first is None: raise BatchError('The input table has no note records.')
                text = first[2]
            if job in ['preview','first']:
                result = detector.redact(text)
                self.bus.put(('preview',(text,result)))
                self.bus.put(('done','Preview ready. Review both texts before running a batch.'))
                return
            audit = run_batch(detector,values['source'],values['output'],values['text'],values['patient'],values['encoding'],self.cancel,lambda n,s:self.bus.put(('progress',(n,s))) if n == 1 or n % 10 == 0 else None)
            self.bus.put(('complete',(values['output'],audit)))
            self.bus.put(('done','Batch complete. Review the redacted notes and review.csv locally.'))
        except (SetupError,BatchError) as error:
            self.bus.put(('error',str(error)))
        except Exception:
            self.bus.put(('error','The operation failed. Check file permissions, configuration and encoding. Source text was not included in the error message.'))

    def check_model(self):
        self.start('check')

    def preview_first(self):
        self.start('first')

    def redact_preview(self):
        self.start('preview',self.original.get('1.0','end-1c'))

    def start(self, job, text=None):
        try:
            values = self.options()
            if job in ['first','batch'] and not values['source']:
                raise ValueError('Select an input file or TXT folder.')
            if job == 'batch' and not values['output']:
                raise ValueError('Choose a new output folder.')
            self.launch(job,values,text)
        except ValueError as error:
            messagebox.showerror('Check settings',str(error))

    def run(self):
        if not self.review_ack.get():
            messagebox.showinfo('Local review','Check the local-review acknowledgment before processing.')
            return
        self.start('batch')

    def sample(self):
        self.original.delete('1.0','end')
        self.original.insert('1.0',SAMPLE)

    def clear_preview(self):
        self.original.delete('1.0','end')
        self.redacted.configure(state='normal')
        self.redacted.delete('1.0','end')
        self.redacted.configure(state='disabled')
        self.preview_info.set('Preview cleared.')

    def finish(self):
        self.busy = False
        for widget in self.mutable: widget.configure(state='normal')
        self.text_combo.configure(state='readonly')
        self.patient_combo.configure(state='readonly')
        self.original.configure(state='normal')
        self.cancel_button.configure(state='disabled')
        self.progress.stop()

    def poll(self):
        try:
            while True:
                kind, data = self.bus.get_nowait()
                if kind == 'progress':
                    self.stats.set(f'{data[0]:,} notes  •  {data[1]:,} candidate spans')
                    self.status.set('Processing locally… Do not modify the source files during a run.')
                elif kind == 'preview':
                    original, (redacted, detected, empty, clinical) = data
                    self.original.configure(state='normal')
                    self.original.delete('1.0','end')
                    self.original.insert('1.0',original)
                    self.redacted.configure(state='normal')
                    self.redacted.delete('1.0','end')
                    self.redacted.insert('1.0',redacted)
                    self.redacted.configure(state='disabled')
                    for item in detected:
                        self.original.tag_add('phi',f"1.0+{item['start']}c",f"1.0+{item['end']}c")
                    self.original.tag_configure('phi',background='#ffdfdf',foreground='#74252c')
                    types = ', '.join(sorted({d['type'] for d in detected})) or 'none'
                    self.preview_info.set(f'{len(detected)} candidate spans. Types: {types}.' + (' Clinical-term overlap: review carefully.' if clinical else ' Review for missed identifiers.'))
                    self.tabs.select(self.preview)
                elif kind == 'complete':
                    self.last_output, audit = data
                    self.stats.set(f"{audit['records']:,} notes  •  {sum(audit['candidate_spans_by_type'].values()):,} candidate spans  •  {audit['records_with_clinical_overlap']:,} clinical overlaps")
                elif kind == 'done':
                    self.status.set(data)
                    self.finish()
                elif kind == 'error':
                    self.status.set(data)
                    self.finish()
                    messagebox.showerror('Operation stopped',data)
        except queue.Empty:
            pass
        self.root.after(100,self.poll)

    def open_output(self):
        if not self.last_output:
            messagebox.showinfo('Output','No completed output is available yet.')
            return
        path = str(Path(self.last_output).resolve())
        if sys.platform == 'win32': os.startfile(path)
        elif sys.platform == 'darwin': subprocess.Popen(['open',path])
        else: subprocess.Popen(['xdg-open',path])

    def close(self):
        if self.busy:
            messagebox.showinfo('Processing','Cancel the run and wait for it to stop before closing.')
            return
        self.root.destroy()


if __name__ == '__main__':
    block_network()
    window = tk.Tk()
    App(window)
    window.mainloop()
