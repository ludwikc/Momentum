-- Baza wiedzy Momentum — schemat + wyszukiwanie hybrydowe (pgvector + FTS, RRF).
--
-- Uruchom RĘCZNIE raz w panelu Supabase: SQL editor → wklej całość → Run.
-- Wymaga rozszerzeń `vector` (pgvector) i `unaccent` (oba dostępne na Supabase).
--
-- Wymiar wektora (1024) MUSI zgadzać się z config.MOMENTUM_KB_EMBED_DIMS oraz
-- z `dimensions` używanym przy embedowaniu (scripts/ingest_knowledge.py i
-- cogs/przywolanie.py). Zmieniasz jedno — zmień wszystkie trzy.

create extension if not exists vector;
create extension if not exists unaccent;

create table if not exists knowledge_base (
  id           bigint generated always as identity primary key,
  temat        text not null,
  odpowiedz    text not null,
  kategoria    text,
  content_hash text not null unique,            -- idempotentny re-import
  embedding    vector(1024),                     -- text-embedding-3-large, dims=1024
  fts          tsvector generated always as (
                 to_tsvector('simple', unaccent(coalesce(temat,'') || ' ' || coalesce(odpowiedz,'')))
               ) stored,
  created_at   timestamptz default now()
);

create index if not exists knowledge_embedding_idx
  on knowledge_base using hnsw (embedding vector_cosine_ops);
create index if not exists knowledge_fts_idx
  on knowledge_base using gin (fts);


-- Wyszukiwanie hybrydowe: łączy ranking semantyczny (cosine na pgvector) z
-- rankingiem leksykalnym (Postgres full-text) metodą Reciprocal Rank Fusion
-- (k=60). Zwraca najlepsze `match_count` dopasowań; opcjonalny filtr kategorii.
create or replace function match_knowledge(
  query_text       text,
  query_embedding  vector(1024),
  match_count      int default 3,
  filter_kategoria text default null
) returns table (id bigint, temat text, odpowiedz text, kategoria text, score float)
language sql stable as $$
  with sem as (
    select kb.id, row_number() over (order by kb.embedding <=> query_embedding) as r
    from knowledge_base kb
    where filter_kategoria is null or kb.kategoria = filter_kategoria
    order by kb.embedding <=> query_embedding
    limit 30
  ),
  lex as (
    select kb.id,
           row_number() over (
             order by ts_rank(kb.fts, websearch_to_tsquery('simple', unaccent(query_text))) desc
           ) as r
    from knowledge_base kb
    where (filter_kategoria is null or kb.kategoria = filter_kategoria)
      and kb.fts @@ websearch_to_tsquery('simple', unaccent(query_text))
    limit 30
  )
  select kb.id, kb.temat, kb.odpowiedz, kb.kategoria,
         coalesce(1.0/(60+sem.r),0) + coalesce(1.0/(60+lex.r),0) as score
  from knowledge_base kb
  left join sem on sem.id = kb.id
  left join lex on lex.id = kb.id
  where sem.id is not null or lex.id is not null
  order by score desc
  limit match_count;
$$;
