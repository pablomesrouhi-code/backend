/**
 * NabtaLabo — إلحاق طلب واحد بالصفحة الأولى من جدولك (نفس أعمدة الشيت التجارية).
 * النسخة المرجعية لهذا السكربت موجودة تحت مستودع الـ backend: `backend/sheet/`
 *
 * خطوات النشر في Google Sheets:
 * 1) Extensions → Apps Script → الصق هذا الملف وحفظ.
 * 2) Deploy → New deployment → نوع Web app، Execute as: Me، Who has access: Anyone.
 * 3) انسخ عنوان URL الذي يظهر بعد النشر وأضعه في المتغير GOOGLE_SHEET_WEBHOOK_URL في بيئة الـ backend (.env).
 *
 * المتوقع أن يكون الصفحة الأولى (أو الورقة Sheet1) بها صف عنوان بهذا الترتيب:
 * DATE | ORDERID | COUNTRY | NAME | PHONE | PRODUCT | SKU | quantité | TOTAL PRICE | CURRENCY | STATUS
 *
 * JSON المرسل من الـ API يطابق هذه الحقول (snake_case):
 * date, order_id, country, name, phone, product, sku, quantity, total_price, currency, status (فارغ)
 */
function doPost(e) {
  try {
    const raw = (e.postData && e.postData.contents) || "{}";
    const body =
      typeof raw === "string" ? JSON.parse(raw) : raw;

    const row = [
      body.date || "",
      body.order_id || "",
      body.country || "",
      body.name || "",
      body.phone || "",
      body.product || "",
      body.sku || "",
      body.quantity || "",
      body.total_price != null && body.total_price !== ""
        ? body.total_price
        : "",
      body.currency || "",
      body.status !== undefined && body.status !== null ? body.status : "",
    ];

    const ss = SpreadsheetApp.getActiveSpreadsheet();
    const sheet =
      ss.getSheetByName("Sheet1") || ss.getActiveSheet();
    sheet.appendRow(row);

    return jsonResponse({ ok: true, received: row.length }, 200);
  } catch (error) {
    return jsonResponse({ ok: false, error: String(error) }, 500);
  }
}

/** فحص يدوي من المتصفح بعد النشر: افتح عنوان الـ URL فقط */
function doGet() {
  return ContentService.createTextOutput(
    "NabtaLabo sheet webhook: use POST JSON from backend."
  );
}

function jsonResponse(payload, statusCode) {
  return ContentService.createTextOutput(
    JSON.stringify(Object.assign({ status: statusCode }, payload))
  ).setMimeType(ContentService.MimeType.JSON);
}
