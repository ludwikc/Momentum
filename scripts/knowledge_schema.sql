-- Baza wiedzy Momentum — schemat + wyszukiwanie hybrydowe (pgvector + trigramy, RRF).
--
-- Uruchom RĘCZNIE raz w panelu Supabase: SQL editor → wklej całość → Run.
-- Idempotentny: można wkleić ponownie po zmianach (godzi też starsze instalacje,
-- które miały leksykalną nogę opartą na FTS — usuwa nieużywaną kolumnę `fts`).
-- Wymaga rozszerzeń `vector` (pgvector) i `pg_trgm` (oba dostępne na Supabase).
--
-- Wymiar wektora (1024) MUSI zgadzać się z config.MOMENTUM_KB_EMBED_DIMS oraz
-- z `dimensions` używanym przy embedowaniu (scripts/ingest_knowledge.py i
-- cogs/przywolanie.py). Zmieniasz jedno — zmień wszystkie trzy.

create extension if not exists vector;
create extension if not exists pg_trgm;

create table if not exists knowledge_base (
  id           bigint generated always as identity primary key,
  source_id    bigint,                           -- 'id' z pliku źródłowego (opcjonalne)
  temat        text not null,
  tresc        text not null,
  kategoria    text,
  content_hash text not null unique,            -- idempotentny re-import
  embedding    vector(1024),                     -- text-embedding-3-large, dims=1024
  created_at   timestamptz default now()
);

-- Godzenie starszej instalacji (noga leksykalna była na FTS): usuń nieużywane.
drop index if exists knowledge_fts_idx;
alter table knowledge_base drop column if exists fts;

create index if not exists knowledge_embedding_idx
  on knowledge_base using hnsw (embedding vector_cosine_ops);
-- Trigramowy indeks pod leksykalną nogę (word_similarity) — odporny na odmianę.
create index if not exists knowledge_trgm_idx
  on knowledge_base using gin ((temat || ' ' || tresc) gin_trgm_ops);


-- Wyszukiwanie hybrydowe: łączy ranking semantyczny (cosine na pgvector) z
-- rankingiem leksykalnym (trigramy, word_similarity — łapie konkretne frazy/nazwy
-- mimo polskiej odmiany) metodą Reciprocal Rank Fusion (k=60). Zwraca najlepsze
-- `match_count` dopasowań; opcjonalny filtr kategorii.
create or replace function match_knowledge(
  query_text       text,
  query_embedding  vector(1024),
  match_count      int default 3,
  filter_kategoria text default null
) returns table (id bigint, temat text, tresc text, kategoria text, score float)
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
             order by word_similarity(query_text, kb.temat || ' ' || kb.tresc) desc
           ) as r
    from knowledge_base kb
    where (filter_kategoria is null or kb.kategoria = filter_kategoria)
      and word_similarity(query_text, kb.temat || ' ' || kb.tresc) > 0.3
    limit 30
  )
  select kb.id, kb.temat, kb.tresc, kb.kategoria,
         coalesce(1.0/(60+sem.r),0) + coalesce(1.0/(60+lex.r),0) as score
  from knowledge_base kb
  left join sem on sem.id = kb.id
  left join lex on lex.id = kb.id
  where sem.id is not null or lex.id is not null
  order by score desc
  limit match_count;
$$;
