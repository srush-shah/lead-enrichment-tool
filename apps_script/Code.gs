/**
 * EliseAI GTM enrichment — Sheets <-> FastAPI bridge.
 *
 * Expected sheet layout (row 1 = headers):
 *   A: name | B: email | C: company | D: property_address | E: city
 *   F: state | G: country | H: status | I: tier | J: score
 *   K: why_now | L: talking_point | M: objection_preempt
 *   N: draft_email_subject | O: draft_email_body
 *   P: msa | Q: renter_pct | R: pct_5plus | S: median_rent | T: walkscore
 *   U: has_wikipedia | V: news_count | W: evidence_links | X: enriched_at
 *
 * Status column (H) values: "Ready" -> queue for enrichment;
 *   "Enriched" / "Skipped" / "Error" -> set by this script.
 */

const BACKEND_URL = 'https://YOUR-RENDER-APP.onrender.com';
const SHARED_SECRET = PropertiesService.getScriptProperties().getProperty('WEBHOOK_SECRET');
const SHEET_NAME = 'Leads';

const COL = {
  name: 1, email: 2, company: 3, property_address: 4, city: 5, state: 6, country: 7,
  status: 8, tier: 9, score: 10,
  why_now: 11, talking_point: 12, objection_preempt: 13,
  subject: 14, body: 15,
  msa: 16, renter_pct: 17, pct_5plus: 18, median_rent: 19, walkscore: 20,
  has_wiki: 21, news_count: 22, evidence: 23, enriched_at: 24,
};

/* ---------- Triggers ---------- */

function onEdit(e) {
  if (!e || !e.range) return;
  const sheet = e.range.getSheet();
  if (sheet.getName() !== SHEET_NAME) return;
  if (e.range.getColumn() !== COL.status) return;
  const val = String(e.value || '').trim().toLowerCase();
  if (val !== 'ready') return;

  const row = e.range.getRow();
  const lead = readLead_(sheet, row);
  if (!lead) return;
  sheet.getRange(row, COL.status).setValue('Processing…');
  try {
    const result = callBackend_('/enrich/realtime', [lead]);
    writeResult_(sheet, row, result.leads[0]);
  } catch (err) {
    sheet.getRange(row, COL.status).setValue('Error: ' + err.message);
  }
}

function dailyBatch() {
  const sheet = SpreadsheetApp.getActive().getSheetByName(SHEET_NAME);
  const lastRow = sheet.getLastRow();
  if (lastRow < 2) return;
  const range = sheet.getRange(2, 1, lastRow - 1, COL.country);
  const rows = range.getValues();

  const queued = [];
  rows.forEach((r, i) => {
    const status = String(sheet.getRange(i + 2, COL.status).getValue() || '').trim().toLowerCase();
    if (!status || status === 'ready' || status === 'queued') {
      const lead = rowToLead_(r);
      if (lead) queued.push({ row: i + 2, lead: lead });
    }
  });

  if (!queued.length) return;

  // Chunk by 50 to fit one batch window.
  for (let i = 0; i < queued.length; i += 50) {
    const slice = queued.slice(i, i + 50);
    slice.forEach(q => sheet.getRange(q.row, COL.status).setValue('Processing…'));
    try {
      const result = callBackend_('/enrich/batch', slice.map(q => q.lead));
      result.leads.forEach((enriched, idx) => writeResult_(sheet, slice[idx].row, enriched));
    } catch (err) {
      slice.forEach(q => sheet.getRange(q.row, COL.status).setValue('Error: ' + err.message));
    }
  }
}

/* ---------- Helpers ---------- */

function readLead_(sheet, row) {
  const values = sheet.getRange(row, 1, 1, COL.country).getValues()[0];
  return rowToLead_(values);
}

function rowToLead_(r) {
  if (!r[COL.email - 1] || !r[COL.company - 1]) return null;
  return {
    name: String(r[COL.name - 1] || '').trim(),
    email: String(r[COL.email - 1] || '').trim(),
    company: String(r[COL.company - 1] || '').trim(),
    property_address: String(r[COL.property_address - 1] || '').trim(),
    city: String(r[COL.city - 1] || '').trim(),
    state: String(r[COL.state - 1] || '').trim(),
    country: String(r[COL.country - 1] || 'USA').trim(),
  };
}

function writeResult_(sheet, row, enriched) {
  const brief = enriched.brief || {};
  const updates = [
    [COL.status, enriched.tier === 'Skipped' ? ('Skipped: ' + (enriched.skipped_reason || 'low MPS')) : 'Enriched'],
    [COL.tier, enriched.tier],
    [COL.score, enriched.score],
    [COL.why_now, brief.why_now || ''],
    [COL.talking_point, brief.talking_point || ''],
    [COL.objection_preempt, brief.objection_preempt || ''],
    [COL.subject, enriched.draft_email_subject || ''],
    [COL.body, enriched.draft_email_body || ''],
    [COL.msa, enriched.msa || ''],
    [COL.renter_pct, (enriched.census && enriched.census.renter_occupied_pct) || ''],
    [COL.pct_5plus, (enriched.census && enriched.census.pct_5plus_units) || ''],
    [COL.median_rent, (enriched.census && enriched.census.median_gross_rent) || ''],
    [COL.walkscore, (enriched.walk && enriched.walk.walkscore) || ''],
    [COL.has_wiki, (enriched.company && enriched.company.has_wikipedia) ? 'Yes' : 'No'],
    [COL.news_count, (enriched.news && enriched.news.articles) ? enriched.news.articles.length : 0],
    [COL.evidence, (brief.evidence_links || []).join(' | ')],
    [COL.enriched_at, enriched.enriched_at || new Date().toISOString()],
  ];
  updates.forEach(([col, val]) => sheet.getRange(row, col).setValue(val));

  if (enriched.tier === 'Skipped') {
    sheet.getRange(row, 1, 1, COL.enriched_at).setBackground('#f0f0f0');
  } else if (enriched.tier === 'A') {
    sheet.getRange(row, 1, 1, COL.enriched_at).setBackground('#d9ead3');
  } else if (enriched.tier === 'B') {
    sheet.getRange(row, 1, 1, COL.enriched_at).setBackground('#fff2cc');
  }
}

function callBackend_(path, leads) {
  const body = JSON.stringify({ leads: leads });
  const sig = hmacHex_(SHARED_SECRET, body);
  const resp = UrlFetchApp.fetch(BACKEND_URL + path, {
    method: 'post',
    contentType: 'application/json',
    headers: { 'X-Signature': sig },
    payload: body,
    muteHttpExceptions: true,
  });
  if (resp.getResponseCode() >= 400) {
    throw new Error('HTTP ' + resp.getResponseCode() + ': ' + resp.getContentText().slice(0, 200));
  }
  return JSON.parse(resp.getContentText());
}

function hmacHex_(secret, body) {
  const sigBytes = Utilities.computeHmacSha256Signature(body, secret);
  return sigBytes.map(b => {
    const v = (b + 256) % 256;
    return (v < 16 ? '0' : '') + v.toString(16);
  }).join('');
}

/* ---------- One-time setup ---------- */

function installDailyTrigger() {
  ScriptApp.getProjectTriggers().forEach(t => {
    if (t.getHandlerFunction() === 'dailyBatch') ScriptApp.deleteTrigger(t);
  });
  ScriptApp.newTrigger('dailyBatch')
    .timeBased()
    .atHour(9)
    .everyDays(1)
    .inTimezone('America/New_York')
    .create();
}
