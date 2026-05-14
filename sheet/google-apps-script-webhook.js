/**
 * NabtaLabo Orders → Google Sheet (Web App `/exec`).
 *
 * Row 1 headers must match Nabtalabo (Sheet1.csv):
 * DATE,ORDERID,COUNTRYC,NAME,PHONE,PRODUCT,SKU,QUANTITY,TOTALPRICE,CURRENCY,STATUS
 *
 * Deploy from the spreadsheet: Extensions → Apps Script → paste → Deploy → Web app
 * Execute as: Me · Who has access: Anyone / Anyone with link
 * Backend env: GOOGLE_SHEET_WEBHOOK_URL = paste URL ending in /exec (no separate secret variable).
 */

var WEBHOOK_VERSION = 3;

var SPREADSHEET_ID = '';
var SHEET_TAB_NAME = '';

function getSpreadsheet_() {
  var sid = SPREADSHEET_ID ? String(SPREADSHEET_ID).trim() : '';
  if (sid.length > 0) {
    return SpreadsheetApp.openById(sid);
  }
  var ss = SpreadsheetApp.getActiveSpreadsheet();
  if (!ss) {
    throw new Error(
      'Standalone: set SPREADSHEET_ID from the Sheet URL (…/d/ID/edit), or attach the script from inside the Spreadsheet.'
    );
  }
  return ss;
}

function getTargetSheet_() {
  var ss = getSpreadsheet_();
  var tab = SHEET_TAB_NAME ? String(SHEET_TAB_NAME).trim() : '';
  if (tab.length > 0) {
    var sh = ss.getSheetByName(tab);
    if (!sh) {
      throw new Error('Tab not found: "' + tab + '" — fix SHEET_TAB_NAME.');
    }
    return sh;
  }
  var sheets = ss.getSheets();
  if (!sheets || sheets.length === 0) {
    throw new Error('Spreadsheet has no sheets.');
  }
  return sheets[0];
}

function isEmptyValue_(v) {
  if (v === undefined || v === null) {
    return true;
  }
  if (typeof v === 'number') {
    return isNaN(v);
  }
  return String(v).trim() === '';
}

function normalizePayloadAliases_(data) {
  var d = data;
  if (d.ORDERID && d.order_id == null) d.order_id = d.ORDERID;
  if (d.TOTALPRICE != null && d.total_price == null) d.total_price = d.TOTALPRICE;
  return d;
}

/** @returns {Object|null} null = OK */
function validatePayload_(data) {
  if (typeof data !== 'object' || data === null || Array.isArray(data)) {
    return { error: 'payload_not_object', hint: 'Send JSON POST from Nabtalabo API (POST /api/orders).' };
  }

  normalizePayloadAliases_(data);

  var keys = ['date', 'order_id', 'country', 'name', 'phone', 'product', 'sku', 'quantity', 'total_price', 'currency'];

  var labels = {
    date: 'date',
    order_id: 'order_id (nabta…)',
    country: 'country',
    name: 'name',
    phone: 'phone (966…)',
    product: 'product',
    sku: 'sku',
    quantity: 'quantity',
    total_price: 'total_price',
    currency: 'currency',
  };

  for (var i = 0; i < keys.length; i++) {
    var k = keys[i];
    if (k === 'total_price') {
      if (data[k] === undefined || data[k] === null || isNaN(Number(data[k]))) {
        return { error: 'missing_or_invalid_total_price', hint: 'Must be numeric (TOTALPRICE).' };
      }
      continue;
    }
    if (isEmptyValue_(data[k])) {
      return { error: 'missing_' + k, hint: labels[k] + ' missing' };
    }
  }

  return null;
}

function doGet(e) {
  e = e || {};
  var param = e.parameter || {};
  var payload = {
    ok: true,
    version: WEBHOOK_VERSION,
    service: 'nabtalabo-sheet-webhook',
    sheet_headers_row_1_expected:
      'DATE,ORDERID,COUNTRYC,NAME,PHONE,PRODUCT,SKU,QUANTITY,TOTALPRICE,CURRENCY,STATUS',
    hint: '?check=1 = read spreadsheet; ?check=append = one junk test row (delete after).',
  };

  payload.config = {
    spreadsheet_id_set: String(SPREADSHEET_ID || '').trim().length > 0,
    sheet_tab_name: String(SHEET_TAB_NAME || '') || '(first tab)',
  };

  var check = String(param.check || '');
  if (check === '1' || check === 'spreadsheet') {
    try {
      var sheet = getTargetSheet_();
      var ss = sheet.getParent();
      payload.sheet_check = {
        ok: true,
        spreadsheet_title: ss.getName(),
        spreadsheet_id: ss.getId(),
        sheet_tab: sheet.getName(),
        rows_used: sheet.getLastRow(),
      };
    } catch (err) {
      payload.sheet_check = { ok: false, error: String(err.message || err) };
    }
  }

  if (check === 'append') {
    try {
      var sh = getTargetSheet_();
      sh.appendRow([
        'TEST',
        'nabta-test-' + Date.now(),
        'KSA',
        'Webhook',
        '966500000000',
        'اختبار',
        'NBT-TEST',
        '1',
        1,
        'SAR',
        '',
      ]);
      payload.manual_append_test = { ok: true };
    } catch (err2) {
      payload.manual_append_test = { ok: false, error: String(err2.message || err2) };
    }
  }

  var out = ContentService.createTextOutput(JSON.stringify(payload));
  out.setMimeType(ContentService.MimeType.JSON);
  return out;
}

function doPost(e) {
  if (!e || !e.postData) {
    return jsonResponse({
      ok: false,
      error: 'empty_body',
      hint: 'Expect application/json body from Nabtalabo API.',
    });
  }

  var raw = e.postData.contents;
  if (!raw || String(raw).trim() === '') {
    return jsonResponse({ ok: false, error: 'empty_body' });
  }

  var data;
  try {
    data = JSON.parse(raw);
  } catch (err) {
    return jsonResponse({
      ok: false,
      error: 'invalid_json',
      hint: String(err.message || err).slice(0, 200),
    });
  }

  normalizePayloadAliases_(data);

  try {
    var inv = validatePayload_(data);
    if (inv) {
      return jsonResponse({ ok: false, error: inv.error, hint: inv.hint, version: WEBHOOK_VERSION });
    }

    var sheet = getTargetSheet_();

    // STATUS column stays empty (values in JSON ignored for that column).
    sheet.appendRow([
      String(data.date),
      String(data.order_id),
      String(data.country),
      String(data.name),
      String(data.phone),
      String(data.product),
      String(data.sku),
      String(data.quantity),
      Number(data.total_price),
      String(data.currency),
      '',
    ]);

    return jsonResponse({ ok: true, version: WEBHOOK_VERSION, appended: true });
  } catch (err) {
    return jsonResponse({
      ok: false,
      error: 'append_failed',
      detail: String(err.message || err),
      version: WEBHOOK_VERSION,
    });
  }
}

function jsonResponse(obj) {
  var out = ContentService.createTextOutput(JSON.stringify(obj));
  out.setMimeType(ContentService.MimeType.JSON);
  return out;
}
