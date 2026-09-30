// Runs app.js's own loadPicker() against a fake page (test_picker_load.py).
// argv: path to app.js, then the scenario: "network", "picker" or "shared".
const fs = require('fs');

const source = fs.readFileSync(process.argv[2], 'utf8');
const scenario = process.argv[3];
const start = source.indexOf('function loadPicker()');
const end = source.indexOf('async function openPicker');
if (start < 0 || end < start) throw new Error('loadPicker not found in app.js');

const scripts = [];
let loads = 0;
const document = {
  createElement: () => ({ removed: false, remove() { this.removed = true; } }),
  head: {
    append(script) {
      scripts.push(script);
      setTimeout(() => {
        if (scenario === 'network' && scripts.length === 1) return script.onerror();
        globalThis.gapi = {
          load(name, options) {
            loads += 1;
            if (scenario === 'picker' && loads === 1) return options.onerror();
            options.callback();
          },
        };
        script.onload();
      }, 0);
    },
  },
};

let gapiLoading;
eval(source.slice(start, end));  // declares loadPicker here, using this document

async function outcome(promise) {
  try { await promise; return 'loaded'; } catch (error) { return 'failed'; }
}

(async () => {
  const result = { scenario };
  if (scenario === 'shared') {
    const [a, b] = [loadPicker(), loadPicker()];
    result.same = a === b;
    result.first = await outcome(a);
    result.again = loadPicker() === a;
  } else {
    result.first = await outcome(loadPicker());
    result.second = await outcome(loadPicker());
  }
  result.scripts = scripts.length;
  result.removed = scripts.map(s => s.removed);
  result.loads = loads;
  console.log(JSON.stringify(result));
})();
