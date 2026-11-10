import json
import os
import sqlite3
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs, urlencode
from urllib.request import urlopen, Request
from html import unescape

ROOT = Path(__file__).resolve().parent
DB = Path(os.environ.get('WORKTIME_DB', str(ROOT / 'worktime.sqlite3')))


def connect():
    db = sqlite3.connect(DB, timeout=10)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA foreign_keys=ON')
    db.execute('PRAGMA busy_timeout=10000')
    return db


def init_db():
    DB.parent.mkdir(parents=True, exist_ok=True)
    with connect() as db:
        db.executescript('''
        CREATE TABLE IF NOT EXISTS employees (id INTEGER PRIMARY KEY, name TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS entries (
            id INTEGER PRIMARY KEY, employee_id INTEGER NOT NULL REFERENCES employees(id),
            task TEXT NOT NULL, started_at TEXT NOT NULL, ended_at TEXT);
        CREATE UNIQUE INDEX IF NOT EXISTS one_running_per_employee
            ON entries(employee_id) WHERE ended_at IS NULL;
        ''')
        for table, cols in {'employees': ['name_en', 'name_uz'], 'entries': ['task_en', 'task_uz']}.items():
            existing = {r[1] for r in db.execute(f'PRAGMA table_info({table})')}
            for col in cols:
                if col not in existing:
                    db.execute(f'ALTER TABLE {table} ADD COLUMN {col} TEXT')


def now():
    return datetime.now(timezone.utc).isoformat(timespec='microseconds')


def iso(value):
    try:
        dt = datetime.fromisoformat(value.replace('Z', '+00:00'))
        if dt.tzinfo is None:
            raise ValueError('Timezone required')
        return dt.astimezone(timezone.utc)
    except (ValueError, AttributeError):
        raise ValueError('Invalid ISO date/time')


def employees():
    with connect() as db:
        rows = db.execute('''SELECT e.id, e.name, e.name_en, e.name_uz, t.id AS active_id, t.task AS active_task, t.task_en AS active_task_en, t.task_uz AS active_task_uz,
            t.started_at AS active_since FROM employees e LEFT JOIN entries t
            ON t.employee_id=e.id AND t.ended_at IS NULL ORDER BY e.id''').fetchall()
        return [dict(r) for r in rows]


# MyMemory's public endpoint is free for modest usage, but is not guaranteed.
# Never silently claim that untranslated text has been translated.
TRANSLIT = dict(zip('абвгдеёжзийклмнопрстуфхцчшщъыьэюя',
                    ['a','b','v','g','d','e','yo','zh','z','i','y','k','l','m','n','o','p','r','s','t','u','f','kh','ts','ch','sh','shch','','y','','e','yu','ya']))

def transliterate(text):
    return ''.join((TRANSLIT.get(c.lower(), c) .capitalize() if c.isupper() and c.lower() in TRANSLIT else TRANSLIT.get(c,c)) for c in text)

def latin_to_cyrillic(text):
    # Approximate transliteration for names; user can edit spelling.
    patterns={'shch':'щ','yo':'ё','zh':'ж','kh':'х','ts':'ц','ch':'ч','sh':'ш','yu':'ю','ya':'я',
              'a':'а','b':'б','c':'к','d':'д','e':'е','f':'ф','g':'г','h':'х','i':'и','j':'дж',
              'k':'к','l':'л','m':'м','n':'н','o':'о','p':'п','q':'к','r':'р','s':'с','t':'т',
              'u':'у','v':'в','w':'в','x':'кс','y':'й','z':'з'}
    import re
    return re.sub('|'.join(sorted(patterns,key=len,reverse=True)),
                  lambda m: patterns[m.group().lower()].capitalize() if m.group()[0].isupper() else patterns[m.group().lower()],
                  text,flags=re.IGNORECASE)

