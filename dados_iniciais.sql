-- dados_iniciais.sql
-- Dados de que o sistema precisa para arrancar numa base nova, a correr depois do esquema.sql:
--   psql "<URL>" -v ON_ERROR_STOP=1 -f dados_iniciais.sql
-- Gerado da base em produção, não escrito à mão (sem quem alterou nem quando):
--   parametros       os limiares dos alertas, da relação de fornecimento e da renovação (RNF3),
--                    com a origem de cada um; alteram-se depois no dashboard, pelo gestor
--   taxa_ganho_fase  a proporção histórica de ganho por fase (Quadro 6.9)
-- Gerado a 24-Out-2026.

BEGIN;

INSERT INTO parametros (chave, valor, descricao, origem) VALUES ('anos_renovacao', 5.0, 'Anos desde a entrada da máquina mais recente de um cliente para o propor para renovação', 'Percentil 75 do intervalo entre episódios de compra de equipamento do mesmo cliente (4,9 anos, 533 intervalos), secção 5.3.1; decidido a 23-Out-2026') ON CONFLICT (chave) DO NOTHING;
INSERT INTO parametros (chave, valor, descricao, origem) VALUES ('dia_notificacao', 5, 'Dia da semana em que os alertas são notificados (1 = segunda, 5 = sexta; 0 = todos os dias)', 'Entrevista 1, 9-Out-2026') ON CONFLICT (chave) DO NOTHING;
INSERT INTO parametros (chave, valor, descricao, origem) VALUES ('dias_base_sem_contacto', 90, 'Cliente com equipamento sem visita: dias sem contacto com um cliente da base instalada sem negócio aberto', '§4.5') ON CONFLICT (chave) DO NOTHING;
INSERT INTO parametros (chave, valor, descricao, origem) VALUES ('dias_fecho', 180, 'Fecho automático do negócio sem contacto (RF2.8)', '§4.5') ON CONFLICT (chave) DO NOTHING;
INSERT INTO parametros (chave, valor, descricao, origem) VALUES ('dias_mesmo_estado', 30, 'Encomenda sem avanço: dias em «Encomenda confirmada» sem mudar de estado', '§4.5') ON CONFLICT (chave) DO NOTHING;
INSERT INTO parametros (chave, valor, descricao, origem) VALUES ('dias_negociacao', 14, 'À espera de resposta: dias sem contacto num negócio em proposta, negociação ou aprovação interna', '§4.5') ON CONFLICT (chave) DO NOTHING;
INSERT INTO parametros (chave, valor, descricao, origem) VALUES ('dias_sem_contacto', 90, 'Sem contacto: dias sem contacto num negócio aberto, em qualquer estado', '§4.5') ON CONFLICT (chave) DO NOTHING;
INSERT INTO parametros (chave, valor, descricao, origem) VALUES ('k_dormente', 3.47, 'Consumíveis: silêncio acima deste múltiplo do intervalo típico é "dormente"', 'Percentis 75 e 95 dos silêncios que terminaram numa compra, secção 5.2.3') ON CONFLICT (chave) DO NOTHING;
INSERT INTO parametros (chave, valor, descricao, origem) VALUES ('k_risco', 1.59, 'Consumíveis: silêncio acima deste múltiplo do intervalo típico é "em risco"', 'Percentis 75 e 95 dos silêncios que terminaram numa compra, secção 5.2.3') ON CONFLICT (chave) DO NOTHING;
INSERT INTO parametros (chave, valor, descricao, origem) VALUES ('teto_atraso', 15, 'Máximo de avisos por comercial e por semana enquanto houver avisos atrasados do arranque', 'Decisão do gestor, 15-Out-2026') ON CONFLICT (chave) DO NOTHING;
INSERT INTO parametros (chave, valor, descricao, origem) VALUES ('teto_semanal', 10, 'Máximo de alertas por comercial e por semana', '§5.1') ON CONFLICT (chave) DO NOTHING;

INSERT INTO taxa_ganho_fase (estado, negocios, ganho, ganho_faturacao, origem) VALUES ('1. Lead / Prospeção', 390, 0.023, 0.021, 'Quadro 6.9, §6.4') ON CONFLICT (estado) DO NOTHING;
INSERT INTO taxa_ganho_fase (estado, negocios, ganho, ganho_faturacao, origem) VALUES ('10. Indeterminado', 199, 0.126, 0.075, 'Quadro 6.9, §6.4') ON CONFLICT (estado) DO NOTHING;
INSERT INTO taxa_ganho_fase (estado, negocios, ganho, ganho_faturacao, origem) VALUES ('2. Qualificação', 385, 0.127, 0.101, 'Quadro 6.9, §6.4') ON CONFLICT (estado) DO NOTHING;
INSERT INTO taxa_ganho_fase (estado, negocios, ganho, ganho_faturacao, origem) VALUES ('3. Proposta / Orçamento', 270, 0.189, 0.152, 'Quadro 6.9, §6.4') ON CONFLICT (estado) DO NOTHING;
INSERT INTO taxa_ganho_fase (estado, negocios, ganho, ganho_faturacao, origem) VALUES ('4. Negociação', 84, 0.298, 0.262, 'Quadro 6.9, §6.4') ON CONFLICT (estado) DO NOTHING;
INSERT INTO taxa_ganho_fase (estado, negocios, ganho, ganho_faturacao, origem) VALUES ('5. Aprovação Interna', 102, 0.284, 0.255, 'Quadro 6.9, §6.4') ON CONFLICT (estado) DO NOTHING;

COMMIT;
