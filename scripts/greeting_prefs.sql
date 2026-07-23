-- Preferencje powitań Momentum na kanale Deep Work (per użytkownik, trwałe).
--
-- Uruchom RĘCZNIE raz w panelu Supabase: SQL editor → wklej całość → Run.
--
-- Prosta tabela stanu (bez RPC — operacje robimy zwykłym upsertem z db.py):
--   mode              'full'  → powitania LLM (z fallbackiem statycznym),
--                     'plain' → tylko krótkie "Cześć @user 👋".
--   unanswered_streak liczba powitań pod rząd, na które użytkownik nie odpowiedział;
--                     po MOMENTUM_GREETING_MAX_UNANSWERED bot proponuje opt-out.
--                     Wraca do 0, gdy użytkownik odezwie się na kanale tego samego dnia.

create table if not exists deepwork_greeting_prefs (
    discord_id        text primary key,
    mode              text not null default 'full',
    unanswered_streak int  not null default 0,
    updated_at        timestamptz not null default now()
);
