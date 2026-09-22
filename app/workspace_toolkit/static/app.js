'use strict';
const $ = id => document.getElementById(id);
let session, sourceHash, selected, reportUrl;
async function request(url, options = {}) {
  const response = await fetch(url, options);
  const body = await response.json();
  if (!response.ok) throw new Error(body.error?.message || 'The request failed. Please try again.');
  return body;
}
function busy(value) { for (const id of ['file','analyse','convert','logout']) $(id).disabled = value; }
function download(report, parent) {
  if (reportUrl) URL.revokeObjectURL(reportUrl);
  reportUrl = URL.createObjectURL(new Blob([JSON.stringify(report, null, 2)], {type:'application/json'}));
  const a = document.createElement('a'); a.href = reportUrl; a.download = 'conversion-report.json'; a.textContent = 'Download report'; parent.append(a);
}
function link(url, label, parent) {
  const parsed = new URL(url);
  if (parsed.protocol !== 'https:' || !['docs.google.com','drive.google.com'].includes(parsed.hostname)) return;
  const p = document.createElement('p'), a = document.createElement('a'); a.href = url; a.textContent = label; a.target = '_blank'; a.rel = 'noopener noreferrer'; p.append(a); parent.append(p);
}
function pipelineFor(file) {
  const dot = file.name.lastIndexOf('.');
  const ext = dot === -1 ? '' : file.name.slice(dot).toLowerCase();
  return (session.formats || []).find(f => f.extension === ext);
}
async function upload(convert) {
  const file = $('file').files[0];
  if (!file || !pipelineFor(file)) throw new Error('Please choose a ' + (session.formats || []).map(f => f.extension).join(' or ') + ' file.');
  if (file.size > session.maxUploadBytes) throw new Error('This file exceeds the upload limit.');
  if (convert && (file !== selected || !sourceHash)) throw new Error('Please check this file first.');
  const headers = {'Content-Type':file.type || 'application/octet-stream','X-Upload-Filename':encodeURIComponent(file.name),'X-CSRF-Token':session.csrfToken};
  if (convert) headers['X-Source-Sha256'] = sourceHash;
  return request(convert ? '/api/convert' : '/api/analyse', {method:'POST', headers, body:file});
}
async function perform(convert) {
  const chosen = $('file').files[0] && pipelineFor($('file').files[0]);
  busy(true); $('status').textContent = convert ? 'Converting and checking your file…' : 'Checking your file…';
  try {
    const report = await upload(convert);
    const parent = convert ? $('result') : $('summary'); parent.replaceChildren();
    const unit = chosen && chosen.kind === 'document' ? 'sections' : 'slides';
    const p = document.createElement('p'); p.textContent = `${report.pages} ${unit} · ${Object.values(report.assetCounts).reduce((a,b)=>a+b,0)} recovered files · ${report.warnings.length} items to review`; parent.append(p);
    const list = document.createElement('ul');
    for (const message of [...new Set(report.warnings.map(w=>w.message))]) { const li = document.createElement('li'); li.textContent = message; list.append(li); }
    parent.append(list);
    if (!convert) { sourceHash = report.sourceSha256; selected = $('file').files[0]; $('convert').hidden = false; }
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
$('file').addEventListener('change', ()=>{sourceHash=null;selected=null;$('convert').hidden=true;$('summary').replaceChildren();$('result').replaceChildren();});
$('logout').addEventListener('click', async ()=>{try{await request('/auth/logout',{method:'POST',headers:{'X-CSRF-Token':session.csrfToken}});location.reload();}catch(e){$('status').textContent=e.message;}});
request('/api/session').then(s=>{session=s;$('signin').hidden=s.signedIn;$('logout').hidden=!s.signedIn;$('workspace').hidden=!s.signedIn;$('limit').textContent=`Upload limit: ${Math.round(s.maxUploadBytes/1024/1024)} MiB.`;if(!s.signedIn&&!s.configured)$('status').textContent='Google sign-in needs to be configured by the application owner.';}).catch(e=>{$('status').textContent=e.message;});
