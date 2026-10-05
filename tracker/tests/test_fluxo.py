"""Fluxo completo: conta → pixel → webhook → painel."""

import json
from datetime import date

from sqlalchemy import select

from rastro.modelos import Conta, ContaAnuncio, EntidadeAnuncio, GastoDiario, Venda, Visita
from tests import amostras

ID_VISITA = "tk0123456789abcdefgh"
UTMS = {"utm_source": "FB", "utm_campaign": "Campanha Black|120210000000000001",
        "utm_medium": "Conjunto Aberto|120210000000000002", "utm_content": "Vídeo 3|120210000000000003",
        "utm_term": "Instagram_Reels", "fbclid": "IwAR123"}


def _conta(app) -> Conta:
    with app.state.banco.sessao() as sessao:
        return sessao.scalar(select(Conta))


def _integracao(cliente, plataforma="hotmart", **extra) -> dict:
    resposta = cliente.post("/api/integracoes", json={"plataforma": plataforma, **extra})
    assert resposta.status_code == 200, resposta.text
    return resposta.json()


def _visita(cliente, conta, id_visita=ID_VISITA, utms=UTMS, tipo="pagina"):
    corpo = json.dumps({"k": conta.chave_publica, "t": tipo, "c": id_visita, "v": "v0123456789abcdef", "u": utms,
                        "fbp": "fb.1.1700000000000.123", "fbc": None, "url": "https://lp.exemplo.com/?utm_source=FB",
                        "ref": ""})
    resposta = cliente.post("/c", content=corpo, headers={"Content-Type": "text/plain", "User-Agent": "Mozilla/5.0",
                                                          "X-Forwarded-For": "177.10.20.30, 10.0.0.1"})
    assert resposta.status_code == 204


def _webhook(cliente, integracao, dados, headers=None):
    caminho = integracao["url"].removeprefix("https://rastro.exemplo.com")
    return cliente.post(caminho, content=json.dumps(dados),
                        headers={"Content-Type": "application/json", **(headers or {})})


def test_precisa_login_e_cabecalho_csrf(cliente):
    assert cliente.get("/api/painel").status_code == 401
    assert cliente.post("/api/entrar", json={"email": "a", "senha": "b"},
                        headers={"X-Rastro": ""}).status_code == 403


def test_configuracao_inicial_login_e_cadastro_fechado(cliente):
    assert cliente.get("/api/sessao").json()["precisa_configurar"] is True
    dados = {"nome_conta": "Op", "nome": "Ana", "email": "Ana@Exemplo.com", "senha": "senha-forte-123"}
    assert cliente.post("/api/configurar", json=dados).status_code == 200
    assert cliente.get("/api/sessao").json()["usuario"]["email"] == "ana@exemplo.com"
    cliente.post("/api/sair")
    cliente.cookies.clear()
    assert cliente.post("/api/configurar", json={**dados, "email": "outro@x.com"}).status_code == 403
    assert cliente.post("/api/entrar", json={"email": "ana@exemplo.com", "senha": "errada"}).status_code == 401
    assert cliente.post("/api/entrar", json={"email": "ana@exemplo.com", "senha": "senha-forte-123"}).status_code == 200
    assert cliente.get("/api/sessao").json()["logado"] is True


def test_pixel_registra_visita_com_ids_do_meta(logado, app):
    conta = _conta(app)
    _visita(logado, conta)
    _visita(logado, conta, tipo="checkout")
    with app.state.banco.sessao() as sessao:
        visita = sessao.get(Visita, ID_VISITA)
        assert (visita.campanha_id, visita.conjunto_id, visita.anuncio_id) == (
            "120210000000000001", "120210000000000002", "120210000000000003")
        assert visita.ip == "177.10.20.30"
        assert (visita.paginas, visita.checkouts) == (1, 1)
        assert visita.fbclid == "IwAR123"
    # chave errada ou id fora do formato: ignora em silêncio
    logado.post("/c", content=json.dumps({"k": "pk_x", "c": "tkzzzzzzzzzzzzzzzzzz"}))
    logado.post("/c", content="não é json")
    with app.state.banco.sessao() as sessao:
        assert len(sessao.scalars(select(Visita)).all()) == 1


