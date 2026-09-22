/**
 * Google Docs Fixer - Apps Script Web App
 * ----------------------------------------
 * Repairs a .docx file so it imports cleanly into Google Docs, by
 * eliminating the constructs Google's importer silently drops:
 *
 *   - floating / anchored text boxes  -> inline 1x1 tables (text runs,
 *     inline images, and the text box's own solid fill color as cell
 *     shading are all preserved; the shape's *position* is not, since
 *     that's exactly what Google Docs can't import)
 *   - floating / anchored plain pictures -> inline pictures
 *   - legacy VML-only pictures (no modern DrawingML sibling) -> modern
 *     inline pictures
 *   - handwritten "ink" annotations -> removed (decorative only)
 *   - legacy mc:Fallback branches -> discarded; mc:Choice is kept
 *   - full-page decorative background images hiding in headers/footers
 *     -> removed (detected by size + page-aspect-ratio match, so real
 *     letterhead logos are left alone)
 *
 * This is a direct port of a Python/lxml prototype, validated against
 * real ticket files, onto Apps Script's XmlService (a real XML DOM --
 * NOT regex/string replace, which breaks on nested <w:p> elements).
 *
 * Deployment: Extensions > Apps Script in a Drive/Sheet, paste this
 * file and Index.html, then Deploy > New deployment > Web app.
 */

// ---------- Namespaces ----------
const NS = {
  w:   XmlService.getNamespace('w',   'http://schemas.openxmlformats.org/wordprocessingml/2006/main'),
  w14: XmlService.getNamespace('w14', 'http://schemas.microsoft.com/office/word/2010/wordml'),
  wp:  XmlService.getNamespace('wp',  'http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing'),
  a:   XmlService.getNamespace('a',   'http://schemas.openxmlformats.org/drawingml/2006/main'),
  pic: XmlService.getNamespace('pic', 'http://schemas.openxmlformats.org/drawingml/2006/picture'),
  wps: XmlService.getNamespace('wps', 'http://schemas.microsoft.com/office/word/2010/wordprocessingShape'),
  mc:  XmlService.getNamespace('mc',  'http://schemas.openxmlformats.org/markup-compatibility/2006'),
  r:   XmlService.getNamespace('r',   'http://schemas.openxmlformats.org/officeDocument/2006/relationships'),
  rel: XmlService.getNamespace('http://schemas.openxmlformats.org/package/2006/relationships'),
  v:   XmlService.getNamespace('v',   'urn:schemas-microsoft-com:vml'),
  o:   XmlService.getNamespace('o',   'urn:schemas-microsoft-com:office:office'),
};

let _nextDocPrId = 800001;
function _newDocPrId() { return ++_nextDocPrId; }

// ================= Web app entry points =================

function doGet() {
  return HtmlService.createHtmlOutputFromFile('Index')
      .setTitle('Docx -> Google Docs Fixer')
      .addMetaTag('viewport', 'width=device-width, initial-scale=1');
}

/**
 * Called from the browser (Index.html) with the uploaded file's bytes.
 * Fixes the docx, uploads it to Drive with automatic conversion to a
 * Google Doc, and returns the resulting Doc's URL.
 */
function processUpload(base64Data, filename) {
  const maxBytes = 25 * 1024 * 1024;
  if (typeof filename !== 'string' || !/\.docx$/i.test(filename)) {
    throw new Error('Please choose a .docx file.');
  }
  if (typeof base64Data !== 'string' || !base64Data.length) {
    throw new Error('The uploaded file is empty.');
  }
  if (base64Data.length > 4 * Math.ceil(maxBytes / 3)) {
    throw new Error('The file exceeds the 25 MiB upload limit.');
  }
  const rawBytes = Utilities.base64Decode(base64Data);
  if (rawBytes.length > maxBytes) {
    throw new Error('The file exceeds the 25 MiB upload limit.');
  }
  const inputBlob = Utilities.newBlob(rawBytes, 'application/vnd.openxmlformats-officedocument.wordprocessingml.document', filename);

  const fixedBlob = fixDocx(inputBlob);

  const file = Drive.Files.create(
    { name: filename.replace(/\.docx$/i, ''), mimeType: MimeType.GOOGLE_DOCS },
    fixedBlob,
    { fields: 'id,webViewLink' }
  );

  return { url: file.webViewLink, id: file.id };
}

// ================= Core fixer =================

/**
 * Takes a .docx Blob, returns a fixed .docx Blob (still docx -- the
 * caller decides whether/how to convert it to a Google Doc).
 */
