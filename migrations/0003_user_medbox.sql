-- 0003_user_medbox.sql · 用户 + 药箱持久化
-- MVP 阶段用 device_id 标识用户，不引入登录/注册（见 app/medbox/schemas.py）。

-- ── users：设备标识（无登录）────────────────────────────────────────
create table if not exists users (
  id         bigint generated always as identity primary key,
  device_id  text not null unique,
  created_at timestamptz not null default now()
);

comment on table  users is '用户表（MVP 用 device_id 标识，无认证）';
comment on column users.device_id is '客户端生成的设备标识（UUID），幂等创建用户';

-- ── user_medbox：个人药箱 ────────────────────────────────────────────
create table if not exists user_medbox (
  id              bigint generated always as identity primary key,
  user_id         bigint not null references users(id) on delete cascade,
  drug_id         bigint not null references drugs(id) on delete cascade,
  dosage_per_day  int,
  added_at        timestamptz not null default now(),
  unique(user_id, drug_id)
);

comment on table  user_medbox is '用户个人药箱';
comment on column user_medbox.dosage_per_day is '每日服用次数，NULL 按 1 次/日计（保守低估）';
comment on column user_medbox.added_at is '加入药箱的时间';
