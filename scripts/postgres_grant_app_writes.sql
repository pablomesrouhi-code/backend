-- ============================================================================
-- انسخي كل ما تحت (من BEGIN) ونفّذيه في PgWeb دفعة واحدة.
-- شروط:
--   1) فالقائمة فوق: اختاري قاعدة nabtalabo (مش postgres فقط إلا بغيتي التأكد).
--   2) لازم تكوني متصلة بحساب عندو صلاحية مشرف (غالباً user اسمو postgres).
--   3) بدّلي YOUR_APP_USER باسم المستخدم اللي كاين في DATABASE_URL قبل :
--      مثال URL: postgres://nabtalabo:SECRET@host:5432/nabtalabo  → الاسم nabtalabo
--   4) إلا اسم قاعدة البيانات مش nabtalabo، بدّلي nabtalabo في سطر CONNECT تحت.
-- ============================================================================

BEGIN;

-- صلاحية الولوج للقاعدة
GRANT CONNECT ON DATABASE nabtalabo TO YOUR_APP_USER;

-- مخطّط الجداول
GRANT USAGE, CREATE ON SCHEMA public TO YOUR_APP_USER;

-- كل الجداول الموجودة دابا في public (orders, order_items, …)
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO YOUR_APP_USER;

-- Sequences لو كاينين (تلقائي من مهاجرات أحياناً)
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO YOUR_APP_USER;

-- أي جداول جديدة منين يصاوبها مهاجر بحساب postgres (كلاسيكي على EasyPanel)
ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public
  GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO YOUR_APP_USER;
ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public
  GRANT USAGE, SELECT ON SEQUENCES TO YOUR_APP_USER;

-- إذا الجداول تصلحات بمزيّوج من غير postgres، زيدي لهاد النسخة أيضاً بنفس الاسم بدل CURRENT_USER بحسابك:
ALTER DEFAULT PRIVILEGES IN SCHEMA public
  GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO YOUR_APP_USER;
ALTER DEFAULT PRIVILEGES IN SCHEMA public
  GRANT USAGE, SELECT ON SEQUENCES TO YOUR_APP_USER;

COMMIT;

-- ============================================================================
-- تحقّق (نفّذي متى بغيتي؛ بدّلي YOUR_APP_USER بحال فوق):
-- ============================================================================
-- SELECT current_database(), CURRENT_USER;

-- SELECT has_table_privilege('YOUR_APP_USER', CAST('public.orders' AS regclass), 'SELECT') AS can_select_orders,
--        has_table_privilege('YOUR_APP_USER', CAST('public.orders' AS regclass), 'INSERT') AS can_insert_orders;
