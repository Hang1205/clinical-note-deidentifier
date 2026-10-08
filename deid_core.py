"""Local-only PHI detection and batch redaction. English research notes."""
from __future__ import annotations

import csv
import gzip
import hashlib
import importlib.metadata
import json
import logging
from pathlib import Path
import re
import socket
import threading
from datetime import datetime, timezone
from collections import Counter
from uuid import uuid4

VERSION = '1.0.0'
MAX_NOTE_CHARS = 1_000_000
ENTITIES = ['PERSON', 'LOCATION', 'DATE_TIME', 'EMAIL_ADDRESS', 'PHONE_NUMBER',
            'US_SSN', 'US_DRIVER_LICENSE', 'US_PASSPORT', 'US_BANK_NUMBER',
            'CREDIT_CARD', 'IBAN_CODE', 'IP_ADDRESS', 'URL',
            'MEDICAL_RECORD_NUMBER', 'CLINICAL_IDENTIFIER', 'STREET_ADDRESS', 'AGE_OVER_89']
CLINICAL_TERMS = re.compile(r'\b(?:Fontan|Glenn|Norwood|Rastelli|Mustard|Senning|Blalock[- ]Taussig)\b', re.I)


class SetupError(Exception):
    pass


class BatchError(Exception):
    pass


class Cancelled(BatchError):
    pass


def block_network():
    """Fail closed on Python socket networking, including model auto-downloads."""
    def denied(*args, **kwargs):
        raise OSError('Network access is disabled in Clinical Note Deidentifier.')
    socket.socket.connect = denied
    socket.socket.connect_ex = denied
    socket.create_connection = denied
    socket.getaddrinfo = denied


def spreadsheet_safe(text):
    if text.lstrip().startswith(('=', '+', '-', '@')):
        return "'" + text
    return text


def open_text(path, encoding='utf-8-sig'):
    path = Path(path)
    return (gzip.open if path.suffix.lower() == '.gz' else open)(path, 'rt', encoding=encoding, newline='')


def file_kind(path):
    name = Path(path).name.lower()
    if name.endswith(('.csv', '.csv.gz')):
        return 'csv'
    if name.endswith(('.tsv', '.tsv.gz')):
        return 'tsv'
    if name.endswith('.txt'):
        return 'txt'
    raise BatchError('Select CSV, CSV.GZ, TSV, TSV.GZ, TXT, or a folder of TXT files.')


def input_files(source):
    source = Path(source).resolve()
    if not source.exists():
        raise BatchError('The selected input does not exist.')
    if source.is_dir():
        files = sorted(p for p in source.iterdir() if p.is_file() and not p.is_symlink() and p.suffix.lower() == '.txt')
        if not files:
            raise BatchError('The folder has no TXT files. Subfolders are not scanned.')
        return files
    file_kind(source)
    return [source]


def column_names(source, encoding='utf-8-sig'):
    kind = file_kind(source)
    if kind == 'txt':
        return []
    with open_text(source, encoding) as handle:
        reader = csv.reader(handle, delimiter='\t' if kind == 'tsv' else ',')
        headers = next(reader, [])
    if not headers or len(set(headers)) != len(headers) or any(not h.strip() for h in headers):
        raise BatchError('Table headers must be present, nonempty, and unique.')
    return headers


def records(source, text_column='', patient_column='', encoding='utf-8-sig', cancel=None):
    files = input_files(source)
    ordinal = 0
    for source_number, path in enumerate(files, 1):
        kind = file_kind(path)
        if cancel and cancel.is_set():
            raise Cancelled('Cancelled.')
        if kind == 'txt':
            with open_text(path, encoding) as handle:
                text = handle.read(MAX_NOTE_CHARS + 1)
            if len(text) > MAX_NOTE_CHARS:
                raise BatchError('A text file exceeds the one-million-character note limit.')
            ordinal += 1
            yield ordinal, source_number, text, ''
        else:
            headers = column_names(path, encoding)
            if text_column not in headers:
                raise BatchError('Select a valid note text column.')
            if patient_column and patient_column not in headers:
                raise BatchError('Select a valid patient identifier column, or leave it blank.')
            csv.field_size_limit(MAX_NOTE_CHARS * 4)
            with open_text(path, encoding) as handle:
                reader = csv.DictReader(handle, delimiter='\t' if kind == 'tsv' else ',')
                for row in reader:
                    if cancel and cancel.is_set():
                        raise Cancelled('Cancelled.')
                    ordinal += 1
                    if None in row or any(v is None for v in row.values()):
                        raise BatchError(f'Malformed table record {ordinal}; no completed output was published.')
                    text = row[text_column]
                    if len(text) > MAX_NOTE_CHARS:
                        raise BatchError(f'Record {ordinal} exceeds the note length limit.')
                    patient = row[patient_column] if patient_column else ''
                    if patient_column and not patient.strip():
                        raise BatchError(f'Record {ordinal} has a blank patient identifier.')
                    yield ordinal, source_number, text, patient