function fixDocx(inputBlob) {
  // A .docx *is* a zip, but Utilities.unzip() rejects anything not declared as
  // application/zip -- retype a copy rather than mutating the caller's blob.
  const zipBlob = inputBlob.copyBlob().setContentType(MimeType.ZIP);
  const parts = Utilities.unzip(zipBlob); // array of Blobs, one per zip entry
  const byName = {};
  parts.forEach(p => byName[p.getName()] = p);

  const docXmlBlob = byName['word/document.xml'];
  if (!docXmlBlob) throw new Error('Not a valid .docx (missing word/document.xml)');

  const docXmlString = docXmlBlob.getDataAsString();
  const pageAspect = _getPageAspect(docXmlString);

  const fixedDocXml = fixDocumentXml(docXmlString);
  byName['word/document.xml'] = Utilities.newBlob(fixedDocXml, 'application/xml', 'word/document.xml');

  // Strip full-page decorative background images from headers/footers
  Object.keys(byName).forEach(name => {
    if (/^word\/(header|footer)\d*\.xml$/.test(name)) {
      const relsName = 'word/_rels/' + name.split('/').pop() + '.rels';
      const relsBlob = byName[relsName];
      const cleaned = _stripFullPageBackground(
        byName[name].getDataAsString(),
        relsBlob ? relsBlob.getDataAsString() : null,
        byName,
        pageAspect
      );
      if (cleaned !== null) {
        byName[name] = Utilities.newBlob(cleaned, 'application/xml', name);
      }
    }
  });

  const rezippedParts = Object.keys(byName).map(name => {
    const blob = byName[name];
    blob.setName(name);
    return blob;
  });

  const outBlob = Utilities.zip(rezippedParts, 'fixed.docx');
  outBlob.setContentType('application/vnd.openxmlformats-officedocument.wordprocessingml.document');
  return outBlob;
}

function fixDocumentXml(xmlString) {
  const doc = XmlService.parse(xmlString);
  const root = doc.getRootElement();

  _stripFallbacksKeepChoice(root);
  _removeInkRuns(root);
  _removeBackground(root);
  _replaceAnchors(root);
  _fixLegacyPicts(root);
  _removeEmptyParagraphs(root);

  const serialized = XmlService.getRawFormat().format(doc);
  const withoutDecl = serialized.replace(/^<\?xml[^>]*\?>\s*/, '');
  return '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\r\n' + withoutDecl;
}

// ---------- Transform passes ----------

function _stripFallbacksKeepChoice(root) {
  const acs = _findAllDeep(root, 'AlternateContent', NS.mc);
  acs.forEach(ac => {
    const choice = ac.getChild('Choice', NS.mc);
    const parent = ac.getParentElement();
    const idx = _contentIndex(parent, ac);
    if (choice) {
      const children = choice.getChildren().slice(); // copy before mutating
      children.forEach(c => choice.removeContent(c));
      let insertAt = idx;
      children.forEach(c => { parent.addContent(insertAt, c); insertAt++; });
    }
    parent.removeContent(ac);
  });
}

function _removeInkRuns(root) {
  const runs = _findAllDeep(root, 'r', NS.w);
  runs.forEach(r => {
    if (_findAllDeep(r, 'contentPart', NS.w14).length > 0) {
      const parent = r.getParentElement();
      if (parent) parent.removeContent(r);
    }
  });
}

function _removeBackground(root) {
  const bgs = _findAllDeep(root, 'background', NS.w);
  bgs.forEach(bg => {
    const parent = bg.getParentElement();
    if (parent) parent.removeContent(bg);
  });
}

/**
 * Plain pictures are left as floating anchors so Google Docs imports them with
 * its own "Wrap text" / "Behind text" / "In front of text" positioning, which
 * the user can then drag around. Word's wrap modes map straight onto the Docs
 * menu (wrapNone -> in front of text, wrapSquare -> wrap, behindDoc="1" ->
 * behind text), so the author's intent survives.
 *
 * Set false to force every picture inline instead -- safer if a document's
 * floating images come through badly placed, at the cost of making them
 * un-draggable.
 *
 * Text boxes are converted regardless: they become tables, and a table in
 * Google Docs is always inline. That is a hard limit of the target format.
 */
const KEEP_PICTURES_FLOATING = true;

const EMU_PER_INCH = 914400;

