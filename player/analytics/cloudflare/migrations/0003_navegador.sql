-- Navegador de cada sessão (Instagram, Facebook, TikTok, Chrome WebView, Samsung, Edge, Firefox, Chrome, Safari ou Outro),
-- classificado pelo User-Agent na inserção. Linhas antigas ficam em branco e aparecem como Desconhecido no painel.
-- O Worker também roda este comando sozinho no primeiro acesso (garantirEsquema) e ignora a coluna que já existe.
ALTER TABLE sessoes ADD COLUMN navegador TEXT NOT NULL DEFAULT '';
