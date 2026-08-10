-- 用药提醒表（Supabase / Postgres 路径）。
-- SQLite 端由 app/knowledge/sqlite_repo.init_schema 自动建表，不需要此文件。
-- 每个提醒时刻一行；(user_id, drug_id, time_of_day) 唯一，覆盖式设置先删后插。

create table if not exists user_reminders (
    id bigint generated always as identity primary key,
    user_id bigint not null references users(id) on delete cascade,
    drug_id bigint not null references drugs(id) on delete cascade,
    time_of_day text not null,
    created_at timestamptz not null default now(),
    unique(user_id, drug_id, time_of_day)
);
