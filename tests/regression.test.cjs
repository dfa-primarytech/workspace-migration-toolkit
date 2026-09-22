const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const { test } = require('node:test');
const source = fs.readFileSync('src/Code.gs', 'utf8');
function server(extra = {}) {
  const ctx = vm.createContext({
    XmlService: { getNamespace: (...args) => ({ getURI: () => args.at(-1) }) },
    ...extra,
  });
  vm.runInContext(source, ctx);
  return ctx;
}

test('unknown objects and normal floating pictures are not detached', () => {
  const ctx = server();
  for (const kind of ['unknown', 'picture']) {
    ctx._emitGroup([{ kind, drawing: { removeContent() { assert.fail('object was deleted'); } } }]);
  }
});

test('ink and confirmed backing pictures are still removed', () => {
  const ctx = server();
  for (const kind of ['ink', 'picture']) {
    const anchor = {};
    let removed = 0;
    ctx._emitGroup([{ kind, drop: true, anchor, drawing: {
      removeContent(node) { assert.equal(node, anchor); removed++; },
    } }]);
    assert.equal(removed, 1);
  }
});

test('groups and canvases are recognised before descendant extraction', () => {
  const ctx = server();
  for (const type of ['wordprocessingGroup', 'wordprocessingCanvas']) {
    ctx._findFirstDeep = () => ({ getAttribute: () => ({ getValue: () =>
      'http://schemas.microsoft.com/office/word/2010/' + type }) });
    assert.equal(ctx._isCompoundAnchor({}), true);
  }
  ctx._findFirstDeep = () => null;
  assert.equal(ctx._isCompoundAnchor({}), false);
});

test('invalid uploads fail before decoding or contacting Drive', () => {
  const ctx = server({ Utilities: { base64Decode() { assert.fail('decoded rejected input'); } } });
  assert.throws(() => ctx.processUpload('AA==', 'file.doc'), /docx/);
  assert.throws(() => ctx.processUpload('', 'file.docx'), /empty/);
  assert.throws(() => ctx.processUpload('A'.repeat(4 * Math.ceil(25 * 1024 * 1024 / 3) + 4), 'file.docx'), /25 MiB/);
});

test('decoded size check catches base64 boundary rounding', () => {
  const ctx = server({ Utilities: { base64Decode: () => ({ length: 25 * 1024 * 1024 + 1 }) } });
  assert.throws(() => ctx.processUpload('AA==', 'file.docx'), /25 MiB/);
});

test('valid upload still repairs and converts a document', () => {
  const blob = {};
  const ctx = server({
    Utilities: { base64Decode: () => [1, 2], newBlob: () => blob },
    MimeType: { GOOGLE_DOCS: 'google-doc' },
    Drive: { Files: { create(meta, fixed) {
      assert.equal(meta.name, 'Worksheet');
      assert.equal(fixed, blob);
      return { id: '123', webViewLink: 'https://docs.google.com/document/d/123/edit' };
    } } },
  });
  ctx.fixDocx = input => { assert.equal(input, blob); return blob; };
  assert.equal(ctx.processUpload('AQI=', 'Worksheet.DOCX').id, '123');
});

function browser() {
  const elements = Object.fromEntries(['dropzone', 'fileInput', 'status'].map(id => [id, {
    addEventListener() {}, prepend() {}, textContent: '',
    set innerHTML(value) { assert.fail('unexpected HTML insertion: ' + value); },
  }]));
  let reads = 0;
  let reader;
  const ctx = vm.createContext({
    document: { getElementById: id => elements[id], createElement: () => ({}) },
    FileReader: class {
      constructor() { reader = this; }
      readAsDataURL() { reads++; }
    },
  });
  const html = fs.readFileSync('src/Index.html', 'utf8');
  vm.runInContext(html.match(/<script>([\s\S]*?)<\/script>/)[1], ctx);
  return { ctx, status: elements.status, reads: () => reads, reader: () => reader };
}

test('oversize browser upload is rejected before reading bytes', () => {
  const b = browser();
  b.ctx.handleFile({ name: 'large.docx', size: 26 * 1024 * 1024 });
  assert.equal(b.reads(), 0);
  assert.match(b.status.textContent, /26.0 MiB.*25 MiB/);
});

test('filenames are displayed as text, including HTML-shaped names', () => {
  const b = browser();
  const name = '<img src=x onerror=alert(1)>.docx';
  b.ctx.handleFile({ name, size: 100 });
  assert.equal(b.reads(), 1);
  assert.ok(b.status.textContent.includes(name));
});

test('file read failure has an actionable error', () => {
  const b = browser();
  b.ctx.handleFile({ name: 'sample.docx', size: 100 });
  b.reader().onerror();
  assert.equal(b.status.className, 'error');
  assert.match(b.status.textContent, /Could not read/);
});

test('compound anchor classification never extracts a descendant text box', () => {
  const ctx = server();
  const paragraph = {};
  const run = {};
  const drawing = { getParentElement: () => run };
  const anchor = { getParentElement: () => drawing };
  ctx._findAllDeep = (root, name) => name === 'anchor' ? [anchor] : [];
  ctx._isCompoundAnchor = () => true;
  ctx._findFirstDeep = () => assert.fail('compound content was extracted');
  ctx._enclosingParagraph = () => paragraph;
  ctx._markKey = () => 'p1';
  ctx._anchorExtent = () => null;
  ctx._anchorOffset = () => null;
  ctx._clearMarks = () => {};
  let classified;
  ctx._emitGroup = group => { classified = group[0].kind; };
  ctx._replaceAnchors({});
  assert.equal(classified, 'unknown');
});