def test_venda_hotmart_herda_utms_da_visita_pelo_sck(logado, app):
    conta = _conta(app)
    _visita(logado, conta)
    integracao = _integracao(logado)
    resposta = _webhook(logado, integracao, amostras.hotmart(sck=ID_VISITA))
    assert resposta.json()["situacao"] == "processado"
    with app.state.banco.sessao() as sessao:
        venda = sessao.scalar(select(Venda))
        assert venda.visita_id == ID_VISITA
        assert venda.utm_campaign == "Campanha Black|120210000000000001"
        assert (venda.campanha_id, venda.campanha_nome) == ("120210000000000001", "Campanha Black")
        assert venda.anuncio_nome == "Vídeo 3"
        assert venda.dia == date(2025, 10, 5)


def test_status_nao_volta_atras(logado, app):
    integracao = _integracao(logado)
    _webhook(logado, integracao, amostras.hotmart(evento="PURCHASE_BILLET_PRINTED", tipo="BILLET"))
    _webhook(logado, integracao, amostras.hotmart(evento="PURCHASE_REFUNDED", tipo="BILLET"))
    _webhook(logado, integracao, amostras.hotmart(evento="PURCHASE_APPROVED", tipo="BILLET"))  # chegou atrasado
    with app.state.banco.sessao() as sessao:
        vendas = sessao.scalars(select(Venda)).all()
        assert len(vendas) == 1
        assert vendas[0].status == "reembolsada"


def test_webhook_com_segredo_errado_e_token_inexistente(logado):
    integracao = _integracao(logado, segredo="hottok-certo")
    assert _webhook(logado, integracao, amostras.hotmart(), headers={"X-Hotmart-Hottok": "errado"}).status_code == 401
    assert _webhook(logado, integracao, amostras.hotmart(),
                    headers={"X-Hotmart-Hottok": "hottok-certo"}).status_code == 200
    assert logado.post("/webhook/wh_naoexiste", json={}).status_code == 404


def test_webhook_com_erro_fica_no_log_e_pode_ser_reprocessado(logado, app):
    integracao = _integracao(logado, "generico")
    resposta = _webhook(logado, integracao, {"id": "p1", "status": "aprovada", "valor": 10})  # falta "data"
    assert resposta.status_code == 200 and resposta.json()["situacao"] == "erro"
    log = logado.get("/api/webhooks").json()
    assert log["itens"][0]["situacao"] == "erro"
    # Corrige o registro e reprocessa (simula um ajuste no adaptador)
    from rastro.modelos import WebhookRecebido
    with app.state.banco.sessao() as sessao:
        registro = sessao.get(WebhookRecebido, log["itens"][0]["id"])
        registro.corpo = json.dumps({"id": "p1", "status": "aprovada", "valor": 10, "data": "2025-10-05T10:00:00Z"})
    assert logado.post("/api/webhooks/reprocessar-erros").json() == {"reprocessados": 1, "ainda_com_erro": 0}


def _gastos(app, conta_id):
    with app.state.banco.sessao() as sessao:
        conta_anuncio = ContaAnuncio(conta_id=conta_id, meta_id="act_1", nome="BM Principal", ativo=True,
                                     cotacao=1.0, moeda="BRL")
        sessao.add(conta_anuncio)
        sessao.flush()
        for anuncio, gasto in (("120210000000000003", 5000), ("120210000000000004", 3000)):
            sessao.add(GastoDiario(conta_id=conta_id, conta_anuncio_id=conta_anuncio.id, dia=date(2025, 10, 5),
                                   campanha_id="120210000000000001", campanha_nome="Campanha Black",
                                   conjunto_id="120210000000000002", conjunto_nome="Conjunto Aberto",
                                   anuncio_id=anuncio, anuncio_nome=f"Anúncio {anuncio[-1]}", gasto_cent=gasto,
                                   impressoes=10000, cliques=300, cliques_link=200, visualizacoes_pagina=150,
                                   checkouts_iniciados=20, compras_meta=1))
        sessao.add(EntidadeAnuncio(conta_id=conta_id, id="120210000000000001", conta_anuncio_id=conta_anuncio.id,
                                   nivel="campanha", nome="Campanha Black", status="ACTIVE", status_efetivo="ACTIVE",
                                   orcamento_diario_cent=20000, campanha_id="120210000000000001"))


