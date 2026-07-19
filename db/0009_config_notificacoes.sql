-- Chave/valor de configuração operacional, e o interruptor de notificações.
--
-- Por que isso existe: a carteira tem ORGANIZAÇÕES REAIS que nunca pediram para
-- receber nada nosso. O envio externo não pode depender de ninguém lembrar de
-- não configurar um destinatário — tem que ser uma trava explícita, no banco,
-- desligada por padrão, e visível na tela.

CREATE TABLE IF NOT EXISTS configuracoes (
    chave          text PRIMARY KEY,
    valor          text NOT NULL,
    atualizado_em  timestamptz NOT NULL DEFAULT now(),
    atualizado_por text
);

-- Tudo nasce FALSE. Ligar é ato deliberado, registrado com autor e horário.
INSERT INTO configuracoes (chave, valor, atualizado_por) VALUES
    ('notificacoes_ativas', 'false', 'migration 0009'),
    ('canal_seriema',       'false', 'migration 0009'),
    ('canal_whatsapp',      'false', 'migration 0009'),
    ('canal_webhook',       'false', 'migration 0009')
ON CONFLICT (chave) DO NOTHING;

-- Histórico de quem mexeu no interruptor: ligar/desligar envio externo é ato
-- auditável, não preferência de tela.
CREATE TABLE IF NOT EXISTS configuracoes_log (
    id         serial PRIMARY KEY,
    chave      text NOT NULL,
    de         text,
    para       text NOT NULL,
    quem       text,
    quando     timestamptz NOT NULL DEFAULT now()
);