class Detector:
    def __init__(self, model='en_core_web_lg', threshold=0.35, custom_rules=None):
        block_network()
        logging.getLogger('presidio-analyzer').setLevel(logging.CRITICAL)
        logging.getLogger('presidio_analyzer').setLevel(logging.CRITICAL)
        if not 0 <= threshold <= 1:
            raise SetupError('Detection threshold must be between 0 and 1.')
        try:
            import spacy
            import tldextract
            # EmailRecognizer uses this module. Disable its public-suffix downloads
            # and home-directory cache; use the library's bundled suffix snapshot.
            tldextract.extract = tldextract.TLDExtract(suffix_list_urls=(), cache_dir=None)
            from presidio_analyzer import AnalyzerEngine, Pattern, PatternRecognizer, RecognizerRegistry
            from presidio_analyzer.nlp_engine import SpacyNlpEngine
            from presidio_anonymizer import AnonymizerEngine
        except ImportError:
            raise SetupError('Presidio or spaCy is missing. Run the included setup instructions first.') from None
        try:
            loaded = spacy.load(model)
        except Exception:
            raise SetupError('The chosen local spaCy model cannot be loaded. Install the bundled model or select an extracted model folder; this app will not download it.') from None
        if 'ner' not in loaded.pipe_names:
            raise SetupError('The selected model must include a trained NER component. A blank language pipeline is not supported.')
        loaded.max_length = MAX_NOTE_CHARS + 1

        class LocalSpacyEngine(SpacyNlpEngine):
            def load(self):
                self.nlp = {'en': loaded}

        engine = LocalSpacyEngine(models=[{'lang_code': 'en', 'model_name': str(model)}])
        engine.load()
        registry = RecognizerRegistry(supported_languages=['en'])
        registry.load_predefined_recognizers(languages=['en'], nlp_engine=engine, countries=['us'])
        # Only local recognizers are registered. Header patterns intentionally include the label.
        defaults = [
            ('MEDICAL_RECORD_NUMBER', r'\b(?:MRN|medical\s+record\s+(?:number|no\.?|#))\s*[:#=]?\s*[A-Z0-9][A-Z0-9-]{2,30}\b', 0.95),
            ('CLINICAL_IDENTIFIER', r'\b(?:patient\s+ID|account\s+(?:number|no\.?|#)|accession\s+(?:number|no\.?|#)|encounter\s+ID)\s*[:#=]?\s*[A-Z0-9][A-Z0-9-]{2,30}\b', 0.95),
            ('STREET_ADDRESS', r'\b\d{1,6}\s+(?:[A-Z0-9]+[ \t]+){1,5}(?:Street|St\.?|Road|Rd\.?|Avenue|Ave\.?|Boulevard|Blvd\.?|Lane|Ln\.?|Drive|Dr\.?)\b(?:[ \t]+(?:Apt|Suite|Unit)\.?[ \t#]*[A-Z0-9-]+)?', 0.85),
            ('AGE_OVER_89', r'\b(?:9\d|1\d{2})\s*(?:years?[- ]old|y/?o|years?\s+of\s+age)\b', 0.9),
        ]
        self.rule_specs = list(defaults)
        for entity, pattern, score in defaults:
            registry.add_recognizer(PatternRecognizer(supported_entity=entity, patterns=[Pattern(entity, pattern, score)], supported_language='en'))
        self.entities = list(ENTITIES)
        if custom_rules:
            try:
                config = json.loads(Path(custom_rules).read_text(encoding='utf-8'))
                rules = config['recognizers']
                if not isinstance(rules, list):
                    raise ValueError()
                for item in rules:
                    entity, expression = item['entity'], item['regex']
                    score = float(item.get('score', 0.9))
                    if not re.fullmatch(r'[A-Z][A-Z0-9_]{1,60}', entity) or not 0 <= score <= 1:
                        raise ValueError()
                    re.compile(expression)
                    registry.add_recognizer(PatternRecognizer(supported_entity=entity, patterns=[Pattern(entity, expression, score)], supported_language='en'))
                    self.entities.append(entity)
                    self.rule_specs.append((entity, expression, score))
            except Exception:
                raise SetupError('Custom recognizer JSON is invalid. Check entity labels, regular expressions, and scores.') from None
        self.analyzer = AnalyzerEngine(nlp_engine=engine, registry=registry, supported_languages=['en'])
        self.anonymizer = AnonymizerEngine()
        self.threshold = threshold
        self.model = str(model)
        self.versions = {name: importlib.metadata.version(name) for name in ['presidio-analyzer', 'presidio-anonymizer', 'spacy']}
        self.model_version = loaded.meta.get('version', 'unknown')
        self.rules_hash = hashlib.sha256(json.dumps(self.rule_specs, sort_keys=True).encode()).hexdigest()

    def redact(self, text):
        from presidio_anonymizer.entities import OperatorConfig
        if not text.strip():
            return text, [], True, False
        found = self.analyzer.analyze(text=text, language='en', entities=list(set(self.entities)), score_threshold=self.threshold)
        found = sorted(found, key=lambda r: (r.start, r.end, r.entity_type))
        clinical = any(r.start < m.end() and r.end > m.start() for m in CLINICAL_TERMS.finditer(text) for r in found)
        operators = {entity: OperatorConfig('replace', {'new_value': f'[{entity}]'}) for entity in self.entities}
        result = self.anonymizer.anonymize(text=text, analyzer_results=found, operators=operators)
        # Detector counts are candidate spans; overlapping spans can become one replacement.
        detections = [{'type': r.entity_type, 'start': r.start, 'end': r.end, 'score': round(r.score, 4)} for r in found]
        return result.text, detections, False, clinical