// Two anchors count as occupying the same rectangle when their offsets agree
// to within this much. Measured tolerances in real files are ~0.01".
const COINCIDENT_TOL_EMU = Math.round(0.06 * EMU_PER_INCH);
// ...and their extents agree to within this fraction.
const COINCIDENT_SIZE_TOL = 0.03;
// Anchors whose vertical offsets differ by less than this are treated as
// sitting on the same visual row, and are laid out left-to-right.
const ROW_TOL_EMU = Math.round(0.35 * EMU_PER_INCH);

/**
 * Reads a <wp:positionH>/<wp:positionV> offset in EMU.
 *
 * Returns null when the anchor gives no usable horizontal/vertical hint.
 * <wp:align> carries a keyword rather than a number, so map the keywords onto
 * nominal offsets purely so they sort sensibly against numeric siblings.
 */
function _anchorOffset(anchor, axis) {
  const pos = anchor.getChild('position' + axis, NS.wp);
  if (!pos) return null;
  const off = pos.getChild('posOffset', NS.wp);
  if (off) {
    const v = parseInt(off.getText(), 10);
    return isNaN(v) ? null : v;
  }
  const align = pos.getChild('align', NS.wp);
  if (!align) return null;
  const nominal = {
    left: 0, inside: 0, center: Math.round(3.5 * EMU_PER_INCH),
    right: Math.round(7 * EMU_PER_INCH), outside: Math.round(7 * EMU_PER_INCH),
    top: 0, middle: Math.round(4.5 * EMU_PER_INCH), bottom: Math.round(9 * EMU_PER_INCH),
  };
  const key = (align.getText() || '').trim();
  return Object.prototype.hasOwnProperty.call(nominal, key) ? nominal[key] : null;
}

function _anchorExtent(anchor) {
  const extent = anchor.getChild('extent', NS.wp);
  if (!extent) return null;
  const cx = parseInt(extent.getAttribute('cx').getValue(), 10);
  const cy = parseInt(extent.getAttribute('cy').getValue(), 10);
  return (isNaN(cx) || isNaN(cy)) ? null : { cx: cx, cy: cy };
}

function _enclosingParagraph(el) {
  let p = el;
  while (p && p.getName() !== 'p') p = p.getParentElement();
  return p;
}

/**
 * Rewrites every floating anchor as inline content, preserving as much of the
 * original layout as Google Docs can actually represent.
 *
 * Vertical offsets in these files are relative to the anchoring paragraph, not
 * the page, so they are only comparable *within* one paragraph -- document
 * order of the paragraphs already carries the page-level flow. Anchors are
 * therefore grouped by anchoring paragraph, ordered top-to-bottom then
 * left-to-right inside each group, and anchors sharing a row become one
 * multi-cell table row rather than a stack of single-cell tables.
 */
function _replaceAnchors(root) {
  const anchors = _findAllDeep(root, 'anchor', NS.wp);

  // --- classify ---
  const items = [];
  anchors.forEach(anchor => {
    const oldDrawing = anchor.getParentElement();       // <w:drawing>
    // An earlier pass (mc:Fallback stripping) can already have detached this
    // subtree; without the guard every removeContent() below throws.
    if (!oldDrawing) return;
    const run = oldDrawing.getParentElement();          // <w:r>

    let kind, txbx = null, blip = null;
    if (_findAllDeep(anchor, 'contentPart', NS.w14).length > 0) {
      kind = 'ink';                                     // decorative, dropped
    } else if (_isCompoundAnchor(anchor)) {
      // A group may contain text boxes and pictures: extracting the first
      // descendant would discard the rest of the group.
      kind = 'unknown';
    } else if ((txbx = _findFirstDeep(anchor, 'txbxContent', NS.w))) {
      kind = 'textbox';
    } else if ((blip = _findFirstDeep(anchor, 'blip', NS.a)) && anchor.getChild('extent', NS.wp)) {
      kind = 'picture';
    } else {
      kind = 'unknown';
    }

    const encl = _enclosingParagraph(run);
    items.push({
      anchor: anchor, drawing: oldDrawing, run: run,
      p: encl,
      // Elements can't be compared or used as keys, so group on a stamped id.
      pKey: encl ? _markKey(encl) : null,
      kind: kind, txbx: txbx, blip: blip,
      ext: _anchorExtent(anchor),
      h: _anchorOffset(anchor, 'H'),
      v: _anchorOffset(anchor, 'V'),
      drop: false,
    });
  });

  _dropBackingPictures(items);

  // --- group by anchoring paragraph, preserving document order of groups ---
  const groups = [];
  const seen = {};   // pKey -> index into groups
  items.forEach(it => {
    if (!it.pKey) { groups.push([it]); return; }
    if (Object.prototype.hasOwnProperty.call(seen, it.pKey)) {
      groups[seen[it.pKey]].push(it);
    } else {
      seen[it.pKey] = groups.length;
      groups.push([it]);
    }
  });

  groups.forEach(group => _emitGroup(group));

  // The paragraph stamps must not survive into the saved document.
  _clearMarks(root);
}

