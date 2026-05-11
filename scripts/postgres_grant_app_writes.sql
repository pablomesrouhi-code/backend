-- صلاحيات الكتابة إذا كان مستخدم DATABASE_URL لا يملك INSERT على جداول Nabtalabo.
-- نفِّذيها في PgWeb بعد اختيار قاعدة nabtalabo، وبحساب مشرف (غالباً postgres).
-- بدّلي nabtalabo_app باسم المستخدم من DATABASE_URL (قبل @ في الرابط).

GRANT CONNECT ON DATABASE nabtalabo TO nabtalabo_app;
GRANT USAGE ON SCHEMA public TO nabtalabo_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO nabtalabo_app;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO nabtalabo_app;

ALTER DEFAULT PRIVILEGES IN SCHEMA public
  GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO nabtalabo_app;
ALTER DEFAULT PRIVILEGES IN SCHEMA public
  GRANT USAGE, SELECT ON SEQUENCES TO nabtalabo_app;