def translate_text(text, source, kind='task'):
    if source not in ('ru','en'):
        raise ValueError('Unsupported language')
    if kind == 'name':
        if source == 'ru':
            return transliterate(text)
        # English->Russian names cannot be reliably inferred; request a correction.
        raise ValueError('English names require manual Russian spelling; use edit after saving')
    target = 'en' if source == 'ru' else 'ru'
    query = urlencode({'q': text, 'langpair': source + '|' + target})
    req = Request('https://api.mymemory.translated.net/get?' + query,
                  headers={'User-Agent':'WorkTimeTracker/2.1'})
    try:
        with urlopen(req, timeout=7) as response:
            data = json.load(response)
        translated = unescape(str(data.get('responseData',{}).get('translatedText',''))).strip()
        if int(data.get('responseStatus',0)) != 200 or not translated or translated.lower() == text.lower():
            raise ValueError('Translation unavailable; try again or edit manually')
        return translated
    except (OSError, TimeoutError, KeyError, TypeError) as exc:
        raise ValueError('Free translation service unavailable; retry later') from exc

def bilingual(text, source, kind='task', override=None):
    text = text.strip() if isinstance(text,str) else ''
    limit = 100 if kind=='name' else 300
    if not text or len(text)>limit:
        raise ValueError('Text must be 1–%d characters' % limit)
    if source not in ('ru','en'):
        raise ValueError('Language must be ru or en')
    if source=='ru':
        ru, en = text, override or (transliterate(text) if kind=='name' else translate_text(text,'ru',kind))
    else:
        en = text
        ru = override or (latin_to_cyrillic(text) if kind=='name' else translate_text(text,'en',kind))
    if not ru or not en or len(ru)>limit or len(en)>limit:
        raise ValueError('Invalid translation')
    return ru,en

def add_employee(name, name_en=None, name_uz=None, source='ru'):
    ru,en = bilingual(name,source,'name',name_en if source=='ru' else name_uz)
    with connect() as db:
        cur=db.execute('INSERT INTO employees(name,name_en) VALUES(?,?)',(ru,en))
        return {'id':cur.lastrowid,'name':ru,'name_en':en}


def start_timer(employee_id, task, task_en=None, task_uz=None, source='ru'):
    ru,en = bilingual(task,source,'task',task_en if source=='ru' else task_uz)
    with connect() as db:
        if not db.execute('SELECT 1 FROM employees WHERE id=?',(employee_id,)).fetchone():
            raise LookupError('Employee not found')
        try:
            cur=db.execute('INSERT INTO entries(employee_id,task,task_en,started_at) VALUES(?,?,?,?)',
                           (employee_id,ru,en,now()))
        except sqlite3.IntegrityError:
            raise RuntimeError('Timer is already running for this employee')
        return {'id':cur.lastrowid}

def stop_timer(employee_id):
    with connect() as db:
        cur = db.execute('UPDATE entries SET ended_at=? WHERE employee_id=? AND ended_at IS NULL',
                         (now(), employee_id))
        if cur.rowcount == 0:
            raise RuntimeError('No running timer for this employee')
        return {'stopped': True}