/**
 * Word builds "card" layouts by stacking a text box directly on top of a
 * picture of identical size and position. Inline content cannot overlap, so
 * emitting both would tear the card in half and double the document's length.
 * The text is the part that must stay editable, so the backing picture goes.
 */
function _dropBackingPictures(items) {
  const boxes = items.filter(it => it.kind === 'textbox' && it.ext && it.h !== null && it.v !== null);
  items.forEach(pic => {
    if (pic.kind !== 'picture' || !pic.ext || pic.h === null || pic.v === null) return;
    const covered = boxes.some(box => {
      if (box.pKey !== pic.pKey) return false;
      if (Math.abs(box.h - pic.h) > COINCIDENT_TOL_EMU) return false;
      if (Math.abs(box.v - pic.v) > COINCIDENT_TOL_EMU) return false;
      const dw = Math.abs(box.ext.cx - pic.ext.cx) / Math.max(box.ext.cx, 1);
      const dh = Math.abs(box.ext.cy - pic.ext.cy) / Math.max(box.ext.cy, 1);
      return dw <= COINCIDENT_SIZE_TOL && dh <= COINCIDENT_SIZE_TOL;
    });
    if (covered) pic.drop = true;
  });
}

/** Orders one paragraph's anchors into rows and emits the replacement blocks. */
function _emitGroup(group) {
  const live = [];
  group.forEach(it => {
    // Keep unsupported content available to the importer instead of deleting it.
    if (it.kind === 'unknown') return;
    // A floating picture we intend to keep is left entirely alone -- detaching
    // and rebuilding it would lose the wrap mode and position we want Docs to
    // read. Backing pictures are still dropped even in floating mode.
    if (KEEP_PICTURES_FLOATING && it.kind === 'picture' && !it.drop) return;

    // Everything else is detached first -- dropped ones simply never come back.
    it.drawing.removeContent(it.anchor);
    if (it.kind === 'ink' || it.kind === 'unknown' || it.drop) return;
    live.push(it);
  });
  if (!live.length) return;

  const anchorP = live[0].p;
  if (!anchorP) return;
  const pParent = anchorP.getParentElement();
  if (!pParent) return;

  // Stable sort: top-to-bottom, then left-to-right. Anchors with no usable
  // offset keep their document position by falling back to it.
  live.forEach((it, i) => { it._seq = i; });
  live.sort((a, b) => {
    const av = a.v === null ? 0 : a.v, bv = b.v === null ? 0 : b.v;
    if (Math.abs(av - bv) > ROW_TOL_EMU) return av - bv;
    const ah = a.h === null ? 0 : a.h, bh = b.h === null ? 0 : b.h;
    if (ah !== bh) return ah - bh;
    return a._seq - b._seq;
  });

  // Split into visual rows on the same vertical tolerance used for sorting.
  const rows = [];
  live.forEach(it => {
    const row = rows[rows.length - 1];
    const prev = row && row[row.length - 1];
    if (prev && Math.abs((it.v === null ? 0 : it.v) - (prev.v === null ? 0 : prev.v)) <= ROW_TOL_EMU) {
      row.push(it);
    } else {
      rows.push([it]);
    }
  });

  const blocks = [];
  rows.forEach(row => {
    const boxes = row.filter(it => it.kind === 'textbox');
    const pics  = row.filter(it => it.kind === 'picture');
    if (boxes.length) blocks.push(_buildTableFromTextboxes(boxes));
    pics.forEach(pic => {
      const para = _buildPicturePara(pic);
      if (para) blocks.push(para);
    });
  });

  // Adjacent <w:tbl> siblings merge into a single table, so separate them.
  const spaced = [];
  blocks.forEach(b => {
    if (!b) return;
    const prev = spaced[spaced.length - 1];
    if (prev && prev.getName() === 'tbl' && b.getName() === 'tbl') {
      spaced.push(XmlService.createElement('p', NS.w));
    }
    spaced.push(b);
  });

  let at = _contentIndex(pParent, anchorP) + 1;
  spaced.forEach(b => { pParent.addContent(at, b); at++; });
}

