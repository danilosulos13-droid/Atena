alter table public.atena_memory_chunks
  add column if not exists content_tsv tsvector generated always as (
    to_tsvector('simple', coalesce(content, ''))
  ) stored;

create index if not exists atena_memory_chunks_content_tsv_gin
  on public.atena_memory_chunks using gin (content_tsv);

create or replace function public.hybrid_search_atena_memory_chunks(
  query_embedding extensions.vector(384),
  query_text text,
  match_count integer default 10,
  vector_weight real default 0.7,
  text_weight real default 0.3
)
returns table (
  id bigint,
  content_hash text,
  source_path text,
  content text,
  approved boolean,
  metadata jsonb,
  vector_similarity double precision,
  text_rank real,
  hybrid_score double precision
)
language sql stable
as $$
  with vector_candidates as (
    select c.id, 1 - (c.embedding <=> query_embedding) as vector_similarity
    from public.atena_memory_chunks c
    where c.embedding is not null
    order by c.embedding <=> query_embedding
    limit 100
  ),
  text_candidates as (
    select c.id,
           ts_rank_cd(c.content_tsv, websearch_to_tsquery('simple', query_text)) as text_rank
    from public.atena_memory_chunks c
    where c.content_tsv @@ websearch_to_tsquery('simple', query_text)
    order by ts_rank_cd(c.content_tsv, websearch_to_tsquery('simple', query_text)) desc
    limit 100
  ),
  scores as (
    select coalesce(v.id, t.id) as id,
           coalesce(v.vector_similarity, 0)::double precision as vector_similarity,
           coalesce(t.text_rank, 0)::real as text_rank,
           (coalesce(v.vector_similarity, 0) * vector_weight
            + coalesce(t.text_rank, 0) * text_weight)::double precision as hybrid_score
    from vector_candidates v
    full outer join text_candidates t on t.id = v.id
  )
  select c.id, c.content_hash, c.source_path, c.content, c.approved, c.metadata,
         s.vector_similarity, s.text_rank, s.hybrid_score
  from scores s
  join public.atena_memory_chunks c on c.id = s.id
  order by s.hybrid_score desc
  limit least(greatest(match_count, 1), 50);
$$;
