-- 一次性切换脚本：把存量生产库对齐到压缩后的迁移基线 0001_initial_schema。
-- 背景见 docs/adr/0016-squash-migration-baseline.md：代码库迁移链已压缩为单基线，
-- 旧版本号（0001_stage1 ~ 0031_agent_turn_batches）不再存在于迁移脚本中。
--
-- 执行时机：必须在部署携带新基线的代码之前执行（start.sh / migrate 服务会运行
-- `alembic upgrade head`，若库中仍是旧版本号将因无法识别而失败）。
-- 执行前必须完成备份（ops/Backup-QQTimeAgent.ps1）。
-- 本脚本执行一次后即可删除，不作为常规发布产物保留。
--
-- 使用步骤：
--   1. 停止写入并停止应用容器（web/worker/qq），保留 postgres。
--   2. 确认当前版本：
--        SELECT version_num FROM alembic_version;
--   3a. 若结果是 0030_todo_completion_gate：执行下方整个事务（含 DDL 与版本更新）。
--   3b. 若结果是 0031_agent_turn_batches：跳过 DDL，只执行末尾的 UPDATE alembic_version 语句。
--       （若结果不是上述两者，停止操作并核对部署历史，不要继续。）
--   4. 核对：再次执行第 2 步查询，应返回 0001_initial_schema。
--   5. 之后才允许部署新代码并运行 start.sh。

BEGIN;

-- ==== 第 3a 步 DDL（仅当库停在 0030_todo_completion_gate 时执行）====
-- 内容等价于压缩前 0031_agent_turn_batches 迁移的 upgrade()，由 Alembic 离线生成。

ALTER TABLE agent_runs ADD COLUMN source_refs JSONB DEFAULT '[]'::jsonb NOT NULL;

ALTER TABLE agent_runs ALTER COLUMN source_refs DROP DEFAULT;

CREATE TABLE agent_turn_batches (
    turn_id UUID NOT NULL,
    user_id VARCHAR(120) NOT NULL,
    conversation_key_hash VARCHAR(64) NOT NULL,
    status VARCHAR(16) NOT NULL,
    generation INTEGER NOT NULL,
    message_count INTEGER NOT NULL,
    content_chars INTEGER NOT NULL,
    ready_at TIMESTAMP WITH TIME ZONE NOT NULL,
    hard_deadline_at TIMESTAMP WITH TIME ZONE NOT NULL,
    lease_owner VARCHAR(160),
    lease_until TIMESTAMP WITH TIME ZONE,
    failure_class VARCHAR(120),
    created_at TIMESTAMP WITH TIME ZONE NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
    PRIMARY KEY (turn_id),
    CONSTRAINT ck_agent_turn_batches_status CHECK (status IN ('OPEN', 'LEASED', 'COMPLETED', 'FAILED')),
    CONSTRAINT ck_agent_turn_batches_counts CHECK (generation >= 1 AND message_count >= 1 AND content_chars >= 0)
);

CREATE INDEX ix_agent_turn_batches_conversation_status ON agent_turn_batches (conversation_key_hash, status, created_at);

CREATE TABLE agent_turn_segments (
    turn_id UUID NOT NULL,
    position INTEGER NOT NULL,
    inbox_item_id UUID NOT NULL,
    source_type VARCHAR(40) NOT NULL,
    trust_level VARCHAR(10) NOT NULL,
    occurred_at TIMESTAMP WITH TIME ZONE NOT NULL,
    provider_sequence BIGINT,
    reference_hash VARCHAR(64),
    content_chars INTEGER NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL,
    PRIMARY KEY (turn_id, position),
    CONSTRAINT ck_agent_turn_segments_size CHECK (position >= 1 AND content_chars >= 0),
    FOREIGN KEY(turn_id) REFERENCES agent_turn_batches (turn_id) ON DELETE CASCADE,
    CONSTRAINT uq_agent_turn_segments_inbox_item UNIQUE (inbox_item_id)
);

-- ==== 版本登记（第 3a 步与第 3b 步都需要执行这一句）====

UPDATE alembic_version SET version_num = '0001_initial_schema';

COMMIT;