function _isCompoundAnchor(anchor) {
  const data = _findFirstDeep(anchor, 'graphicData', NS.a);
  const uri = data && data.getAttribute('uri');
  return !!uri && [
    'http://schemas.microsoft.com/office/word/2010/wordprocessingGroup',
    'http://schemas.microsoft.com/office/word/2010/wordprocessingCanvas',
  ].indexOf(uri.getValue()) !== -1;
}

function _buildPicturePara(pic) {
  const rid = pic.blip.getAttribute('embed', NS.r);
  if (!rid || !pic.ext) return null;
  const p = XmlService.createElement('p', NS.w);
  const r = XmlService.createElement('r', NS.w);
  r.addContent(_makeInlineDrawing(rid.getValue(), pic.ext.cx, pic.ext.cy, 'Picture'));
  p.addContent(r);
  return p;
}

function _fixLegacyPicts(root) {
  const picts = _findAllDeep(root, 'pict', NS.w);
  picts.forEach(pict => {
    const shape = _findFirstDeep(pict, 'shape', NS.v);
    const imagedata = _findFirstDeep(pict, 'imagedata', NS.v);
    if (!shape || !imagedata) return;
    const ridAttr = imagedata.getAttribute('id', NS.r);
    if (!ridAttr) return;
    const rid = ridAttr.getValue();
    const style = shape.getAttribute('style') ? shape.getAttribute('style').getValue() : '';
    const wMatch = style.match(/width:([\d.]+)pt/);
    const hMatch = style.match(/height:([\d.]+)pt/);
    if (!wMatch || !hMatch) return;
    const cx = Math.round(parseFloat(wMatch[1]) * 12700);
    const cy = Math.round(parseFloat(hMatch[1]) * 12700);
    const altAttr = shape.getAttribute('alt');
    const alt = altAttr ? altAttr.getValue() : 'Picture';
    const parent = pict.getParentElement();
    // <w:pict> also appears under <w:object> and inside mc:Fallback, where a
    // <w:drawing> is not a legal child -- leave those alone.
    if (!parent || parent.getName() !== 'r') return;
    const drawing = _makeInlineDrawing(rid, cx, cy, alt);
    const idx = _contentIndex(parent, pict);
    parent.removeContent(pict);
    parent.addContent(idx, drawing); // insert the full <w:drawing> wrapper
  });
}

/**
 * Removes paragraphs left hollow by the passes above (e.g. a run whose only
 * child was an anchored drawing we relocated).
 *
 * Deliberately conservative: a paragraph counts as empty only when it has no
 * element children at all besides <w:pPr>. Listing "text bearing" tags instead
 * loses fields, footnote/comment references, symbols, embedded objects and
 * bookmarks -- all of which are real content that happens not to be <w:t>.
 */
function _removeEmptyParagraphs(root) {
  const paragraphs = _findAllDeep(root, 'p', NS.w);
  paragraphs.forEach(p => {
    const parent = p.getParentElement();
    if (!parent) return;

    // The final paragraph of a section carries <w:pPr><w:sectPr> -- page size,
    // margins and orientation all live there. Never remove it.
    const pPr = p.getChild('pPr', NS.w);
    if (pPr && pPr.getChild('sectPr', NS.w)) return;

    // OOXML requires every <w:tc> to end with a paragraph; emptying the last
    // one out of a cell produces a file Word and Google both reject.
    if (parent.getName() === 'tc' && parent.getChildren('p', NS.w).length <= 1) return;

    // A paragraph wedged between two tables is what keeps them from merging
    // into one -- Word joins adjacent <w:tbl> siblings.
    const sibs = parent.getChildren();
    const at = _childIndex(parent, p);
    if (at > 0 && at < sibs.length - 1 &&
        sibs[at - 1].getName() === 'tbl' && sibs[at + 1].getName() === 'tbl') return;

    const hasContent = p.getChildren().some(c => !_isHollow(c));
    if (!hasContent) parent.removeContent(p);
  });
}

/**
 * True for the property/formatting wrappers that carry no visible content, and
 * for runs left behind once their only child (an anchored drawing) was moved.
 */
function _isHollow(el) {
  const name = el.getName();
  if (name === 'pPr') return true;
  if (name === 'r') return el.getChildren().every(c => c.getName() === 'rPr');
  return false;
}

// ---------- Builders ----------

function _shapeFillColor(anchor) {
  const sppr = _findFirstDeep(anchor, 'spPr', NS.wps);
  if (!sppr) return null;
  if (_findFirstDeep(sppr, 'noFill', NS.a)) return null;
  const solid = sppr.getChild('solidFill', NS.a);
  if (!solid) return null;
  const srgb = solid.getChild('srgbClr', NS.a);
  if (!srgb) return null;
  const val = srgb.getAttribute('val');
  return val ? val.getValue() : null;
}

