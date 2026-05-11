/**
 * NabtaLabo — append one order row from backend POST JSON.
 *
 * Deploy: Extensions → Apps Script (from INSIDE the spreadsheet) → paste → Deploy → Web app
 * Execute as: Me | Who has access: Anyone (with link) or Anyone
 * Put the deployment URL in backend env GOOGLE_SHEET_WEBHOOK_URL ending in /exec
 *
 * If your script is STANDALONE (created at script.google.com, not from the Sheet):
 * set SPREADSHEET_ID below to the ID from your Sheet URL (.../d/THIS_PART/edit).
 *
 * SHEET_TAB_NAME: name of the tab (e.g. Feuille 1), or '' to append to the first tab.
 */
var SPREADSHEET_ID = ''; // e.g. '1AbCdEfGhIjKlMnOpQrStUvWxYz' or leave '' if bound to sheet
var SHEET_TAB_NAME = ''; // e.g. 'Orders' — must match sheet tab exactly

/**
 * Sheet row 1 (headers), same order:
 * DATE | ORDERID | COUNTRY | NAME | PHONE | PRODUCT | SKU | quantité | TOTAL PRICE | CURRENCY | STATUS
 */

function getSpreadsheet_() {
  var sid = SPREADSHEET_ID ? String(SPREADSHEET_ID).trim() : '';
  if (sid.length > 0) {
    return SpreadsheetApp.openById(sid);
  }
  var ss = SpreadsheetApp.getActiveSpreadsheet();
  if (!ss) {
    throw new Error(
      'No spreadsheet: standalone project must set SPREADSHEET_ID from the Sheet URL (…/d/ID/edit), ' +
        'OR create the script with Extensions → Apps Script from inside that Sheet.'
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
      throw new Error('Sheet tab not found: "' + tab + '" — check SHEET_TAB_NAME matches exactly.');
    }
    return sh;
  }
  var sheets = ss.getSheets();
  if (!sheets || sheets.length === 0) {
    throw new Error('Spreadsheet has no sheets.');
  }
  return sheets[0];
}

function doGet() {
  var out = ContentService.createTextOutput(
    JSON.stringify({
      ok: true,
      service: 'nabtalabo-sheet-webhook',
      hint: 'Orders are sent via POST JSON from the Nabtalabo API (GOOGLE_SHEET_WEBHOOK_URL).',
    })
  );
  out.setMimeType(ContentService.MimeType.JSON);
  return out;
}

function doPost(e) {
  if (!e || !e.postData || !e.postData.contents) {
    return jsonResponse({ ok: false, error: 'empty_body' }, 400);
  }
  var data;
  try {
    data = JSON.parse(e.postData.contents);
  } catch (err) {
    return jsonResponse({ ok: false, error: 'invalid_json' }, 400);
  }

  try {
    var sheet = getTargetSheet_();
    var status = data.status != null ? String(data.status) : '';

    sheet.appendRow([
      data.date,
      data.order_id,
      data.country,
      data.name,
      data.phone,
      data.product,
      data.sku,
      data.quantity,
      data.total_price,
      data.currency,
      status,
    ]);

    return jsonResponse({ ok: true });
  } catch (err) {
    return jsonResponse({ ok: false, error: String(err) }, 500);
  }
}

function jsonResponse(obj, statusCode) {
  var out = ContentService.createTextOutput(JSON.stringify(obj));
  out.setMimeType(ContentService.MimeType.JSON);
  if (typeof statusCode === 'number') {
    return out;
  }
  return out;
}
