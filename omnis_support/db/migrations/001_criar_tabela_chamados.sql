-- Chamados recebidos pela caixa de suporte, com a decisão tomada pelo agente.

CREATE TABLE tickets (
    id                  BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    graph_message_id    TEXT        NOT NULL UNIQUE,
    internet_message_id TEXT,
    conversation_id     TEXT,
    sender_email        TEXT        NOT NULL,
    sender_name         TEXT,
    subject             TEXT        NOT NULL DEFAULT '',
    body                TEXT        NOT NULL DEFAULT '',
    received_at         TIMESTAMPTZ NOT NULL,

    status              TEXT        NOT NULL DEFAULT 'recebido'
        CHECK (status IN ('recebido', 'respondido_automaticamente', 'encaminhado', 'ignorado', 'erro')),
    category            TEXT,
    complexity          TEXT CHECK (complexity IN ('simples', 'complexo')),
    confidence          NUMERIC(4, 3) CHECK (confidence BETWEEN 0 AND 1),
    summary             TEXT,
    is_interesting      BOOLEAN     NOT NULL DEFAULT FALSE,
    interesting_reason  TEXT,
    decision_reason     TEXT,
    auto_reply          TEXT,

    attempts            INTEGER     NOT NULL DEFAULT 1,
    last_error          TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

COMMENT ON TABLE tickets IS 'Emails recebidos em suporte@ e o atendimento dado pelo agente';
COMMENT ON COLUMN tickets.is_interesting IS 'Dúvida relevante para a equipe: bug, lentidão, melhoria etc.';
COMMENT ON COLUMN tickets.decision_reason IS 'Por que o agente respondeu, encaminhou ou ignorou';

CREATE INDEX ix_tickets_conversation ON tickets (conversation_id);
CREATE INDEX ix_tickets_received_at ON tickets (received_at DESC);
CREATE INDEX ix_tickets_category ON tickets (category);
CREATE INDEX ix_tickets_interesting ON tickets (received_at DESC) WHERE is_interesting;

CREATE FUNCTION set_updated_at() RETURNS trigger AS $$
BEGIN
    NEW.updated_at := now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_tickets_updated_at
    BEFORE UPDATE ON tickets
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- Consultas prontas para a equipe

CREATE VIEW vw_duvidas_interessantes AS
SELECT
    'OMN-' || lpad(id::text, 6, '0') AS chamado,
    received_at                       AS recebido_em,
    sender_email                      AS cliente,
    subject                           AS assunto,
    category                          AS categoria,
    summary                           AS resumo,
    interesting_reason                AS motivo,
    status
FROM tickets
WHERE is_interesting
ORDER BY received_at DESC;

CREATE VIEW vw_resumo_por_categoria AS
SELECT
    date_trunc('week', received_at)::date                          AS semana,
    category                                                       AS categoria,
    count(*)                                                       AS total,
    count(*) FILTER (WHERE status = 'respondido_automaticamente')  AS respondidos_pelo_agente,
    count(*) FILTER (WHERE status = 'encaminhado')                 AS encaminhados,
    count(*) FILTER (WHERE is_interesting)                         AS interessantes
FROM tickets
WHERE status <> 'ignorado'
GROUP BY 1, 2
ORDER BY 1 DESC, 3 DESC;
