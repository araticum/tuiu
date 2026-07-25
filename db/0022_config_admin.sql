-- Config editável por ADMIN — o especialista (Danilo) incrementa a plataforma
-- sem código. Duas famílias de configurável nesta primeira leva:
--   regras_situacao : classifica a SIT_CONVENIO em fase (convenente/concedente/
--                     ignorar). Decide se um prazo de prestação vira alarme e de
--                     quem é a bola. Era hardcode no motor — origem de 62% dos
--                     alarmes vermelhos falsos até o especialista calibrar
--                     (07/2026). Agora é dado, e quem calibra é quem entende.
--   regras_acao     : o "próximo passo" (texto que o operador lê na fila) por
--                     tipo de marco.
-- Admin = flag em usuarios; operador comum opera, admin configura. Pedro e
-- Danilo nascem admin.

ALTER TABLE usuarios ADD COLUMN IF NOT EXISTS admin boolean NOT NULL DEFAULT false;
UPDATE usuarios SET admin = true WHERE login IN ('pedro@araticum.net', 'danilo@araticum.net');


CREATE TABLE IF NOT EXISTS regras_situacao (
    id            serial PRIMARY KEY,
    padrao        text NOT NULL,   -- substring normalizada (minúscula, sem acento) a casar na situação
    fase          text NOT NULL CHECK (fase IN ('convenente', 'concedente', 'ignorar')),
    nota          text,            -- por que a regra existe (rastro do especialista)
    ativo         boolean NOT NULL DEFAULT true,
    criado_por    text,
    criado_em     timestamptz NOT NULL DEFAULT now(),
    atualizado_em timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX IF NOT EXISTS regras_situacao_padrao ON regras_situacao (padrao);

COMMENT ON TABLE regras_situacao IS
  'Classificação da situação do instrumento em fase de prestação (convenente owe / '
  'concedente owe / ignorar). Editável por admin. Precedência: ignorar > convenente '
  '> concedente; sem casar = sem marco de prestação. Seed = listas antes hardcoded.';

-- Seed: as listas que estavam no motor_prazos, calibradas com o Danilo (07/2026).
INSERT INTO regras_situacao (padrao, fase, nota, criado_por) VALUES
  ('em execucao',                                 'convenente', 'Executando: prazo de PC se aproximando é aviso legítimo.',  'seed'),
  ('aguardando prestacao de contas',              'convenente', 'PC pendente de envio pelo convenente.',                     'seed'),
  ('prestacao de contas em complementacao',       'convenente', 'PC devolvida para complementar: a bola volta ao cliente.',  'seed'),
  ('prestacao de contas iniciada por antecipacao','convenente', 'Cliente começou a PC por antecipação.',                     'seed'),
  ('prestacao de contas enviada',                 'concedente', 'PC entregue, aguardando análise do órgão.',                 'seed'),
  ('prestacao de contas em analise',              'concedente', 'PC em análise pelo concedente.',                            'seed'),
  ('prestacao de contas comprovada',              'concedente', 'PC comprovada, em análise final do órgão.',                 'seed'),
  ('prestacao de contas aprovada',                'concedente', 'PC aprovada — encerrada, sem ação do cliente.',             'seed'),
  ('prestacao de contas arquivada',               'concedente', 'PC arquivada pelo órgão.',                                  'seed')
ON CONFLICT (padrao) DO NOTHING;


CREATE TABLE IF NOT EXISTS regras_acao (
    tipo          text PRIMARY KEY,
    proximo_passo text NOT NULL,
    nota          text,
    criado_por    text,
    atualizado_em timestamptz NOT NULL DEFAULT now()
);

COMMENT ON TABLE regras_acao IS
  'Próximo passo (o que o operador deve fazer) por tipo de marco. Editável por admin. '
  'Seed = o dicionário PROXIMO_PASSO antes hardcoded na fila.';

INSERT INTO regras_acao (tipo, proximo_passo, criado_por) VALUES
  ('prestacao_contas',          'Montar e enviar a prestação de contas no Transferegov',                 'seed'),
  ('fim_vigencia',              'Decidir: concluir o objeto, pedir aditivo de prazo ou encerrar',        'seed'),
  ('impedimento_pix',           'Regularizar o plano de ação impedido junto ao órgão',                   'seed'),
  ('relatorio_gestao_pix',      'Preencher e enviar o Relatório de Gestão',                              'seed'),
  ('fim_execucao_pix',          'Concluir a execução pactuada e reunir comprovação',                     'seed'),
  ('defeso_eleitoral',          'Não celebrar nova transferência voluntária na janela',                  'seed'),
  ('impedimento_cadastro',      'Sanar a pendência que gerou o impedimento e pedir baixa',               'seed'),
  ('andamento',                 'Ler a mudança e decidir a ação (o órgão mexeu no instrumento)',         'seed'),
  ('proposta_parada',           'Cobrar o concedente (art. 97) sobre a análise parada',                  'seed'),
  ('complementacao_pendente',   'Responder a complementação exigida pelo órgão',                         'seed'),
  ('etapa_cronograma',          'Executar/comprovar a etapa do cronograma físico',                       'seed'),
  ('parcela_prevista',          'Conferir se a parcela foi liberada; cobrar se não saiu',                'seed'),
  ('analise_parada_concedente', 'Cobrar decisão do concedente (art. 97) sobre as prestações paradas',    'seed'),
  ('proposta_rejeitada',        'Ler o parecer do órgão e decidir: corrigir e reapresentar, ou encerrar','seed')
ON CONFLICT (tipo) DO NOTHING;
