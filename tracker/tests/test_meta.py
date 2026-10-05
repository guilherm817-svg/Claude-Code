import hashlib
import json
from datetime import date, datetime, timezone
from urllib.parse import parse_qs

import httpx
import pytest
from sqlalchemy import select

from rastro.capi import montar_evento
from rastro.meta import ClienteMeta, ErroMeta
from rastro.modelos import Conta, ContaAnuncio, EntidadeAnuncio, GastoDiario, Venda, Visita
from rastro.sincronizacao import atualizar_contas_anuncio, sincronizar_conta_anuncio


def insight(dia, anuncio, gasto, **extra):
    return {"date_start": dia, "date_stop": dia, "campaign_id": "c1", "campaign_name": "Campanha",
            "adset_id": "s1", "adset_name": "Conjunto", "ad_id": anuncio, "ad_name": f"Anúncio {anuncio}",
            "spend": gasto, "impressions": "1000", "clicks": "40", "inline_link_clicks": "30",
            "actions": [{"action_type": "landing_page_view", "value": "25"},
                        {"action_type": "offsite_conversion.fb_pixel_initiate_checkout", "value": "4"},
                        {"action_type": "omni_purchase", "value": "1"}], **extra}


class MetaFalso:
    """Simula a Graph API: responde por caminho e guarda as chamadas."""

    def __init__(self, respostas):
        self.respostas = respostas
        self.chamadas = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.chamadas.append(request)
        caminho = request.url.path.split("/", 2)[2]  # tira "/v25.0/"
        resposta = self.respostas.get(caminho)
        if callable(resposta):
            resposta = resposta(request)
        if resposta is None:
            return httpx.Response(404, json={"error": {"message": f"sem resposta para {caminho}", "code": 803}})
        return httpx.Response(200, json=resposta)


def cliente_falso(respostas) -> tuple[ClienteMeta, MetaFalso]:
    falso = MetaFalso(respostas)
    return ClienteMeta("EAAtoken", "v25.0", httpx.Client(transport=httpx.MockTransport(falso))), falso


def test_paginacao_e_conversao_de_insights():
    pagina2 = "https://graph.facebook.com/v25.0/act_1/insights_pagina2"
    cliente, falso = cliente_falso({
        "act_1/insights": {"data": [insight("2026-10-04", "a1", "12.34")], "paging": {"next": pagina2}},
        "act_1/insights_pagina2": {"data": [insight("2026-10-05", "a1", "50")]},
    })
    linhas = list(cliente.insights("act_1", date(2026, 10, 4), date(2026, 10, 5)))
    assert [linha["gasto_cent"] for linha in linhas] == [1234, 5000]
    assert linhas[0]["visualizacoes_pagina"] == 25
    assert linhas[0]["checkouts_iniciados"] == 4
    assert linhas[0]["compras_meta"] == 1
    params = parse_qs(falso.chamadas[0].url.query.decode())
    assert params["level"] == ["ad"] and params["time_increment"] == ["1"]
    assert json.loads(params["time_range"][0]) == {"since": "2026-10-04", "until": "2026-10-05"}


def test_erro_de_token_vira_mensagem_clara():
    cliente, _ = cliente_falso({"me": lambda r: {"error": {"message": "Session expired", "code": 190}}})
    with pytest.raises(ErroMeta, match="Token do Meta inválido ou expirado"):
        cliente.eu()


@pytest.fixture
def conta(banco):
    with banco.sessao() as sessao:
        conta = Conta(nome="Op", meta_token="EAAtoken")
        sessao.add(conta)
    return conta


