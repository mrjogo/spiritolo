-- Registration links. An admin mints a single-use, time-limited invite for an
-- operator; whoever opens /login?invite=<token> registers a passkey for that
-- operator with no session. Two uses: inviting a second operator (create the
-- operators row, then a link), and re-registering after the public hostname
-- changes (passkeys are bound to the domain they were created on, so the
-- existing ones stop working the moment PUBLIC_ORIGIN moves).
create table operator_invites (
    id          integer primary key,
    token_hash  text not null unique,              -- sha256 hex of the token; the token itself is never stored
    operator_id integer not null references operators(id) on delete cascade,
    created_by  integer references operators(id) on delete set null,
    created_at  text not null default (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    expires_at  text not null,
    used_at     text
);
create index operator_invites_operator_idx on operator_invites (operator_id);
