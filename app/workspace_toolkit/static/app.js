'use strict';
// One step, for a teacher whose files did not come across to Google well
// (DECISIONS.md, 2026-09-29): choose one or more files, press Convert, get
// the Google files. No notes on screen: every note is in the report saved in
// each conversion's Drive folder, for whoever supports the app.
const $ = id => document.getElementById(id);
let session, gapiLoading, chosen = [];
async function request(url, options = {}) {
  const response = await fetch(url, options);
  // A proxy's 413 or a plain-text server error is not JSON; show our own words, not a parse error.
  const body = await response.json().catch(() => null);
  if (!response.ok || !body) throw new Error(body?.error?.message || 'The request failed. Please try again.');
  return body;
}
function busy(value) { for (const id of ['file','pick-drive','convert','smaller','logout']) $(id).disabled = value; }
function link(url, label) {
  const parsed = new URL(url);
  if (parsed.protocol !== 'https:' || !['docs.google.com','drive.google.com'].includes(parsed.hostname)) return null;
  const a = document.createElement('a'); a.href = url; a.textContent = label; a.target = '_blank'; a.rel = 'noopener noreferrer';
  return a;
}
// Each chosen file is one shape whichever way it arrived: a browser upload
// carries its own File to send as the request body; a Drive pick carries
// only an id, which the server downloads itself (see /api/picker-token and
// web.py's x-drive-file-id handling) -- nothing here ever sees its bytes.
function pipelineFor(src) {
  const dot = src.name.lastIndexOf('.');
  const ext = dot === -1 ? '' : src.name.slice(dot).toLowerCase();
  return (session.formats || []).find(f => f.extension === ext);
}
// Why a file can't be converted here, in plain words, or '' if it can.
function refusal(src) {
  const format = pipelineFor(src);
  if (!format) return 'This kind of file can’t be converted.';
  if (format.convertible === false) return 'Converting this kind of file isn’t set up here yet.';
  // No limit unless the deployment sets one (maxUploadBytes is then a number, not null).
  if (session.maxUploadBytes && src.size && src.size > session.maxUploadBytes) return 'This file is too large.';
  return '';
}
function choose(files) {
  chosen = files.map(src => ({...src, row: null}));
  const list = $('files'); list.replaceChildren();
  for (const src of chosen) {
    const li = document.createElement('li');
    const name = document.createElement('span'); name.className = 'name'; name.textContent = src.name;
    const state = document.createElement('span'); state.className = 'state'; state.textContent = refusal(src);
    li.append(name, state); list.append(li); src.row = state;
  }
  const ready = chosen.filter(src => !refusal(src));
  $('convert').hidden = !ready.length;
  $('convert').textContent = ready.length > 1 ? `Convert ${ready.length} files` : 'Convert';
  // Only a PowerPoint or Word file can have its pictures made smaller (see web.py).
  $('smaller-choice').hidden = !ready.some(src => ['.pptx','.docx'].includes(pipelineFor(src).extension));
  $('smaller').checked = false;
  $('status').textContent = '';
}
// One load at a time, shared while it runs or once it worked. A failed load
// is forgotten, and its script removed, so the next try starts again (#132).
function loadPicker() {
  if (gapiLoading) return gapiLoading;
  let script = null;
  gapiLoading = new Promise((resolve, reject) => {
    const failed = () => reject(new Error('Could not load Google Drive picker.'));
    const picker = () => gapi.load('picker', {callback: resolve, onerror: failed});
    if (typeof gapi !== 'undefined') return picker();  // the script came, the picker didn't
    script = document.createElement('script');
    script.src = 'https://apis.google.com/js/api.js';
    script.onload = picker;
    script.onerror = failed;
    document.head.append(script);
  }).catch(error => {
    gapiLoading = null;
    if (script && typeof gapi === 'undefined') script.remove();
    throw error;
  });
  return gapiLoading;
}
async function openPicker() {
  if (!session.pickerEnabled) throw new Error('Choosing files from Drive is not available.');
  await loadPicker();
  const {accessToken} = await request('/api/picker-token');
  const mimeTypes = (session.formats || []).map(f => f.mime).join(',');
  await new Promise(resolve => {
    // Folders can be opened, and every file in one selected at once: that
    // is how a whole folder is converted under the drive.file scope, which
    // only lets the app open files the person picked.
    const view = new google.picker.DocsView().setMimeTypes(mimeTypes).setIncludeFolders(true).setSelectFolderEnabled(false);
    const picker = new google.picker.PickerBuilder()
      .addView(view)
      .enableFeature(google.picker.Feature.MULTISELECT_ENABLED)
      .setOAuthToken(accessToken)
      .setDeveloperKey(session.pickerApiKey)
      .setAppId(session.pickerAppId)
      .setCallback(data => {
        if (data.action === google.picker.Action.PICKED) {
          $('file').value = '';
          choose(data.docs.map(doc => ({name: doc.name, size: doc.sizeBytes ? Number(doc.sizeBytes) : 0, driveId: doc.id})));
          resolve();
        } else if (data.action === google.picker.Action.CANCEL) {
          resolve();
        }
      })
      .build();
    picker.setVisible(true);
  });
}
function send(src) {
  const headers = {'X-Upload-Filename': encodeURIComponent(src.name), 'X-CSRF-Token': session.csrfToken};
  if ($('smaller').checked) headers['X-Compress-Pictures'] = '1';
  if (src.driveId) {
    headers['Content-Type'] = 'application/octet-stream';
    headers['X-Drive-File-Id'] = src.driveId;
    return request('/api/convert', {method: 'POST', headers});
  }
  headers['Content-Type'] = src.file.type || 'application/octet-stream';
  return request('/api/convert', {method: 'POST', headers, body: src.file});
}
async function convertAll() {
  const queue = chosen.filter(src => !refusal(src));
  let done = 0, failed = 0;
  busy(true);
  try {
    // One at a time: the server converts one file at once, and a teacher
    // sees each file finish.
    for (const [index, src] of queue.entries()) {
      $('status').textContent = queue.length > 1 ? `Converting ${index + 1} of ${queue.length}…` : 'Converting…';
      src.row.replaceChildren('Converting…');
      try {
        const report = await send(src);
        const format = pipelineFor(src);
        const open = report.url && link(report.url, 'Open in ' + (format.destination || 'Google Drive'));
        const folder = report.folderUrl && link(report.folderUrl, 'Folder');
        if (report.status && report.status.startsWith('failed')) {
          failed += 1;
          const why = report.stoppedBecause ? `Didn’t finish: ${report.stoppedBecause} ` : 'Didn’t finish. ';
          src.row.replaceChildren(why, ...(folder ? [folder] : []));
        } else {
          done += 1;
          src.row.replaceChildren(...[open, folder].filter(Boolean).flatMap((a, i) => i ? [' · ', a] : [a]));
        }
      } catch (error) {
        failed += 1;
        src.row.replaceChildren('Couldn’t convert: ' + error.message);
      }
    }
    $('convert').hidden = true;
    $('smaller-choice').hidden = true;
    $('status').textContent = failed
      ? `${done} converted, ${failed} couldn’t be.`
      : done > 1 ? `All ${done} files converted.` : 'Converted.';
  } finally { busy(false); }
}
$('convert').addEventListener('click', convertAll);
$('pick-drive').addEventListener('click', async () => { try { await openPicker(); } catch (e) { $('status').textContent = e.message; } });
$('file').addEventListener('change', () => choose([...$('file').files].map(file => ({name: file.name, size: file.size, file}))));
$('logout').addEventListener('click', async () => { try { await request('/auth/logout', {method: 'POST', headers: {'X-CSRF-Token': session.csrfToken}}); location.reload(); } catch (e) { $('status').textContent = e.message; } });
request('/api/session').then(s => {
  session = s;
  $('signin').hidden = s.signedIn; $('logout').hidden = !s.signedIn; $('workspace').hidden = !s.signedIn; $('pick-drive').hidden = !s.pickerEnabled;
  $('limit').textContent = s.maxUploadBytes ? `Up to ${Math.round(s.maxUploadBytes / 1024 / 1024)} MB each.` : '';
  if (!s.signedIn && !s.configured) $('status').textContent = 'Google sign-in needs to be configured by the application owner.';
}).catch(e => { $('status').textContent = e.message; });