def test_sincronizacao_substitui_o_periodo_e_atualiza_entidades(banco, conta):
    gastos = {"valor": "10"}
    cliente, _ = cliente_falso({
        "me/adaccounts": {"data": [{"id": "act_1", "name": "BM 1", "currency": "USD",
                                    "timezone_name": "America/Sao_Paulo"}]},
        "act_1/insights": lambda r: {"data": [insight("2026-10-05", "a1", gastos["valor"])]},
        "act_1/campaigns": {"data": [{"id": "c1", "name": "Campanha", "status": "ACTIVE",
                                      "effective_status": "ACTIVE", "daily_budget": "15000"}]},
        "act_1/adsets": {"data": [{"id": "s1", "name": "Conjunto", "status": "PAUSED",
                                   "effective_status": "PAUSED", "campaign_id": "c1"}]},
        "act_1/ads": {"data": [{"id": "a1", "name": "Anúncio a1", "status": "ACTIVE",
                                "effective_status": "CAMPAIGN_PAUSED", "campaign_id": "c1", "adset_id": "s1"}]},
    })
    with banco.sessao() as sessao:
        conta = sessao.get(Conta, conta.id)
        [conta_anuncio] = atualizar_contas_anuncio(sessao, conta, cliente)
        assert (conta_anuncio.moeda, conta_anuncio.ativo) == ("USD", False)
        conta_anuncio.ativo = True
        sincronizar_conta_anuncio(sessao, conta_anuncio, cliente, date(2026, 10, 5), date(2026, 10, 5))
        gastos["valor"] = "25.5"  # o Meta revisou o gasto do dia
        sincronizar_conta_anuncio(sessao, conta_anuncio, cliente, date(2026, 10, 5), date(2026, 10, 5))
        assert conta_anuncio.erro is None and conta_anuncio.ultima_sincronizacao is not None
        assert [g.gasto_cent for g in sessao.scalars(select(GastoDiario))] == [2550]
        campanha = sessao.get(EntidadeAnuncio, (conta.id, "c1"))
        assert campanha.orcamento_diario_cent == 15000 and campanha.nivel == "campanha"
        assert sessao.get(EntidadeAnuncio, (conta.id, "a1")).conjunto_id == "s1"


def test_falha_na_sincronizacao_fica_registrada_na_conta(banco, conta):
    cliente, _ = cliente_falso({"act_1/insights": lambda r: {"error": {"message": "limite", "code": 17}}})
    with banco.sessao() as sessao:
        conta_anuncio = ContaAnuncio(conta_id=conta.id, meta_id="act_1", nome="BM", ativo=True, cotacao=1.0)
        sessao.add(conta_anuncio)
        sessao.flush()
        sincronizar_conta_anuncio(sessao, conta_anuncio, cliente)
        assert "Limite de chamadas" in conta_anuncio.erro


def test_evento_da_api_de_conversoes():
    venda = Venda(plataforma="hotmart", id_externo="HP1", moeda="BRL", valor_bruto_cent=19700,
                  cliente_email=" Cliente@Exemplo.com ", cliente_telefone="11999998888",
                  cliente_nome="Maria da Silva", produto_nome="Curso",
                  criada_em=datetime(2026, 10, 5, 12, tzinfo=timezone.utc),
                  aprovada_em=datetime(2026, 10, 5, 12, 5, tzinfo=timezone.utc))
    visita = Visita(id="tk0123456789abcdefgh", visitante_id="v1", ip="177.1.2.3", user_agent="Mozilla",
                    fbp="fb.1.1.2", fbc="fb.1.3.IwAR", url_entrada="https://lp.com/?utm_source=FB")
    evento = montar_evento(venda, visita)
    sha = lambda texto: hashlib.sha256(texto.encode()).hexdigest()  # noqa: E731
    assert evento["user_data"]["em"] == [sha("cliente@exemplo.com")]
    assert evento["user_data"]["ph"] == [sha("5511999998888")]
    assert evento["user_data"]["fn"] == [sha("maria")] and evento["user_data"]["ln"] == [sha("silva")]
    assert evento["user_data"]["client_ip_address"] == "177.1.2.3"
    assert evento["event_id"] == "rastro-hotmart-HP1"
    assert evento["event_time"] == int(datetime(2026, 10, 5, 12, 5, tzinfo=timezone.utc).timestamp())
    assert evento["custom_data"]["value"] == 197.0
    assert evento["event_source_url"] == "https://lp.com/?utm_source=FB"
    # Sem visita rastreada não há user agent: o evento vai como "system_generated"
    assert montar_evento(venda, None)["action_source"] == "system_generated"
