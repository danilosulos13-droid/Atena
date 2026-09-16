create extension if not exists vector with schema extensions;

alter table public.atena_memory_chunks
  alter column embedding type extensions.vector(384)
  using null::extensions.vector(384);

create index if not exists atena_memory_chunks_embedding_hnsw
  on public.atena_memory_chunks
  using hnsw (embedding extensions.vector_cosine_ops)
  where embedding is not null;

create or replace function public.match_atena_memory_chunks(
  query_embedding extensions.vector(384),
  match_count integer default 5
)
returns table (
  id bigint,
  content_hash text,
  source_path text,
  content text,
  approved boolean,
  metadata jsonb,
  similarity double precision
)
language sql stable
as $$
  select c.id, c.content_hash, c.source_path, c.content, c.approved,
         c.metadata,
         (1 - (c.embedding <=> query_embedding))::double precision as similarity
  from public.atena_memory_chunks c
  where c.embedding is not null
  order by c.embedding <=> query_embedding
  limit least(greatest(match_count, 1), 50);
$$;
