// Runs app.js's own request() and convertAll() against fakes and prints what
// a teacher would see (test_page_results.py). argv: path to app.js, scenario.
const fs = require('fs');

const source = fs.readFileSync(process.argv[2], 'utf8');
const scenario = process.argv[3];
function slice(from, to) {
  const start = source.indexOf(from);
  const end = source.indexOf(to, start);
  if (start < 0 || end < start) throw new Error(`${from} not found in app.js`);
  return source.slice(start, end);
}

class Row {
  constructor() { this.parts = []; }
  replaceChildren(...parts) { this.parts = parts.map(p => (typeof p === 'string' ? p : `[${p.textContent}]`)); }
  get text() { return this.parts.join(''); }
}
const elements = {};
const $ = id => (elements[id] ||= { textContent: '', hidden: false, disabled: false, checked: false });
const busy = () => {};
const refusal = () => '';
const pipelineFor = () => ({ destination: 'Google Sheets' });
const link = (url, label) => ({ textContent: label, href: url });

let fetch;
let send;
let chosen = [];
eval(slice('async function request', 'function busy'));
eval(slice('async function convertAll', "$('convert').addEventListener"));

(async () => {
  const result = { scenario };
  if (scenario === 'offline') {
    fetch = () => Promise.reject(new TypeError('Failed to fetch'));
    try { await request('/api/convert'); } catch (error) { result.message = error.message; }
  } else {
    const reports = {
      // A workbook kept for moving by hand: a folder, nothing to open.
      kept: { status: 'manual_migration_required', folderUrl: 'https://drive.google.com/drive/folders/f',
        stoppedBecause: 'Not converted: it has macros, which Google Sheets can’t run.' },
      converted: { status: 'converted_with_review', folderUrl: 'https://drive.google.com/drive/folders/f',
        url: 'https://docs.google.com/spreadsheets/d/s/edit' },
    };
    send = async () => reports[scenario];
    chosen = [{ name: 'book.xlsm', row: new Row() }];
    await convertAll();
    result.row = chosen[0].row.text;
    result.status = $('status').textContent;
  }
  console.log(JSON.stringify(result));
})();