/**
 * Builds one borderless table row from the text boxes sharing a visual row --
 * two side-by-side boxes become a 1x2 table rather than two stacked 1x1s, which
 * is what keeps a two-column worksheet looking like two columns.
 */
function _buildTableFromTextboxes(boxes) {
  if (!boxes.length) return null;

  const widths = boxes.map(b => (b.ext ? Math.round(b.ext.cx / 635) : 9000));
  const totalDxa = widths.reduce((a, b) => a + b, 0);

  const tbl = XmlService.createElement('tbl', NS.w);
  const tblPr = XmlService.createElement('tblPr', NS.w);
  tblPr.addContent(XmlService.createElement('tblW', NS.w)
      .setAttribute('w', String(totalDxa), NS.w).setAttribute('type', 'dxa', NS.w));
  const borders = XmlService.createElement('tblBorders', NS.w);
  ['top', 'left', 'bottom', 'right', 'insideH', 'insideV'].forEach(side => {
    borders.addContent(XmlService.createElement(side, NS.w)
        .setAttribute('val', 'none', NS.w).setAttribute('sz', '0', NS.w)
        .setAttribute('space', '0', NS.w).setAttribute('color', 'auto', NS.w));
  });
  tblPr.addContent(borders);
  tblPr.addContent(XmlService.createElement('tblLook', NS.w).setAttribute('val', '0000', NS.w));
  tbl.addContent(tblPr);

  const grid = XmlService.createElement('tblGrid', NS.w);
  widths.forEach(w => {
    grid.addContent(XmlService.createElement('gridCol', NS.w).setAttribute('w', String(w), NS.w));
  });
  tbl.addContent(grid);

  const tr = XmlService.createElement('tr', NS.w);
  boxes.forEach((box, i) => tr.addContent(_buildCell(box, widths[i])));
  tbl.addContent(tr);
  return tbl;
}

function _buildCell(box, widthDxa) {
  const color = _shapeFillColor(box.anchor);

  const tc = XmlService.createElement('tc', NS.w);
  const tcPr = XmlService.createElement('tcPr', NS.w);
  tcPr.addContent(XmlService.createElement('tcW', NS.w)
      .setAttribute('w', String(widthDxa), NS.w).setAttribute('type', 'dxa', NS.w));
  if (color) {
    tcPr.addContent(XmlService.createElement('shd', NS.w)
        .setAttribute('val', 'clear', NS.w).setAttribute('color', 'auto', NS.w).setAttribute('fill', color, NS.w));
  }
  const tcMar = XmlService.createElement('tcMar', NS.w);
  ['top', 'left', 'bottom', 'right'].forEach(side => {
    tcMar.addContent(XmlService.createElement(side, NS.w).setAttribute('w', '120', NS.w).setAttribute('type', 'dxa', NS.w));
  });
  tcPr.addContent(tcMar);
  tcPr.addContent(XmlService.createElement('vAlign', NS.w).setAttribute('val', 'center', NS.w));
  tc.addContent(tcPr);

  // move (not copy) the original paragraphs verbatim
  const paragraphs = box.txbx.getChildren().slice();
  paragraphs.forEach(p => { box.txbx.removeContent(p); tc.addContent(p); });

  // A <w:tc> must end with a paragraph; an empty text box would leave none.
  if (!tc.getChildren('p', NS.w).length) {
    tc.addContent(XmlService.createElement('p', NS.w));
  }
  return tc;
}

