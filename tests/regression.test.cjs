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

function node(tag) {
  return {
    tag, children: [], textContent: '', className: '',
    addEventListener() {},
    appendChild(child) { this.children.push(child); return child; },
    prepend(child) { this.children.unshift(child); return child; },
    set innerHTML(value) { assert.fail('unexpected HTML insertion: ' + value); },
  };
}

// Everything the page rendered, as plain text -- if markup ever reaches the DOM
// as a string it shows up here verbatim instead of becoming elements.
function renderedText(el) {
  return el.textContent + el.children.map(renderedText).join('');
}

function browser() {
  const elements = Object.fromEntries(
    ['dropzone', 'fileInput', 'status'].map(id => [id, node(id)]));
  let reads = 0;
  let reader;
  const sent = [];
  const handlers = {};
  const run = {
    withSuccessHandler(fn) { handlers.success = fn; return run; },
    withFailureHandler(fn) { handlers.failure = fn; return run; },
    processUpload(...args) { sent.push(args); return run; },
  };
  const ctx = vm.createContext({
    document: {
      getElementById: id => elements[id],
      createElement: tag => node(tag),
      createTextNode: textContent => ({ tag: '#text', textContent, children: [] }),
    },
    FileReader: class {
      constructor() { reader = this; }
      readAsDataURL() { reads++; }
    },
    google: { script: { run } },
  });
  const html = fs.readFileSync('src/Index.html', 'utf8');
  vm.runInContext(html.match(/<script>([\s\S]*?)<\/script>/)[1], ctx);
  return {
    ctx, status: elements.status, reads: () => reads, reader: () => reader,
    sent, handlers,
    // Drive a file all the way through to the point the server would reply.
    upload(file = { name: 'sample.docx', size: 100 }) {
      ctx.handleFile(file);
      reader.result = 'data:application/octet-stream;base64,QUJD';
      reader.onload();
      return handlers;
    },
    links: () => elements.status.children.filter(c => c.tag === 'a'),
    items: () => elements.status.children
      .filter(c => c.tag === 'ul')
      .flatMap(list => list.children),
  };
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
  // Reading graphicData to label the object is fine; reaching in for its
  // content is the thing that must never happen.
  ctx._findFirstDeep = (root, name) => {
    if (name !== 'graphicData') assert.fail('compound content was extracted: ' + name);
    return null;
  };
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

// ---------- unsupported-object reporting ----------
// Values crossing back from vm.createContext carry that realm's prototypes, so
// deepStrictEqual fails on identity even when the contents match. Strings are
// primitives, so a plain copy is enough to compare them here.
function warningsOf(value) {
  return Array.from(value);
}


function uriAnchor(uri) {
  return { getAttribute: () => ({ getValue: () => uri }) };
}

test('charts and SmartArt are recognised as unsupported, not as pictures', () => {
  const ctx = server();
  for (const uri of [
    'http://schemas.openxmlformats.org/drawingml/2006/chart',
    'http://schemas.microsoft.com/office/drawing/2014/chartex',
    'http://schemas.openxmlformats.org/drawingml/2006/diagram',
  ]) {
    ctx._findFirstDeep = () => uriAnchor(uri);
    assert.equal(ctx._isCompoundAnchor({}), true, uri + ' should be preserved');
  }
  // A plain picture must still classify as a picture.
  ctx._findFirstDeep = () => uriAnchor('http://schemas.openxmlformats.org/drawingml/2006/picture');
  assert.equal(ctx._isCompoundAnchor({}), false);
});

test('descriptors name each unsupported type, falling back for unknown ones', () => {
  const ctx = server();
  const label = uri => {
    ctx._findFirstDeep = () => (uri === null ? null : uriAnchor(uri));
    return ctx._unsupportedDescriptor({}).one;
  };
  assert.equal(label('http://schemas.openxmlformats.org/drawingml/2006/chart'), 'chart');
  assert.equal(label('http://schemas.openxmlformats.org/drawingml/2006/diagram'), 'SmartArt diagram');
  assert.equal(label('http://schemas.microsoft.com/office/word/2010/wordprocessingGroup'), 'grouped shape');
  assert.equal(label('http://schemas.microsoft.com/office/word/2010/wordprocessingCanvas'), 'drawing canvas');
  assert.equal(label('urn:something:unrecognised'), 'floating object');
  assert.equal(label(null), 'floating object');
});

test('warnings count objects, pluralise, and reset between conversions', () => {
  const ctx = server();
  assert.deepEqual(warningsOf(ctx._conversionWarnings()), []);

  ctx._noteUnsupported({ one: 'chart', many: 'charts' });
  assert.deepEqual(warningsOf(ctx._conversionWarnings()),
    ['1 chart could not be converted and was kept as-is -- check how it looks.']);

  ctx._noteUnsupported({ one: 'chart', many: 'charts' });
  ctx._noteUnsupported({ one: 'drawing canvas', many: 'drawing canvases' });
  assert.deepEqual(warningsOf(ctx._conversionWarnings()), [
    '2 charts could not be converted and were kept as-is -- check how they look.',
    '1 drawing canvas could not be converted and was kept as-is -- check how it looks.',
  ]);

  ctx._resetConversionReport();
  assert.deepEqual(warningsOf(ctx._conversionWarnings()), []);
});

test('unsupported anchors are counted once each during classification', () => {
  const ctx = server();
  const run = {};
  const drawing = { getParentElement: () => run };
  const anchors = [
    { getParentElement: () => drawing },
    { getParentElement: () => drawing },
  ];
  ctx._findAllDeep = (root, name) => name === 'anchor' ? anchors : [];
  ctx._isCompoundAnchor = () => true;
  ctx._unsupportedDescriptor = () => ({ one: 'chart', many: 'charts' });
  ctx._enclosingParagraph = () => ({});
  ctx._markKey = () => 'p1';
  ctx._anchorExtent = () => null;
  ctx._anchorOffset = () => null;
  ctx._clearMarks = () => {};
  ctx._emitGroup = () => {};
  ctx._resetConversionReport();
  ctx._replaceAnchors({});
  assert.deepEqual(warningsOf(ctx._conversionWarnings()),
    ['2 charts could not be converted and were kept as-is -- check how they look.']);
});

test('processUpload returns warnings alongside the document link', () => {
  const blob = {};
  const ctx = server({
    Utilities: { base64Decode: () => [1, 2], newBlob: () => blob },
    MimeType: { GOOGLE_DOCS: 'google-doc' },
    Drive: { Files: { create: () => ({ id: '1', webViewLink: 'https://docs.google.com/d/1' }) } },
  });
  ctx.fixDocx = () => { ctx._noteUnsupported({ one: 'chart', many: 'charts' }); return blob; };
  const result = ctx.processUpload('AQI=', 'Deck.docx');
  assert.equal(result.url, 'https://docs.google.com/d/1');
  assert.deepEqual(warningsOf(result.warnings),
    ['1 chart could not be converted and was kept as-is -- check how it looks.']);
});

// ---------- success handler rendering ----------

test('the success handler builds the result link without any HTML string', () => {
  const b = browser();
  b.upload().success({ url: 'https://docs.google.com/document/d/123/edit', warnings: [] });
  const [link] = b.links();
  assert.equal(link.href, 'https://docs.google.com/document/d/123/edit');
  assert.equal(link.textContent, 'open the converted document');
  assert.equal(link.rel, 'noopener noreferrer');
  assert.match(renderedText(b.status), /Done/);
  assert.equal(b.items().length, 0);
});

test('warnings render as list items, never as markup', () => {
  const b = browser();
  const hostile = '<img src=x onerror=alert(1)> 2 charts kept';
  b.upload().success({ url: 'https://docs.google.com/d/1', warnings: [hostile, 'second'] });
  const items = b.items();
  assert.equal(items.length, 2);
  // Present verbatim as text -- the innerHTML guard in node() would have fired
  // had it been concatenated into markup.
  assert.equal(items[0].textContent, hostile);
  assert.equal(items[1].textContent, 'second');
});

test('a non-https result URL is never used as a link target', () => {
  for (const url of ['javascript:alert(1)', 'data:text/html,<script>', 'http://example.com', undefined]) {
    const b = browser();
    b.upload().success({ url, warnings: [] });
    assert.equal(b.links()[0].href, '#', 'unsafe URL was rendered: ' + url);
  }
});

test('a successful render clears an earlier error state', () => {
  const b = browser();
  b.ctx.handleFile({ name: 'x.txt', size: 10 });
  assert.equal(b.status.className, 'error');
  b.upload().success({ url: 'https://docs.google.com/d/1', warnings: [] });
  assert.equal(b.status.className, '');
});

// ---------- floating tables ----------

// Minimal stand-in for XmlService so built elements can be inspected. Only the
// methods Code.gs actually calls are implemented.
function xmlStub() {
  function element(name) {
    return {
      name, children: [], attrs: {},
      getName() { return this.name; },
      addContent(child) { this.children.push(child); return this; },
      setAttribute(n, v) { this.attrs[n] = v; return this; },
      getAttribute(n) { return n in this.attrs ? { getValue: () => this.attrs[n] } : null; },
      getChildren(n) { return n ? this.children.filter(c => c.name === n) : this.children; },
      getChild(n) { return this.children.filter(c => c.name === n)[0] || null; },
      removeContent(child) {
        const i = this.children.indexOf(child);
        if (i !== -1) this.children.splice(i, 1);
      },
    };
  }
  return {
    createElement: name => element(name),
    getNamespace: (...args) => ({ getURI: () => args.at(-1) }),
  };
}

function positionEl(spec) {
  return {
    getAttribute: n => (n === 'relativeFrom' && spec.rel) ? { getValue: () => spec.rel } : null,
    getChild: n => {
      if (n === 'posOffset' && spec.offset !== undefined) return { getText: () => String(spec.offset) };
      if (n === 'align' && spec.align !== undefined) return { getText: () => spec.align };
      return null;
    },
  };
}

function anchorStub(h, v, dist) {
  const d = dist || {};
  return {
    getChild: n => n === 'positionH' ? (h ? positionEl(h) : null)
                 : n === 'positionV' ? (v ? positionEl(v) : null) : null,
    getAttribute: n => n in d ? { getValue: () => String(d[n]) } : null,
  };
}

function floatCtx() {
  const ctx = server({ XmlService: xmlStub() });
  ctx._shapeFillColor = () => null;
  return ctx;
}

function boxFor(anchor, cx) {
  return { anchor, txbx: { getChildren: () => [], removeContent() {} }, ext: { cx: cx || 3000000, cy: 1000000 } };
}

test('absolute offsets convert EMU to dxa and map the anchoring frame', () => {
  const ctx = floatCtx();
  // -0.5in and 1.0in, column/paragraph relative -> both anchor to "text".
  const pr = ctx._floatingTableProps(boxFor(
    anchorStub({ rel: 'column', offset: -457200 }, { rel: 'paragraph', offset: 914400 })));
  assert.equal(pr.attrs.tblpX, '-720');
  assert.equal(pr.attrs.tblpY, '1440');
  assert.equal(pr.attrs.horzAnchor, 'text');
  assert.equal(pr.attrs.vertAnchor, 'text');
  assert.equal(pr.attrs.tblpXSpec, undefined);
});

test('page- and margin-relative anchors keep their own frames', () => {
  const ctx = floatCtx();
  const pr = ctx._floatingTableProps(boxFor(
    anchorStub({ rel: 'page', offset: 0 }, { rel: 'topMargin', offset: 0 })));
  assert.equal(pr.attrs.horzAnchor, 'page');
  assert.equal(pr.attrs.vertAnchor, 'margin');
});

test('align keywords become tblpXSpec/tblpYSpec, not coordinates', () => {
  const ctx = floatCtx();
  const pr = ctx._floatingTableProps(boxFor(
    anchorStub({ rel: 'margin', align: 'center' }, { rel: 'paragraph', align: 'top' })));
  assert.equal(pr.attrs.tblpXSpec, 'center');
  assert.equal(pr.attrs.tblpYSpec, 'top');
  assert.equal(pr.attrs.tblpX, undefined);
  assert.equal(pr.attrs.tblpY, undefined);
});

test('an unrecognised align keyword does not become a bogus spec', () => {
  const ctx = floatCtx();
  const pr = ctx._floatingTableProps(boxFor(
    anchorStub({ rel: 'margin', align: 'sideways' }, { rel: 'paragraph', offset: 0 })));
  assert.equal(pr.attrs.tblpXSpec, undefined);
  assert.equal(pr.attrs.tblpX, '0');
});

test('an anchor with no usable position produces no float at all', () => {
  const ctx = floatCtx();
  assert.equal(ctx._floatingTableProps(boxFor(anchorStub(null, null))), null);
});

test('one axis missing borrows the other axis frame rather than mixing systems', () => {
  const ctx = floatCtx();
  const pr = ctx._floatingTableProps(boxFor(anchorStub({ rel: 'page', offset: 635000 }, null)));
  assert.equal(pr.attrs.horzAnchor, 'page');
  assert.equal(pr.attrs.vertAnchor, 'page');
  assert.equal(pr.attrs.tblpY, '0');
});

test('wrap gaps come from the anchor dist* attributes, defaulting to 180 dxa', () => {
  const ctx = floatCtx();
  const pos = { rel: 'column', offset: 0 };
  const withDist = ctx._floatingTableProps(boxFor(
    anchorStub(pos, pos, { distL: 114300, distR: 114300 })));   // 0.125in -> 180
  assert.equal(withDist.attrs.leftFromText, '180');
  assert.equal(withDist.attrs.rightFromText, '180');
  assert.equal(withDist.attrs.topFromText, '180', 'absent distT should default');

  const custom = ctx._floatingTableProps(boxFor(anchorStub(pos, pos, { distL: 228600 })));
  assert.equal(custom.attrs.leftFromText, '360');
});

test('tblpPr and tblOverlap precede tblW, as the schema requires', () => {
  const ctx = floatCtx();
  const tbl = ctx._buildTableFromTextboxes([boxFor(
    anchorStub({ rel: 'column', offset: 0 }, { rel: 'paragraph', offset: 0 }))]);
  const order = tbl.getChild('tblPr').children.map(c => c.name);
  assert.deepEqual(order.slice(0, 3), ['tblpPr', 'tblOverlap', 'tblW']);
  assert.equal(order.indexOf('tblpPr') < order.indexOf('tblBorders'), true);
});

test('a positionless text box still yields a valid inline table', () => {
  const ctx = floatCtx();
  const tbl = ctx._buildTableFromTextboxes([boxFor(anchorStub(null, null))]);
  const names = tbl.getChild('tblPr').children.map(c => c.name);
  assert.equal(names.indexOf('tblpPr'), -1);
  assert.equal(names[0], 'tblW');
});

test('each text box becomes its own positioned table, never a merged row', () => {
  const ctx = floatCtx();
  const inserted = [];
  ctx._contentIndex = () => 0;
  const anchorP = { getParentElement: () => parent };
  const parent = { addContent: (i, el) => inserted.push(el), getName: () => 'body' };

  const pos = n => anchorStub({ rel: 'column', offset: n }, { rel: 'paragraph', offset: 0 });
  // Two boxes on the same visual row: the inline path would merge these into
  // one two-cell table. Floating must keep them independent.
  const group = [-457200, 3000000].map(x => Object.assign(
    boxFor(pos(x)), { kind: 'textbox', drawing: { removeContent() {} }, p: anchorP }));

  ctx._emitGroup(group);

  const tables = inserted.filter(el => el.getName() === 'tbl');
  assert.equal(tables.length, 2, 'expected one table per text box');
  tables.forEach(t => assert.equal(t.getChild('tblPr').children[0].name, 'tblpPr'));
  // Each table holds exactly one cell.
  tables.forEach(t => assert.equal(t.getChild('tr').getChildren('tc').length, 1));
  // And they are separated, or Word would merge them into one table.
  assert.equal(inserted.some(el => el.getName() === 'p'), true);
});
