'use strict';
const $ = id => document.getElementById(id);
let session, sourceHash, selected, reportUrl, source, gapiLoading;
async function request(url, options = {}) {
  const response = await fetch(url, options);
  // A proxy's 413 or a plain-text server error is not JSON; show our own words, not a parse error.
  const body = await response.json().catch(() => null);
  if (!response.ok || !body) throw new Error(body?.error?.message || 'The request failed. Please try again.');
  return body;
}
function busy(value) { for (const id of ['file','pick-drive','analyse','convert','logout']) $(id).disabled = value; }
// The on-page summary above this is the report for a person; this is the
// same data as raw JSON for IT/support to troubleshoot with. Tucked behind
// <details> so a trial user isn't handed a JSON file as if it were the answer.
function download(report, parent) {
  if (reportUrl) URL.revokeObjectURL(reportUrl);
  reportUrl = URL.createObjectURL(new Blob([JSON.stringify(report, null, 2)], {type:'application/json'}));
  const details = document.createElement('details');
  const summary = document.createElement('summary'); summary.textContent = 'Advanced: full technical report';
  const note = document.createElement('p'); note.textContent = 'For IT support or troubleshooting — not needed for everyday use.';
  const a = document.createElement('a'); a.href = reportUrl; a.download = 'conversion-report.json'; a.textContent = 'Download full report (.json)';
  details.append(summary, note, a);
  parent.append(details);
}
function link(url, label, parent) {
  const parsed = new URL(url);
  if (parsed.protocol !== 'https:' || !['docs.google.com','drive.google.com'].includes(parsed.hostname)) return;
  const p = document.createElement('p'), a = document.createElement('a'); a.href = url; a.textContent = label; a.target = '_blank'; a.rel = 'noopener noreferrer'; p.append(a); parent.append(p);
}
// `source` is one shape whichever way a file arrived: a browser upload
// carries its own File to send as the request body; a Drive pick carries
// only an id, which the server downloads itself (see /api/picker-token and
// web.py's x-drive-file-id handling) -- nothing here ever sees its bytes.
function pipelineFor(src) {
  const dot = src.name.lastIndexOf('.');
  const ext = dot === -1 ? '' : src.name.slice(dot).toLowerCase();
  return (session.formats || []).find(f => f.extension === ext);
}
function resetChoice() {
  sourceHash = null; selected = null; $('convert').hidden = true;
  $('summary').replaceChildren(); $('result').replaceChildren();
  $('picked').textContent = source ? `Selected: ${source.name}` : '';
}
function loadPicker() {
  if (gapiLoading) return gapiLoading;
  gapiLoading = new Promise((resolve, reject) => {
    const script = document.createElement('script');
    script.src = 'https://apis.google.com/js/api.js';
    script.onload = () => gapi.load('picker', {callback: resolve, onerror: () => reject(new Error('Could not load Google Drive picker.'))});
    script.onerror = () => reject(new Error('Could not load Google Drive picker.'));
    document.head.append(script);
  });
  return gapiLoading;
}
async function openPicker() {
  if (!session.pickerEnabled) throw new Error('Adding a file from Drive is not available.');
  await loadPicker();
  const {accessToken} = await request('/api/picker-token');
  const mimeTypes = (session.formats || []).map(f => f.mime).join(',');
  await new Promise(resolve => {
    const view = new google.picker.DocsView().setMimeTypes(mimeTypes).setIncludeFolders(false).setSelectFolderEnabled(false);
    const picker = new google.picker.PickerBuilder()
      .addView(view)
      .setOAuthToken(accessToken)
      .setDeveloperKey(session.pickerApiKey)
      .setAppId(session.pickerAppId)
      .setCallback(data => {
        if (data.action === google.picker.Action.PICKED) {
          const doc = data.docs[0];
          source = {name: doc.name, size: doc.sizeBytes ? Number(doc.sizeBytes) : 0, driveId: doc.id};
          $('file').value = '';
          resetChoice();
          resolve();
        } else if (data.action === google.picker.Action.CANCEL) {
          resolve();
        }
      })
      .build();
    picker.setVisible(true);
  });
}
async function upload(convert) {
  if (!source || !pipelineFor(source)) throw new Error('Please choose a ' + (session.formats || []).map(f => f.extension).join(' or ') + ' file.');
  // No limit unless the deployment sets one (maxUploadBytes is then a number, not null).
  if (session.maxUploadBytes && source.size && source.size > session.maxUploadBytes) throw new Error('This file exceeds the upload limit.');
  if (convert && (source !== selected || !sourceHash)) throw new Error('Please check this file first.');
  const headers = {'X-Upload-Filename':encodeURIComponent(source.name),'X-CSRF-Token':session.csrfToken};
  if (convert) headers['X-Source-Sha256'] = sourceHash;
  if (source.driveId) {
    headers['Content-Type'] = 'application/octet-stream';
    headers['X-Drive-File-Id'] = source.driveId;
    return request(convert ? '/api/convert' : '/api/analyse', {method:'POST', headers});
  }
  headers['Content-Type'] = source.file.type || 'application/octet-stream';
  return request(convert ? '/api/convert' : '/api/analyse', {method:'POST', headers, body:source.file});
}
async function perform(convert) {
  const chosen = source && pipelineFor(source);
  busy(true); $('status').textContent = convert ? 'Converting and checking your file…' : 'Checking your file…';
  try {
    const report = await upload(convert);
    const parent = convert ? $('result') : $('summary'); parent.replaceChildren();
    const unit = chosen && chosen.kind === 'document' ? 'sections' : 'slides';
    const p = document.createElement('p'); p.textContent = `${report.pages} ${unit} · ${Object.values(report.assetCounts).reduce((a,b)=>a+b,0)} recovered files · ${report.warnings.length} items to review`; parent.append(p);
    const list = document.createElement('ul');
    for (const message of [...new Set(report.warnings.map(w=>w.message))]) { const li = document.createElement('li'); li.textContent = message; list.append(li); }
    parent.append(list);
    if (!convert) { sourceHash = report.sourceSha256; selected = source; $('convert').hidden = false; }
    else {
      if (report.url) link(report.url, 'Open in ' + ((chosen && chosen.destination) || 'Google Drive'), parent);
      if (report.folderUrl) link(report.folderUrl, 'Open recovered files in Drive', parent);
      $('convert').hidden = true;
    }
    download(report, parent);
    $('status').textContent = !convert ? 'Ready to convert. Review the findings above.' : report.status.startsWith('failed') ? 'Conversion did not finish. Check the report and any saved files before retrying.' : 'Conversion finished. Please review the result and report.';
  } catch (error) { $('status').textContent = error.message; }
  finally { busy(false); }
}
$('analyse').addEventListener('click', ()=>perform(false));
$('convert').addEventListener('click', ()=>perform(true));
$('pick-drive').addEventListener('click', async ()=>{ try { await openPicker(); } catch (e) { $('status').textContent = e.message; } });
$('file').addEventListener('change', ()=>{ const file = $('file').files[0]; source = file ? {name:file.name, size:file.size, file} : null; resetChoice(); });
$('logout').addEventListener('click', async ()=>{try{await request('/auth/logout',{method:'POST',headers:{'X-CSRF-Token':session.csrfToken}});location.reload();}catch(e){$('status').textContent=e.message;}});
request('/api/session').then(s=>{session=s;$('signin').hidden=s.signedIn;$('logout').hidden=!s.signedIn;$('workspace').hidden=!s.signedIn;$('pick-drive').hidden=!s.pickerEnabled;$('limit').textContent=s.maxUploadBytes?`Upload limit: ${Math.round(s.maxUploadBytes/1024/1024)} MiB.`:'';if(!s.signedIn&&!s.configured)$('status').textContent='Google sign-in needs to be configured by the application owner.';}).catch(e=>{$('status').textContent=e.message;});
