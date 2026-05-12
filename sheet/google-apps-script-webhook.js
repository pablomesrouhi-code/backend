/**
 * NabtaLabo — append one order row from backend POST JSON.
 *
 * مهم جداً — Lead (Meta Pixel / شكرًا) ماكيدوزش لهنا. السطور كاتزاد غير من Nabtalabo API
 * بحال POST /api/orders بعد ما الطلب يتسجل فـ Postgres. إذا بغيتي تسجّل فـ Sheet، خاص
 * checkout يكمّل و API تبعث JSON لهاد السكريپت.
 *
 * Deploy: Extensions → Apps Script (من داخل الشيت) → لصق → Deploy → Web app
 * Execute as: Me | Who has access: Anyone (with link) أو Anyone
 * حط رابط الـ deployment فـ GOOGLE_SHEET_WEBHOOK_URL (كيخلص بـ /exec)
 *
 * سكريپت standalone من script.google.com: عيّن SPREADSHEET_ID من الرابط (.../d/ID/edit).
 * SHEET_TAB_NAME: اسم الورقة بالحرف؛ خليه '' باش يستعمل اللولانية.
 */

var WEBHOOK_VERSION = 2;

var SPREADSHEET_ID = ''; // حط ID الشيت؛ خليه فارغ إلا السكريپت مربوط من داخل Spreadsheet

var SHEET_TAB_NAME = ''; // مثال 'Orders' — مطابق اسم التبويب أو ''

/**
 * Headers row 1 (ORDER template).
 * DATE | ORDERID | COUNTRYC | NAME | PHONE | PRODUCT | SKU | QUANTITY | TOTALPRICE | CURRENCY | STATUS
 */

function getSpreadsheet_() {
  var sid = SPREADSHEET_ID ? String(SPREADSHEET_ID).trim() : '';
  if (sid.length > 0) {
    return SpreadsheetApp.openById(sid);
  }
  var ss = SpreadsheetApp.getActiveSpreadsheet();
  if (!ss) {
    throw new Error(
      'No spreadsheet: مشروع standalone خاصّو SPREADSHEET_ID من URL الشيت (/d/ID/edit)، أو أنشئ السكريپت من Extensions → Apps Script من داخل نفس الشيت.'
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
      throw new Error('Sheet tab not found: "' + tab + '" — دوّز SHEET_TAB_NAME بحال اسم التبويب بالضبط.');
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

/**
 * @returns {Object|null} null = OK, otherwise { error: string, hint: string }
 */
function validatePayload_(data) {
  if (typeof data !== 'object' || data === null || Array.isArray(data)) {
    return {
      error: 'payload_not_object',
      hint: 'السكريپت كيتوقع JSON object من API. Lead و pixel ما كيبعثوش لهنا — غير طلبات من /api/orders.',
    };
  }

  var keys = [
    'date',
    'order_id',
    'country',
    'name',
    'phone',
    'product',
    'sku',
    'quantity',
    'total_price',
    'currency',
  ];

  var labels = {
    date: 'date (DD/MM/YYYY)',
    order_id: 'order_id',
    country: 'country',
    name: 'name',
    phone: 'phone (966…)',
    product: 'product',
    sku: 'sku',
    quantity: 'quantity',
    total_price: 'total_price (رقم)',
    currency: 'currency',
  };

  for (var i = 0; i < keys.length; i++) {
    var k = keys[i];
    if (k === 'total_price') {
      if (data[k] === undefined || data[k] === null || isNaN(Number(data[k]))) {
        return {
          error: 'missing_or_invalid_total_price',
          hint: 'خاص total_price يكون رقم (الـ API كيبعثو integer بالسار).',
        };
      }
      continue;
    }
    if (isEmptyValue_(data[k])) {
      return {
        error: 'missing_' + k,
        hint: 'الحقل ' + (labels[k] || k) + ' فارغ — راجع payload من الباك اند.',
      };
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
    lead_vs_order:
      'Meta Lead / Thank-you page لا يُرسلان إلى Sheet. الصفوف تُضاف فقط بعد POST /api/orders مع حفظ في Postgres.',
    hint: 'نفس رابط /exec: ?check=1 اختبار قراءة الشيت؛ ?check=append صف تجريبي واحد (احذفه بعد التحقق).',
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
        spreadsheet_id_from_url: ss.getId(),
        sheet_tab: sheet.getName(),
        rows_used: sheet.getLastRow(),
        cols_used: sheet.getLastColumn(),
      };
    } catch (err) {
      payload.sheet_check = {
        ok: false,
        error: String(err.message || err),
      };
    }
  }

  /** Optional: append test row (?check=append) — for manual QA only */
  if (check === 'append') {
    try {
      var sh = getTargetSheet_();
      sh.appendRow(['TEST', 'nama-test-' + Date.now(), 'KSA', 'Webhook test', '966500000000', 'تجربة', 'TEST', '1', 1, 'SAR', '']);
      payload.manual_append_test = {
        ok: true,
        message: 'Test row appended — احذفها من الشيت بعد التحقق.',
      };
    } catch (err2) {
      payload.manual_append_test = {
        ok: false,
        error: String(err2.message || err2),
      };
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
      hint: 'POST بدون postData — تأكد أن الباك اند كيبعث Content-Type: application/json و body JSON.',
    });
  }

  var raw = e.postData.contents;
  if (!raw || String(raw).trim() === '') {
    return jsonResponse({
      ok: false,
      error: 'empty_body',
      hint: 'Body فارغ. الـ API خاصّو json=payload لـ /exec.',
    });
  }

  var ctype = (e.postData.type || '').toLowerCase();
  if (ctype.indexOf('json') === -1 && ctype.length > 0) {
    // Apps Script may still parse; warn for ops
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

  try {
    var inv = validatePayload_(data);
    if (inv) {
      return jsonResponse({
        ok: false,
        error: inv.error,
        hint: inv.hint,
        version: WEBHOOK_VERSION,
      });
    }

    var sheet = getTargetSheet_();
    var status = data.status != null ? String(data.status) : '';

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
      status,
    ]);

    return jsonResponse({
      ok: true,
      version: WEBHOOK_VERSION,
      appended: true,
    });
  } catch (err) {
    return jsonResponse({
      ok: false,
      error: 'append_failed',
      detail: String(err.message || err),
      hint: 'صلاحيات الشيت؟ SPREADSHEET_ID / SHEET_TAB_NAME؟ الحساب اللي عمل Deploy لازم يقدر يكتب فـ الشيت.',
      version: WEBHOOK_VERSION,
    });
  }
}

function jsonResponse(obj) {
  var out = ContentService.createTextOutput(JSON.stringify(obj));
  out.setMimeType(ContentService.MimeType.JSON);
  return out;
}
