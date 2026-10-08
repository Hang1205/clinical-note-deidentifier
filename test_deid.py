import csv
import gzip
import json
from pathlib import Path
import socket
import tempfile
import threading
import unittest

from deid_core import Detector, BatchError, SetupError, Cancelled, column_names, run_batch


class DeidTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.detector = Detector()

    def test_real_phi_and_clinical_meaning(self):
        text = 'Jane Smith, MRN: AB1234567. Email: jane.smith@example.com. Phone: 212-555-1212. DOB: 03/12/1980. Lives at 123 Main Street, Boston. History of Fontan surgery. No evidence of ventricular dysfunction.'
        cleaned, found, empty, clinical = self.detector.redact(text)
        for secret in ['Jane Smith','AB1234567','jane.smith@example.com','212-555-1212','03/12/1980','123 Main Street']:
            self.assertNotIn(secret, cleaned)
        self.assertIn('No evidence of ventricular dysfunction',cleaned)
        self.assertFalse(empty)
        self.assertIn('MEDICAL_RECORD_NUMBER',{r['type'] for r in found})
        self.assertTrue('Fontan' in cleaned or clinical)

    def test_network_block(self):
        with self.assertRaises(OSError): socket.create_connection(('example.com',443))

    def test_missing_model_fail_closed(self):
        with self.assertRaises(SetupError): Detector('missing_model_DO_NOT_DOWNLOAD')

    def test_csv_gzip_and_pseudonyms(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root/'original.csv.gz'
            with gzip.open(source,'wt',encoding='utf-8',newline='') as h:
                w=csv.writer(h)
                w.writerow(['patient_id','note_id','text','raw_address'])
                w.writerows([['001','N1','Jane Smith\nMRN: AB1234567','NEVER_COPY'],['001','N2','Email: jane@example.com','NEVER_COPY'],['002','N3','','NEVER_COPY']])
            before=source.read_bytes()
            audit=run_batch(self.detector,source,root/'out','text','patient_id')
            with (root/'out/notes_redacted.csv').open(encoding='utf-8',newline='') as h: rows=list(csv.DictReader(h))
            self.assertEqual(audit['records'],3)
            self.assertEqual(rows[0]['patient_id'],rows[1]['patient_id'])
            self.assertNotEqual(rows[0]['patient_id'],rows[2]['patient_id'])
            self.assertNotIn('note_id',rows[0])
            self.assertNotIn('raw_address',rows[0])
            self.assertIn('\n',rows[0]['redacted_text'])
            self.assertEqual(source.read_bytes(),before)
            for f in (root/'out').iterdir():
                value=f.read_text(encoding='utf-8')
                for secret in ['Jane Smith','AB1234567','jane@example.com','NEVER_COPY','original.csv']:
                    self.assertNotIn(secret,value)
            self.assertEqual(rows[2]['review_status'],'empty_note')

    def test_txt_filenames_excluded_and_formulas_safe(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp); source=root/'input'; source.mkdir()
            (source/'Jane_Smith_MRN123.txt').write_text('=1+1\nMRN: AB1234567',encoding='utf-8')
            run_batch(self.detector,source,root/'out')
            with (root/'out/notes_redacted.csv').open(encoding='utf-8',newline='') as h: row=next(csv.DictReader(h))
            self.assertTrue(row['redacted_text'].startswith("'="))
            self.assertNotIn('Jane_Smith',json.dumps(row))

    def test_no_overwrite_and_bad_columns(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp); source=root/'notes.csv'
            source.write_text('text\nhello\n',encoding='utf-8')
            out=root/'out'; out.mkdir(); (out/'keep').write_text('keep')
            with self.assertRaises(BatchError): run_batch(self.detector,source,out,'text')
            self.assertEqual((out/'keep').read_text(),'keep')
            with self.assertRaises(BatchError): run_batch(self.detector,source,root/'bad','missing')
            self.assertFalse((root/'bad').exists())
            audit=json.loads(next(root.glob('bad.incomplete-*/audit.json')).read_text())
            self.assertEqual(audit['status'],'failed')

    def test_cancel_and_malformed_row(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp); source=root/'notes.csv'; source.write_text('text\nhello\n',encoding='utf-8')
            cancel=threading.Event(); cancel.set()
            with self.assertRaises(Cancelled): run_batch(self.detector,source,root/'stop','text',cancel=cancel)
            self.assertFalse((root/'stop').exists())
            audit=json.loads(next(root.glob('stop.incomplete-*/audit.json')).read_text())
            self.assertEqual(audit['status'],'cancelled')
            source.write_text('text,id\nhello\n',encoding='utf-8')
            with self.assertRaises(BatchError): run_batch(self.detector,source,root/'malformed','text')
            self.assertFalse((root/'malformed').exists())

    def test_duplicate_headers(self):
        with tempfile.TemporaryDirectory() as temp:
            p=Path(temp)/'notes.csv'; p.write_text('text,text\na,b\n')
            with self.assertRaises(BatchError): column_names(p)

    def test_header_only_and_exact_column_labels(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp); source=root/'notes.csv'
            source.write_text(' text \n',encoding='utf-8')
            with self.assertRaises(BatchError): run_batch(self.detector,source,root/'empty',' text ')
            self.assertFalse((root/'empty').exists())
            source.write_text(' text \nMRN: AB1234567\n',encoding='utf-8')
            audit=run_batch(self.detector,source,root/'ok',' text ')
            self.assertEqual(audit['records'],1)

    def test_tsv_and_custom_rules(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp); rules=root/'rules.json'
            rules.write_text(json.dumps({'recognizers':[{'entity':'LOCAL_ID','regex':r'\bZX-\d{8}\b','score':0.95}]}))
            detector=Detector(custom_rules=rules)
            source=root/'notes.tsv'; source.write_text('text\tpid\nZX-12345678\t001\n',encoding='utf-8')
            audit=run_batch(detector,source,root/'out','text','pid')
            self.assertIn('LOCAL_ID',audit['candidate_spans_by_type'])
            self.assertNotIn('ZX-12345678',(root/'out/notes_redacted.csv').read_text())


if __name__ == '__main__': unittest.main()