def run_batch(detector, source, output, text_column='', patient_column='', encoding='utf-8-sig', cancel=None, progress=None):
    cancel = cancel or threading.Event()
    output = Path(output).expanduser().resolve()
    source = Path(source).expanduser().resolve()
    files = input_files(source)
    if output.exists():
        raise BatchError('Choose a new output folder. Existing folders are never overwritten.')
    if source.is_dir() and (output == source or source in output.parents):
        raise BatchError('Choose an output folder outside the input folder.')
    if output in source.parents:
        raise BatchError('The output folder cannot contain the input.')
    output.parent.mkdir(parents=True, exist_ok=True)
    incomplete = output.with_name(output.name + '.incomplete-' + uuid4().hex[:8])
    incomplete.mkdir()
    audit = {'app_version':VERSION, 'started_utc':datetime.now(timezone.utc).isoformat(), 'status':'running',
             'method':'Presidio local NER + pattern recognizers; typed replacement; no compliance certification',
             'network':'Python socket connections disabled', 'language':'en',
             'model': Path(detector.model).name, 'model_version':detector.model_version, 'package_versions':detector.versions,
             'threshold':detector.threshold, 'rules_sha256':detector.rules_hash,
             'source_files':len(files), 'records':0, 'empty_records':0, 'records_without_detections':0,
             'records_with_clinical_overlap':0, 'candidate_spans_by_type':{},
             'identifiers':'Random patient pseudonyms within this run only; no reidentification mapping exported' if patient_column else 'No source identifier columns exported',
             'review':'Every output requires local review; detection absence does not establish de-identification.'}
    counts = Counter()
    patient_map = {}
    start_stats = [(p.stat().st_size, p.stat().st_mtime_ns) for p in files]
    try:
        with (incomplete / 'notes_redacted.csv').open('w', encoding='utf-8', newline='') as handle, (incomplete / 'review.csv').open('w', encoding='utf-8', newline='') as review_handle:
            fields = ['record_number'] + (['patient_id'] if patient_column else []) + ['redacted_text', 'candidate_spans', 'review_status']
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            reviewer = csv.writer(review_handle)
            reviewer.writerow(['record_number', 'candidate_spans', 'clinical_overlap', 'empty_note', 'review_status'])
            for ordinal, source_number, text, patient in records(source, text_column, patient_column, encoding, cancel):
                redacted, detections, empty, clinical = detector.redact(text)
                if cancel.is_set():
                    raise Cancelled('Cancelled.')
                state = 'empty_note' if empty else ('clinical_term_overlap_review' if clinical else ('no_detections_review' if not detections else 'review_required'))
                row = {'record_number':ordinal, 'redacted_text':spreadsheet_safe(redacted), 'candidate_spans':len(detections), 'review_status':state}
                if patient_column:
                    if patient not in patient_map:
                        patient_map[patient] = 'P-' + uuid4().hex
                    row['patient_id'] = patient_map[patient]
                writer.writerow(row)
                reviewer.writerow([ordinal, len(detections), int(clinical), int(empty), state])
                counts.update(item['type'] for item in detections)
                audit['records'] += 1
                audit['empty_records'] += int(empty)
                audit['records_without_detections'] += int(not detections and not empty)
                audit['records_with_clinical_overlap'] += int(clinical)
                if progress:
                    progress(audit['records'], sum(counts.values()))
        if cancel.is_set():
            raise Cancelled('Cancelled.')
        if not audit['records']:
            raise BatchError('The input contained no note records.')
        if start_stats != [(p.stat().st_size, p.stat().st_mtime_ns) for p in files]:
            raise BatchError('Source files changed during processing. Retry with a stable copy.')
        audit.update(status='complete', finished_utc=datetime.now(timezone.utc).isoformat(), candidate_spans_by_type=dict(counts))
        (incomplete / 'audit.json').write_text(json.dumps(audit, indent=2), encoding='utf-8')
        # Atomic directory publication; no completed destination on failure/cancellation.
        if output.exists():
            raise BatchError('The output folder was created during processing. Choose a new folder.')
        incomplete.rename(output)
        return audit
    except Exception as error:
        audit.update(status='cancelled' if isinstance(error, Cancelled) else 'failed', finished_utc=datetime.now(timezone.utc).isoformat(), candidate_spans_by_type=dict(counts))
        # Never serialize exception payloads: they could contain source note text.
        (incomplete / 'audit.json').write_text(json.dumps(audit, indent=2), encoding='utf-8')
        if isinstance(error, (BatchError, SetupError)):
            raise
        raise BatchError('Processing failed. The partial folder has a failed audit and must not be used as completed output. No source text was written to the error log.') from None
