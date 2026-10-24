-- O lead em prospecção é um negócio cujo tipo ainda não é determinável.
--
-- Sem um valor próprio, o topo do funil ou se perdia (par vazio, lead
-- invisível no pipeline) ou obrigava a admitir nulos no identificador e no
-- tipo, que a chave estrangeira e a restrição de tipo não permitem.
--
-- `lead` percorre o ciclo comercial como equipamento e produção, pelo que as
-- restrições que opõem consumíveis aos restantes continuam correctas e não são
-- tocadas. Quando o assunto ganha forma, o negócio é re-tipificado.

ALTER TABLE negocios   DROP CONSTRAINT IF EXISTS negocios_tipo_check;
ALTER TABLE pares_llm  DROP CONSTRAINT IF EXISTS pares_llm_tipo_check;

ALTER TABLE negocios ADD CONSTRAINT negocios_tipo_valido
  CHECK (tipo IN ('equipamento', 'producao', 'consumiveis', 'lead'));

ALTER TABLE pares_llm ADD CONSTRAINT pares_llm_tipo_valido
  CHECK (tipo IN ('equipamento', 'producao', 'consumiveis', 'lead'));
