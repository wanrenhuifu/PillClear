-- 0002_embedding_not_null.sql · insert_chunks.embedding 强制 NOT NULL
-- 入库管线恒为"先向量化再写库"，chunk 必然带向量；而 NULL 向量不会进入
-- HNSW 索引、相似度检索会静默漏掉这些行。与其让无向量 chunk 悄悄落库
-- 导致 RAG 引用缺失，不如在写入时直接拒绝。

alter table insert_chunks
  alter column embedding set not null;
