-- ===========================================
-- Agent Framework PostgreSQL 初始化脚本
-- ===========================================
-- 此脚本在 PostgreSQL 容器首次启动时自动执行

-- 创建扩展
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pg_trgm";  -- 用于模糊搜索

-- 创建枚举类型
DO $$ BEGIN
    CREATE TYPE agentstatus AS ENUM ('draft', 'active', 'inactive', 'archived');
EXCEPTION
    WHEN duplicate_object THEN null;
END $$;

DO $$ BEGIN
    CREATE TYPE taskstatus AS ENUM ('pending', 'running', 'completed', 'failed', 'cancelled', 'paused');
EXCEPTION
    WHEN duplicate_object THEN null;
END $$;

DO $$ BEGIN
    CREATE TYPE workflowstatus AS ENUM ('pending', 'running', 'completed', 'failed', 'cancelled', 'paused');
EXCEPTION
    WHEN duplicate_object THEN null;
END $$;

-- 打印初始化完成消息
DO $$ BEGIN
    RAISE NOTICE 'Agent Framework 数据库初始化完成';
END $$;
