// Runs app.js's own openPicker() against a fake Google Picker and prints the
// views it built (test_picker_views.py). argv: path to app.js.
const fs = require('fs');

const source = fs.readFileSync(process.argv[2], 'utf8');
const start = source.indexOf('async function openPicker');
const end = source.indexOf('function send(');
if (start < 0 || end < start) throw new Error('openPicker not found in app.js');

const views = [];
const built = { views, features: [], title: null };
class DocsView {
  constructor() { this.calls = {}; views.push(this.calls); }
}
for (const name of ['setMimeTypes', 'setIncludeFolders', 'setSelectFolderEnabled', 'setParent', 'setEnableDrives', 'setLabel', 'setOwnedByMe', 'setMode']) {
  DocsView.prototype[name] = function (value) { this.calls[name] = value; return this; };
}
class PickerBuilder {
  addView(view) { built.added = (built.added || 0) + 1; return this; }
  enableFeature(feature) { built.features.push(feature); return this; }
  setTitle(title) { built.title = title; return this; }
  setCallback(callback) { this.callback = callback; return this; }
  build() {
    const callback = this.callback;
    return { setVisible() { callback({ action: 'cancel' }); } };
  }
}
for (const name of ['setOAuthToken', 'setDeveloperKey', 'setAppId', 'setOrigin', 'setLocale']) {
  PickerBuilder.prototype[name] = function () { return this; };
}
globalThis.google = {
  picker: {
    DocsView, PickerBuilder,
    Feature: { MULTISELECT_ENABLED: 'multiselect' },
    Action: { PICKED: 'picked', CANCEL: 'cancel' },
  },
};
const session = { pickerEnabled: true, pickerApiKey: 'k', pickerAppId: '1', formats: [{ mime: 'a/b' }, { mime: 'c/d' }] };
const loadPicker = async () => {};
const request = async () => ({ accessToken: 't' });
const $ = () => ({ value: '' });
const choose = () => {};

eval(source.slice(start, end));  // declares openPicker here, using these fakes

openPicker().then(() => console.log(JSON.stringify(built)));