def test_painel_calcula_lucro_roas_e_tabela_de_campanhas(logado, app):
    conta = _conta(app)
    _gastos(app, conta.id)
    logado.put("/api/configuracoes", json={"imposto_pct": 10, "imposto_anuncios_pct": 12.15})
    _visita(logado, conta)
    integracao = _integracao(logado)
    _webhook(logado, integracao, amostras.hotmart(sck=ID_VISITA))  # líquido 177,50
    _webhook(logado, integracao, amostras.hotmart(transacao="HP2", evento="PURCHASE_BILLET_PRINTED", tipo="BILLET"))
    _webhook(logado, integracao, amostras.hotmart(transacao="HP3", evento="PURCHASE_REFUNDED"))
    produto = logado.get("/api/produtos").json()[0]
    logado.patch(f"/api/produtos/{produto['id']}", json={"custo": 7.5})

    painel = logado.get("/api/painel", params={"inicio": "2025-10-05", "fim": "2025-10-05"}).json()
    resumo = painel["resumo"]
    assert resumo["vendas"] == 1
    assert resumo["faturamento_liquido"] == 177.5
    assert resumo["gasto"] == 89.72  # 80,00 + 12,15% de imposto sobre anúncios
    assert resumo["impostos"] == 17.75
    assert resumo["custo_produtos"] == 7.5
    assert resumo["lucro"] == round(177.5 - 89.72 - 17.75 - 7.5, 2)
    assert resumo["roas"] == round(177.5 / 89.72, 4)
    assert resumo["pendentes"] == 1 and resumo["reembolsadas"] == 1
    assert resumo["taxa_reembolso"] == 0.5
    assert resumo["visitas"] == 0  # a visita foi registrada hoje, fora do período
    pix = next(p for p in painel["pagamentos"] if p["metodo"] == "pix")
    assert (pix["geradas"], pix["pagas"]) == (2, 2)
    assert len(painel["serie"]) == 1 and painel["serie"][0]["vendas"] == 1

    tabela = logado.get("/api/anuncios", params={"nivel": "campanha", "inicio": "2025-10-05",
                                                 "fim": "2025-10-05"}).json()
    [linha] = tabela["linhas"]
    assert linha["nome"] == "Campanha Black"
    assert linha["status"] == "ACTIVE" and linha["orcamento_diario"] == 200.0
    assert linha["vendas"] == 1 and linha["gasto"] == 89.72
    assert linha["ctr"] == 0.02 and linha["checkouts_iniciados"] == 40

    anuncios = logado.get("/api/anuncios", params={"nivel": "anuncio", "pai": "120210000000000002",
                                                   "inicio": "2025-10-05", "fim": "2025-10-05"}).json()["linhas"]
    assert [a["vendas"] for a in anuncios] == [1, 0]
    assert anuncios[0]["visitas"] == 0


def test_vendas_com_utm_fora_do_padrao_aparecem_pelo_nome(logado, app):
    integracao = _integracao(logado, "kiwify")
    tracking = {"utm_source": "facebook", "utm_campaign": "Campanha Sem ID", "utm_medium": "paid"}
    _webhook(logado, integracao, amostras.kiwify(tracking=tracking))
    linhas = logado.get("/api/anuncios", params={"inicio": "2025-10-05", "fim": "2025-10-05"}).json()["linhas"]
    assert [(l["id"], l["nome"], l["vendas"]) for l in linhas] == [(None, "Campanha Sem ID", 1)]


def test_lista_de_vendas_e_busca(logado):
    integracao = _integracao(logado, "kiwify")
    _webhook(logado, integracao, amostras.kiwify())
    _webhook(logado, integracao, amostras.kiwify(pedido="kw-2", status="refused", evento="order_rejected"))
    filtro = {"inicio": "2025-10-01", "fim": "2025-10-31"}
    assert logado.get("/api/vendas", params=filtro).json()["total"] == 2
    assert logado.get("/api/vendas", params={**filtro, "status": "recusada"}).json()["total"] == 1
    assert logado.get("/api/vendas", params={**filtro, "busca": "joao@"}).json()["total"] == 2


def test_capi_fica_pendente_quando_ativo(logado, app, monkeypatch):
    enviados = []
    monkeypatch.setattr("rastro.capi.ClienteMeta.enviar_eventos",
                        lambda self, pixel, eventos, teste=None: enviados.append((pixel, eventos)) or {})
    logado.put("/api/configuracoes", json={"capi_ativo": True, "capi_pixel_id": "999", "capi_token": "EAAtoken"})
    conta = _conta(app)
    _visita(logado, conta)
    dados = amostras.hotmart(sck=ID_VISITA)
    from rastro.modelos import agora
    dados["data"]["purchase"]["order_date"] = int(agora().timestamp() * 1000)
    dados["data"]["purchase"]["approved_date"] = int(agora().timestamp() * 1000)
    _webhook(logado, _integracao(logado), dados)
    assert len(enviados) == 1
    evento = enviados[0][1][0]
    assert evento["event_name"] == "Purchase" and evento["action_source"] == "website"
    assert evento["user_data"]["fbp"] == "fb.1.1700000000000.123"
    with app.state.banco.sessao() as sessao:
        assert sessao.scalar(select(Venda)).capi_situacao == "enviado"


