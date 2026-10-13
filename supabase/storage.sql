-- Run once in the Supabase SQL editor (or psql against the project database).
-- Creates the PRIVATE bucket used for uploaded documents and generated exports.
-- No storage.objects policies are added: browsers never access the bucket directly.
-- The API uses the service-role key and hands out short-lived signed URLs.
insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
values ('documents', 'documents', false, 209715200,
        array['application/pdf', 'text/csv', 'application/json'])
on conflict (id) do update
  set public = false,
      file_size_limit = excluded.file_size_limit,
      allowed_mime_types = excluded.allowed_mime_types;