function _makeInlineDrawing(rid, cx, cy, name) {
  const docPrId = _newDocPrId();
  const drawing = XmlService.createElement('drawing', NS.w);
  const inline = XmlService.createElement('inline', NS.wp)
      .setAttribute('distT', '0').setAttribute('distB', '0')
      .setAttribute('distL', '0').setAttribute('distR', '0');
  inline.addContent(XmlService.createElement('extent', NS.wp).setAttribute('cx', String(cx)).setAttribute('cy', String(cy)));
  inline.addContent(XmlService.createElement('effectExtent', NS.wp)
      .setAttribute('l', '0').setAttribute('t', '0').setAttribute('r', '0').setAttribute('b', '0'));
  inline.addContent(XmlService.createElement('docPr', NS.wp).setAttribute('id', String(docPrId)).setAttribute('name', name));
  const frameLocksWrap = XmlService.createElement('cNvGraphicFramePr', NS.wp);
  frameLocksWrap.addContent(XmlService.createElement('graphicFrameLocks', NS.a).setAttribute('noChangeAspect', '1'));
  inline.addContent(frameLocksWrap);
  const graphic = XmlService.createElement('graphic', NS.a);
  const gdata = XmlService.createElement('graphicData', NS.a)
      .setAttribute('uri', 'http://schemas.openxmlformats.org/drawingml/2006/picture');
  const pic = XmlService.createElement('pic', NS.pic);
  const nvPicPr = XmlService.createElement('nvPicPr', NS.pic);
  nvPicPr.addContent(XmlService.createElement('cNvPr', NS.pic).setAttribute('id', String(docPrId)).setAttribute('name', name));
  nvPicPr.addContent(XmlService.createElement('cNvPicPr', NS.pic));
  pic.addContent(nvPicPr);
  const blipFill = XmlService.createElement('blipFill', NS.pic);
  blipFill.addContent(XmlService.createElement('blip', NS.a).setAttribute('embed', rid, NS.r));
  const stretch = XmlService.createElement('stretch', NS.a);
  stretch.addContent(XmlService.createElement('fillRect', NS.a));
  blipFill.addContent(stretch);
  pic.addContent(blipFill);
  const spPr = XmlService.createElement('spPr', NS.pic);
  const xfrm = XmlService.createElement('xfrm', NS.a);
  xfrm.addContent(XmlService.createElement('off', NS.a).setAttribute('x', '0').setAttribute('y', '0'));
  xfrm.addContent(XmlService.createElement('ext', NS.a).setAttribute('cx', String(cx)).setAttribute('cy', String(cy)));
  spPr.addContent(xfrm);
  const geom = XmlService.createElement('prstGeom', NS.a).setAttribute('prst', 'rect');
  geom.addContent(XmlService.createElement('avLst', NS.a));
  spPr.addContent(geom);
  pic.addContent(spPr);
  gdata.addContent(pic);
  graphic.addContent(gdata);
  inline.addContent(graphic);
  drawing.addContent(inline);
  return drawing;
}

// ---------- Header/footer full-page background stripping ----------

function _getPageAspect(documentXmlString) {
  // Match each attribute independently -- Word emits w:w and w:h in either
  // order, and a single regex with two groups silently swaps them.
  const tag = documentXmlString.match(/<w:pgSz[^>]*>/);
  if (!tag) return null;
  const wm = tag[0].match(/\sw:w="(\d+)"/);
  const hm = tag[0].match(/\sw:h="(\d+)"/);
  if (!wm || !hm) return null;
  const w = parseInt(wm[1], 10), h = parseInt(hm[1], 10);
  if (!w || !h) return null;
  return w / h;
}