def test_usuarios_e_troca_de_senha(logado):
    assert logado.post("/api/usuarios", json={"nome": "Bia", "email": "bia@x.com", "senha": "12345678"}).status_code == 200
    assert len(logado.get("/api/usuarios").json()) == 2
    assert logado.post("/api/usuarios/senha", json={"atual": "errada", "nova": "nova-senha-1"}).status_code == 400
    assert logado.post("/api/usuarios/senha", json={"atual": "senha-forte-123", "nova": "nova-senha-1"}).status_code == 200
    assert logado.get("/api/sessao").json()["logado"] is True  # o cookie foi renovado


def test_configuracoes_mostram_script_do_pixel(logado, app):
    dados = logado.get("/api/configuracoes").json()
    assert dados["script_pixel"].startswith('<script src="https://rastro.exemplo.com/p.js" data-conta="pk_')
    assert "{{campaign.name}}|{{campaign.id}}" in dados["padrao_utms"]
    assert logado.get("/p.js").headers["content-type"].startswith("application/javascript")


def test_pausar_e_mudar_orcamento_no_meta(logado, app, monkeypatch):
    chamadas = []
    monkeypatch.setattr("rastro.meta.ClienteMeta.alterar_status", lambda self, i, s: chamadas.append(("status", i, s)))
    monkeypatch.setattr("rastro.meta.ClienteMeta.alterar_orcamento_diario",
                        lambda self, i, c: chamadas.append(("orcamento", i, c)))
    conta = _conta(app)
    _gastos(app, conta.id)
    caminho = "/api/anuncios/120210000000000001"
    assert logado.post(f"{caminho}/status", json={"status": "PAUSED"}).status_code == 400  # Meta não conectado
    with app.state.banco.sessao() as sessao:
        sessao.get(Conta, conta.id).meta_token = "EAAtoken"
    assert logado.post(f"{caminho}/status", json={"status": "PAUSED"}).json() == {"ok": True, "status": "PAUSED"}
    assert logado.post(f"{caminho}/status", json={"status": "DELETED"}).status_code == 422
    assert logado.post(f"{caminho}/orcamento", json={"orcamento_diario": 350.5}).status_code == 200
    assert logado.post("/api/anuncios/999/status", json={"status": "ACTIVE"}).status_code == 404
    assert chamadas == [("status", "120210000000000001", "PAUSED"), ("orcamento", "120210000000000001", 35050)]
    linha = logado.get("/api/anuncios", params={"inicio": "2025-10-05", "fim": "2025-10-05"}).json()["linhas"][0]
    assert (linha["status"], linha["orcamento_diario"]) == ("PAUSED", 350.5)


def test_conectar_meta_lista_contas_de_anuncio(logado, monkeypatch):
    monkeypatch.setattr("rastro.meta.ClienteMeta.eu", lambda self: {"id": "1", "name": "Usuário do Sistema"})
    monkeypatch.setattr("rastro.meta.ClienteMeta.contas_anuncio", lambda self: [
        {"id": "act_9", "name": "BM Dólar", "currency": "USD", "timezone_name": "America/Sao_Paulo"}])
    dados = logado.post("/api/meta/token", json={"token": "EAA" + "x" * 40}).json()
    assert dados["conectado"] and dados["usuario"] == "Usuário do Sistema"
    assert dados["token"].startswith("••••")
    [conta_anuncio] = dados["contas_anuncio"]
    assert (conta_anuncio["meta_id"], conta_anuncio["ativo"], conta_anuncio["moeda"]) == ("act_9", False, "USD")
    ajustada = logado.patch(f"/api/meta/contas/{conta_anuncio['id']}", json={"cotacao": 5.4}).json()
    assert ajustada["contas_anuncio"][0]["cotacao"] == 5.4


def test_membro_nao_altera_configuracoes(logado):
    logado.post("/api/usuarios", json={"nome": "Bia", "email": "bia@x.com", "senha": "12345678"})
    logado.post("/api/sair")
    logado.cookies.clear()
    assert logado.post("/api/entrar", json={"email": "bia@x.com", "senha": "12345678"}).status_code == 200
    assert logado.get("/api/painel").status_code == 200
    assert logado.put("/api/configuracoes", json={"imposto_pct": 5}).status_code == 403
    assert logado.post("/api/integracoes", json={"plataforma": "kiwify"}).status_code == 403
