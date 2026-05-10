/**
 * NabtaLabo — append one order row from backend POST JSON.
 *
 * Deploy: Extensions → Apps Script → paste → Deploy → New deployment → Web app
 * Execute as: Me | Who has access: Anyone (or Anyone with link)
 * Put the deployment URL in backend env GOOGLE_SHEET_WEBHOOK_URL (no secret).
 *
 * Sheet row 1 (headers), same order as your CSV:
 * DATE | ORDERID | COUNTRY | NAME | PHONE | PRODUCT | SKU | quantité | TOTAL PRICE | CURRENCY | STATUS
 */
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
    var ss = SpreadsheetApp.getActiveSpreadsheet();
    var sheet = ss.getSheets()[0];

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
    // Apps Script ignores HTTP status on TextOutput for simple web apps,
    // but keep shape for readability if you migrate to OAuth / API Gateway.
    return out;
  }
  return out;
}