function _stripFullPageBackground(partXmlString, relsXmlString, byName, pageAspect) {
  if (!pageAspect || !relsXmlString) return null;
  const ridToTarget = {};
  const relMatches = relsXmlString.matchAll(/<Relationship[^>]*Id="([^"]+)"[^>]*Type="[^"]*\/image"[^>]*Target="([^"]+)"/g);
  for (const m of relMatches) ridToTarget[m[1]] = m[2];
  if (Object.keys(ridToTarget).length === 0) return null;

  let changed = false;
  let xml = partXmlString;
  // Don't require a self-closing tag: blips carrying <a:extLst> children are
  // common on images with effects applied, and we only need the rId.
  const blipMatches = [...xml.matchAll(/<a:blip[^>]*r:embed="([^"]+)"/g)];
  blipMatches.forEach(m => {
    const rid = m[1];
    const target = ridToTarget[rid];
    if (!target) return;
    const mediaBlob = byName['word/' + target.replace(/^\.?\//, '')];
    if (!mediaBlob) return;
    const size = _imagePixelSize(mediaBlob);
    if (!size) return;
    if (size.w < 1200 || size.h < 1200) return;
    const aspect = size.w / size.h;
    if (Math.abs(aspect - pageAspect) / pageAspect > 0.05) return;
    // crude but effective: drop the whole containing <w:drawing>...</w:drawing>
    // or <w:pict>...</w:pict> that wraps this blip reference
    const before = xml;
    xml = xml.replace(new RegExp('<w:drawing>(?:(?!</w:drawing>).)*?r:embed="' + rid + '"(?:(?!</w:drawing>).)*?</w:drawing>', 's'), '');
    if (xml === before) {
      xml = xml.replace(new RegExp('<w:pict>(?:(?!</w:pict>).)*?r:id="' + rid + '"(?:(?!</w:pict>).)*?</w:pict>', 's'), '');
    }
    if (xml !== before) changed = true;
  });
  return changed ? xml : null;
}

function _imagePixelSize(blob) {
  const bytes = blob.getBytes();
  const name = blob.getName() || '';
  try {
    if (/\.png$/i.test(name)) {
      // PNG: width/height are big-endian 4-byte ints at offset 16/20
      const w = _u32be(bytes, 16), h = _u32be(bytes, 20);
      return { w, h };
    }
    if (/\.jpe?g$/i.test(name)) {
      return _jpegSize(bytes);
    }
  } catch (e) {
    return null;
  }
  return null;
}

function _u32be(bytes, offset) {
  return ((bytes[offset] & 0xff) << 24) | ((bytes[offset + 1] & 0xff) << 16) |
         ((bytes[offset + 2] & 0xff) << 8) | (bytes[offset + 3] & 0xff);
}

function _jpegSize(bytes) {
  let i = 2; // skip SOI
  while (i < bytes.length) {
    if ((bytes[i] & 0xff) !== 0xff) { i++; continue; }
    const marker = bytes[i + 1] & 0xff;
    if (marker >= 0xc0 && marker <= 0xcf && marker !== 0xc4 && marker !== 0xc8 && marker !== 0xcc) {
      const h = ((bytes[i + 5] & 0xff) << 8) | (bytes[i + 6] & 0xff);
      const w = ((bytes[i + 7] & 0xff) << 8) | (bytes[i + 8] & 0xff);
      return { w, h };
    }
    const segLen = ((bytes[i + 2] & 0xff) << 8) | (bytes[i + 3] & 0xff);
    i += 2 + segLen;
  }
  return null;
}

// ---------- XmlService helpers (getDescendants-style deep search) ----------

/**
 * XmlService's Element has no indexOf(), and its wrapper objects cannot be
 * compared with === -- two reads of the same node hand back different
 * JavaScript objects. Both problems are solved the same way: stamp the node
 * with a throwaway attribute, find the stamp, wipe it.
 *
 * Every marker is removed again before the document is serialized; _clearMarks
 * is the backstop for keys deliberately left in place during a pass.
 */
const _MARK = 'docxFixerMark';
let _markSeq = 0;

function _withMark(el, fn) {
  const had = el.getAttribute(_MARK);
  const token = had ? had.getValue() : 'm' + (++_markSeq);
  if (!had) el.setAttribute(_MARK, token);
  try {
    return fn(token);
  } finally {
    if (!had) {
      const a = el.getAttribute(_MARK);
      if (a) el.removeAttribute(a);
    }
  }
}

/** Index of `child` among ALL of parent's content -- what addContent(i, c) wants. */
function _contentIndex(parent, child) {
  return _withMark(child, token => {
    const all = parent.getAllContent();
    for (let i = 0; i < all.length; i++) {
      const c = all[i];
      if (c.getType() !== XmlService.ContentTypes.ELEMENT) continue;
      const a = c.asElement().getAttribute(_MARK);
      if (a && a.getValue() === token) return i;
    }
    return -1;
  });
}

/** Index of `child` among parent's element children only. */
function _childIndex(parent, child) {
  return _withMark(child, token => {
    const kids = parent.getChildren();
    for (let i = 0; i < kids.length; i++) {
      const a = kids[i].getAttribute(_MARK);
      if (a && a.getValue() === token) return i;
    }
    return -1;
  });
}

/** Stable string identity for an element, used to group by anchoring paragraph. */
function _markKey(el) {
  const had = el.getAttribute(_MARK);
  if (had) return had.getValue();
  const token = 'm' + (++_markSeq);
  el.setAttribute(_MARK, token);
  return token;
}

function _clearMarks(root) {
  _findAllDeep(root, null, null).forEach(el => {
    const a = el.getAttribute(_MARK);
    if (a) el.removeAttribute(a);
  });
}

function _findAllDeep(root, localName, ns) {
  const out = [];
  const stack = [root];
  while (stack.length) {
    const el = stack.pop();
    // A null localName matches every element -- used for whole-tree sweeps.
    if (el.getName && (localName === null || el.getName() === localName) &&
        (!ns || el.getNamespace().getURI() === ns.getURI())) {
      out.push(el);
    }
    const children = el.getChildren ? el.getChildren() : [];
    for (let i = children.length - 1; i >= 0; i--) stack.push(children[i]);
  }
  return out;
}

function _findFirstDeep(root, localName, ns) {
  const all = _findAllDeep(root, localName, ns);
  return all.length ? all[0] : null;
}
