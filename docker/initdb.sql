-- Runs once, on first container start. Tests get their own database so they can
-- wipe and rebuild it freely without touching the seeded dev data.
CREATE DATABASE agencydesk_test OWNER agencydesk;