def report(start_date, end_date, employee_id=None):
    from datetime import date, timedelta
    try:
        start = date.fromisoformat(start_date)
        end = date.fromisoformat(end_date)
    except (ValueError, TypeError):
        raise ValueError('Dates must be YYYY-MM-DD')
    if start > end:
        raise ValueError('Start date must not be after end date')
    from datetime import timedelta as delta
    local_tz = timezone(delta(hours=5))
    lower = datetime.combine(start, datetime.min.time(), local_tz).astimezone(timezone.utc)
    upper = datetime.combine(end + timedelta(days=1), datetime.min.time(), local_tz).astimezone(timezone.utc)
    current = datetime.now(timezone.utc)
    with connect() as db:
        people = db.execute('SELECT id,name,name_en,name_uz FROM employees WHERE (? IS NULL OR id=?) ORDER BY id',
                            (employee_id, employee_id)).fetchall()
        result = []
        for person in people:
            entries = db.execute('SELECT * FROM entries WHERE employee_id=? AND started_at<? AND (ended_at IS NULL OR ended_at>?) ORDER BY started_at DESC',
                                 (person['id'], upper.isoformat(), lower.isoformat())).fetchall()
            items = []
            total = 0
            for r in entries:
                begun = iso(r['started_at'])
                finished = iso(r['ended_at']) if r['ended_at'] else current
                seconds = max(0, int((min(finished, upper) - max(begun, lower)).total_seconds()))
                if seconds == 0:
                    continue
                total += seconds
                items.append({'id': r['id'], 'task': r['task'], 'task_en': r['task_en'], 'task_uz': r['task_uz'], 'started_at': r['started_at'],
                              'ended_at': r['ended_at'], 'seconds': seconds})
            result.append({'id': person['id'], 'name': person['name'], 'name_en': person['name_en'], 'name_uz': person['name_uz'], 'total_seconds': total, 'entries': items})
    return {'start': start_date, 'end': end_date, 'employees': result}


