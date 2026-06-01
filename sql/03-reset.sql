-- =============================================================================
-- MissionControl - Mail Server Manager
-- Copyright (c) 2026 Your Net Tech
-- Developed by Jose Rinaldi
-- All rights reserved.
-- Unauthorized use, reproduction, or distribution is strictly prohibited
-- without written permission from Your Net Tech.
-- =============================================================================

-- ============================================================================
-- MissionControl Database Reset
-- Drops all tables and recreates them from the schema file.
-- ============================================================================

USE missioncontrol;

-- Disable FK checks for clean drop order
SET FOREIGN_KEY_CHECKS = 0;

DROP TABLE IF EXISTS audit_logs;
DROP TABLE IF EXISTS snoozed_messages;
DROP TABLE IF EXISTS undo_send;
DROP TABLE IF EXISTS email_templates;
DROP TABLE IF EXISTS tasks;
DROP TABLE IF EXISTS calendar_events;
DROP TABLE IF EXISTS calendars;
DROP TABLE IF EXISTS contacts;
DROP TABLE IF EXISTS contact_groups;
DROP TABLE IF EXISTS email_aliases;
DROP TABLE IF EXISTS mailboxes;
DROP TABLE IF EXISTS domains;
DROP TABLE IF EXISTS quota_templates;
DROP TABLE IF EXISTS user_roles;
DROP TABLE IF EXISTS users;
DROP TABLE IF EXISTS roles;

SET FOREIGN_KEY_CHECKS = 1;

SOURCE 01-schema.sql;
