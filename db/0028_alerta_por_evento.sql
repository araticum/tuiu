-- Modo de notificação: resumo (padrão) × alerta por evento.
--
-- Correção de produto do Danilo (27/07/2026), operador da carteira: alerta por
-- evento não vale o incômodo, porque **o Transferegov já manda e-mail de cada
-- mudança**. Repetir no WhatsApp é a mesma inundação em outro canal. O valor
-- está na triagem — "teve 200 mudanças, 5 precisam de você".
--
-- Este interruptor existe para os dois modos não conviverem: ligados juntos,
-- o operador receberia o resumo E cada evento dele, que é exatamente a
-- enxurrada que o resumo veio evitar.
--
-- Nasce FALSE: o padrão é resumo. O caminho por evento fica no código porque
-- ainda serve para um recorte crítico no futuro (um cliente, um tipo de marco),
-- mas ligar é ato deliberado e registrado, como todo envio externo aqui.

INSERT INTO configuracoes (chave, valor, atualizado_por) VALUES
    ('alerta_por_evento', 'false', 'migration 0028 — padrao e o resumo diario')
ON CONFLICT (chave) DO NOTHING;