class Handler(BaseHTTPRequestHandler):
    def send(self, status, data):
        body = json.dumps(data, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def export_rows(self, data, lang):
        from datetime import timedelta
        labels = (['Сотрудник','Задача','Начало (местное)','Окончание (местное)','Продолжительность','Статус'] if lang == 'ru' else ['Employee','Task','Started (local)','Ended (local)','Duration','Status'])
        suffix = '_en' if lang == 'en' else ''
        local_tz = timezone(timedelta(hours=5))
        def local_stamp(raw):
            if not raw: return ''
            return iso(raw).astimezone(local_tz).strftime('%d.%m.%Y %H:%M:%S')
        rows=[]
        for person in data['employees']:
            for entry in person['entries']:
                secs=int(entry['seconds'])
                rows.append([person.get('name'+suffix) or person['name'], entry.get('task'+suffix) or entry['task'], local_stamp(entry['started_at']), local_stamp(entry['ended_at']), secs, ('В работе' if lang=='ru' else 'Working') if not entry['ended_at'] else ('Завершено' if lang=='ru' else 'Completed')])
        return labels, rows

    def export_csv(self, data, lang):
        import csv, io
        labels, rows=self.export_rows(data,lang)
        output=io.StringIO(newline='')
        writer=csv.writer(output,delimiter=';',lineterminator='\r\n')
        writer.writerow(labels)
        for r in rows:
            h,rem=divmod(r[4],3600); m,sec=divmod(rem,60)
            writer.writerow(r[:4]+[f'{h:02d}:{m:02d}:{sec:02d}',r[5]])
        body=('\ufeff'+output.getvalue()).encode('utf-8')
        self.send_response(200)
        self.send_header('Content-Type','text/csv; charset=utf-8')
        self.send_header('Content-Disposition','attachment; filename="worktime_report.csv"')
        self.send_header('Content-Length',str(len(body)))
        self.end_headers();self.wfile.write(body)

    def export_xlsx(self, data, lang):
        # Generate a real XLSX using only Python's standard library.
        import io, zipfile, html
        from xml.sax.saxutils import escape
        labels, rows=self.export_rows(data,lang)
        total=sum(r[4] for r in rows)
        def cell(ref, value, style=0, number=False, formula=False):
            attr=f' r="{ref}" s="{style}"'
            if formula: return f'<c{attr}><f>{escape(value)}</f></c>'
            if number: return f'<c{attr}><v>{value}</v></c>'
            return f'<c{attr} t="inlineStr"><is><t xml:space="preserve">{escape(str(value))}</t></is></c>'
        letters='ABCDEF'
        lines=[]
        lines.append('<row r="1" ht="32" customHeight="1">'+''.join(cell(f'{letters[j]}1',v,1) for j,v in enumerate(labels))+'</row>')
        for i,r in enumerate(rows,2):
            cells=''.join(cell(f'{letters[j]}{i}',(r[j]/86400 if j==4 else r[j]),3 if j==4 else (2 if i%2==0 else 0),j==4) for j in range(6))
            lines.append(f'<row r="{i}" ht="27" customHeight="1">{cells}</row>')
        last=len(rows)+1; summary=last+1
        total_label='ИТОГО' if lang=='ru' else 'TOTAL'
        lines.append(f'<row r="{summary}" ht="31" customHeight="1">'+cell(f'A{summary}',total_label,1)+cell(f'E{summary}',f'SUM(E2:E{last})' if rows else '0',4,formula=bool(rows),number=not bool(rows))+'</row>')
        worksheet=f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?><worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetViews><sheetView workbookViewId="0"><pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/></sheetView></sheetViews><sheetFormatPr defaultRowHeight="20"/><cols><col min="1" max="1" width="25" customWidth="1"/><col min="2" max="2" width="48" customWidth="1"/><col min="3" max="4" width="24" customWidth="1"/><col min="5" max="5" width="19" customWidth="1"/><col min="6" max="6" width="17" customWidth="1"/></cols><sheetData>{''.join(lines)}</sheetData><autoFilter ref="A1:F{max(1,last)}"/></worksheet>'''
        styles='''<?xml version="1.0" encoding="UTF-8" standalone="yes"?><styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><numFmts count="1"><numFmt numFmtId="164" formatCode="[h]:mm:ss"/></numFmts><fonts count="3"><font><sz val="11"/><name val="Calibri"/></font><font><b/><sz val="11"/><color rgb="FFFFFFFF"/><name val="Calibri"/></font><font><b/><sz val="11"/><color rgb="FF003092"/><name val="Calibri"/></font></fonts><fills count="4"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill><fill><patternFill patternType="solid"><fgColor rgb="FF003092"/><bgColor indexed="64"/></patternFill></fill><fill><patternFill patternType="solid"><fgColor rgb="FFFFF2DB"/><bgColor indexed="64"/></patternFill></fill></fills><borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders><cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs><cellXfs count="5"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/><xf numFmtId="0" fontId="1" fillId="2" borderId="0" xfId="0" applyFill="1" applyFont="1"/><xf numFmtId="0" fontId="0" fillId="3" borderId="0" xfId="0" applyFill="1"/><xf numFmtId="164" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/><xf numFmtId="164" fontId="2" fillId="3" borderId="0" xfId="0" applyNumberFormat="1"/></cellXfs></styleSheet>'''
        content='''<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/><Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/><Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/></Types>'''
        files={'[Content_Types].xml':content,'_rels/.rels':'<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>','xl/workbook.xml':'<?xml version="1.0"?><workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="Work Time" sheetId="1" r:id="rId1"/></sheets></workbook>','xl/_rels/workbook.xml.rels':'<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/><Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/></Relationships>','xl/worksheets/sheet1.xml':worksheet,'xl/styles.xml':styles}
        output=io.BytesIO()
        with zipfile.ZipFile(output,'w',zipfile.ZIP_DEFLATED) as z:
            for filename,contents in files.items(): z.writestr(filename,contents)
        body=output.getvalue()
        self.send_response(200)
        self.send_header('Content-Type','application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
        self.send_header('Content-Disposition','attachment; filename="worktime_report.xlsx"')
        self.send_header('Content-Length',str(len(body)))
        self.end_headers();self.wfile.write(body)

    def do_GET(self):
        path = urlparse(self.path)
        if path.path in ('/', '/index.html'):
            body = (ROOT / 'static' / 'index.html').read_bytes()
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        try:
            if path.path == '/api/employees':
                return self.send(200, employees())
            if path.path == '/api/report':
                q = parse_qs(path.query)
                eid = q.get('employee_id', [''])[0]
                return self.send(200, report(q.get('start', [''])[0], q.get('end', [''])[0], int(eid) if eid else None))
            if path.path == '/api/export':
                q=parse_qs(path.query)
                eid=q.get('employee_id',[''])[0]
                return self.export_csv(report(q.get('start',[''])[0],q.get('end',[''])[0],int(eid) if eid else None),q.get('lang',['ru'])[0])
            if path.path == '/api/export/xlsx':
                q=parse_qs(path.query)
                eid=q.get('employee_id',[''])[0]
                return self.export_xlsx(report(q.get('start',[''])[0],q.get('end',[''])[0],int(eid) if eid else None),q.get('lang',['ru'])[0])
            self.send(404, {'error': 'Not found'})
        except (ValueError, TypeError) as exc:
            self.send(400, {'error': str(exc)})

    def do_POST(self):
        try:
            length = int(self.headers.get('Content-Length', '0'))
            if length > 10000 or length < 0:
                return self.send(413, {'error': 'Request too large'})
            data = json.loads(self.rfile.read(length))
            if not isinstance(data, dict):
                raise ValueError('Expected JSON object')
            path = urlparse(self.path).path
            if path == '/api/employees':
                return self.send(201, add_employee(data.get('text'), source=data.get('lang','ru')))
            if path == '/api/update_employee':
                eid=int(data['employee_id'])
                with connect() as db:
                    current=db.execute('SELECT * FROM employees WHERE id=?',(eid,)).fetchone()
                    if not current: raise LookupError('Employee not found')
                    ru=(data.get('name') or current['name']).strip()
                    en=(data.get('name_en') or current['name_en'] or transliterate(ru)).strip()
                    if not ru or not en or max(len(ru),len(en))>100: raise ValueError('Invalid names')
                    db.execute('UPDATE employees SET name=?,name_en=? WHERE id=?',(ru,en,eid))
                return self.send(200,{'updated':True})
            if path == '/api/delete_employee':
                eid=int(data['employee_id'])
                with connect() as db:
                    if db.execute('SELECT 1 FROM entries WHERE employee_id=? AND ended_at IS NULL',(eid,)).fetchone():
                        raise RuntimeError('Stop timer before deleting employee')
                    db.execute('DELETE FROM entries WHERE employee_id=?',(eid,))
                    db.execute('DELETE FROM employees WHERE id=?',(eid,))
                return self.send(200, {'deleted': True})
            if path == '/api/update_entry':
                eid=int(data['entry_id'])
                with connect() as db:
                    current=db.execute('SELECT * FROM entries WHERE id=?',(eid,)).fetchone()
                    if not current: raise LookupError('Entry not found')
                    ru=(data.get('task') or current['task']).strip()
                    en=(data.get('task_en') or current['task_en'] or '').strip()
                    if not ru or not en or max(len(ru),len(en))>300: raise ValueError('Both translations required')
                    db.execute('UPDATE entries SET task=?,task_en=? WHERE id=?',(ru,en,eid))
                return self.send(200,{'updated':True})
            if path == '/api/delete_entry':
                with connect() as db:
                    db.execute('DELETE FROM entries WHERE id=?',(int(data['entry_id']),))
                return self.send(200, {'deleted':True})
            if path in ('/api/start', '/api/stop'):
                eid = int(data['employee_id'])
                return self.send(200, start_timer(eid, data.get('text'), source=data.get('lang','ru')) if path == '/api/start' else stop_timer(eid))
            if path.path == '/api/export':
                q = parse_qs(path.query)
                eid = q.get('employee_id', [''])[0]
                return self.export_csv(report(q.get('start', [''])[0], q.get('end', [''])[0], int(eid) if eid else None), q.get('lang',['ru'])[0])
            return self.send(404, {'error': 'Not found'})
        except (ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
            self.send(400, {'error': str(exc)})
        except LookupError as exc:
            self.send(404, {'error': str(exc)})
        except RuntimeError as exc:
            self.send(409, {'error': str(exc)})


if __name__ == '__main__':
    init_db()
    port = int(os.environ.get('PORT', '8000'))
    print(f'Open http://localhost:{port}')
    ThreadingHTTPServer(('127.0.0.1', port), Handler).serve_forever()
