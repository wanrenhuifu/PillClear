-- 0001_init.sql · PillClear 初始 schema
-- 药品说明书结构化存储 + 向量检索基础（D2）。

create extension if not exists vector;

-- ── drugs：药品主数据 ──────────────────────────────────────────────
create table if not exists drugs (
  id                   bigint generated always as identity primary key,
  brand_name           text not null unique,
  generic_name         text,
  otc_category         text,
  dosage_form          text,
  specification        text,
  approval_number      text,
  ingredients          jsonb   not null default '[]'::jsonb,
  ingredients_verified boolean not null default false,
  created_at           timestamptz not null default now()
);

comment on table  drugs is 'OTC 药品主数据';
comment on column drugs.brand_name           is '商品名（说明书文件名即商品名，作为幂等 upsert 键）';
comment on column drugs.generic_name          is '通用名';
comment on column drugs.otc_category          is 'OTC 分类（甲类/乙类）';
comment on column drugs.dosage_form           is '剂型';
comment on column drugs.specification         is '规格';
comment on column drugs.approval_number       is '批准文号（国药准字）';
comment on column drugs.ingredients           is '成分列表 JSONB：[{name,amount,unit}]，重复成分/日剂量检测基础';
comment on column drugs.ingredients_verified  is '成分是否人工核对；仅 true 时才被 D4 规则引擎信任，入库管线永不置 true';
comment on column drugs.created_at            is '创建时间';

-- ── insert_chunks：说明书按章节切分的文本块 + 向量 ─────────────────
create table if not exists insert_chunks (
  id        bigint generated always as identity primary key,
  drug_id   bigint not null references drugs(id) on delete cascade,
  section   text   not null,
  content   text   not null,
  embedding vector(1024)
);

comment on table  insert_chunks is '说明书章节文本块及其向量（RAG 检索与引用来源）';
comment on column insert_chunks.drug_id   is '所属药品 drugs.id';
comment on column insert_chunks.section   is '章节名（如：用法用量、成份、禁忌）';
comment on column insert_chunks.content   is '章节原文，回答引用必须为此内容的精确子串';
comment on column insert_chunks.embedding is 'BGE-M3 向量（1024 维，cosine）';

-- 向量近邻检索索引（D3 使用）
create index if not exists insert_chunks_embedding_hnsw
  on insert_chunks using hnsw (embedding vector_cosine_ops);

create index if not exists insert_chunks_drug_id_idx
  on insert_chunks (drug_id);
