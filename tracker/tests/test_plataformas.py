import hashlib
import hmac
import json
from datetime import datetime, timezone

import pytest

from rastro.modelos import MetodoPagamento, StatusVenda
from rastro.plataformas import EventoIgnorado, PayloadInvalido, generico, hotmart, kiwify
from rastro.plataformas.base import centavos, data_hora
from tests import amostras


def test_hotmart_aprovada():
    venda = hotmart.interpretar(amostras.hotmart(sck="tkabcdefghij0123456789"))
    assert venda.id_externo == "HP1234567890"
    assert venda.status == StatusVenda.APROVADA
    assert venda.metodo_pagamento == MetodoPagamento.PIX
    assert venda.valor_bruto_cent == 19700
    assert venda.valor_liquido_cent == 17750  # comissão do produtor
    assert venda.criada_em == datetime(2025, 10, 5, 17, 0, tzinfo=timezone.utc)
    assert venda.cliente_documento == "12345678900"
    assert venda.rastreio["sck"] == "tkabcdefghij0123456789"
    assert venda.produto_nome == "Curso de Tráfego"


@pytest.mark.parametrize(("evento", "tipo", "status"), [
    ("PURCHASE_BILLET_PRINTED", "BILLET", StatusVenda.PENDENTE),
    ("PURCHASE_REFUNDED", "PIX", StatusVenda.REEMBOLSADA),
    ("PURCHASE_CHARGEBACK", "CREDIT_CARD", StatusVenda.CHARGEBACK),
    ("PURCHASE_CANCELED", "CREDIT_CARD", StatusVenda.RECUSADA),
    ("PURCHASE_CANCELED", "BILLET", StatusVenda.CANCELADA),
    ("PURCHASE_EXPIRED", "PIX", StatusVenda.CANCELADA),
])
def test_hotmart_status(evento, tipo, status):
    assert hotmart.interpretar(amostras.hotmart(evento=evento, tipo=tipo)).status == status


def test_hotmart_afiliado_usa_comissao_do_afiliado():
    dados = amostras.hotmart()
    dados["data"]["commissions"].append({"value": 98.5, "source": "AFFILIATE"})
    assert hotmart.interpretar(dados, papel="afiliado").valor_liquido_cent == 9850


def test_hotmart_eventos_que_nao_sao_venda():
    with pytest.raises(EventoIgnorado):
        hotmart.interpretar(amostras.hotmart(evento="PURCHASE_OUT_OF_SHOPPING_CART"))
    with pytest.raises(PayloadInvalido):
        hotmart.interpretar({"foo": "bar"})


def test_hotmart_hottok():
    assert hotmart.verificar(b"{}", {"x-hotmart-hottok": "abc"}, {}, "abc")
    assert not hotmart.verificar(b"{}", {"x-hotmart-hottok": "errado"}, {}, "abc")
    assert not hotmart.verificar(b"{}", {}, {}, "abc")


def test_kiwify_aprovada_com_utms():
    tracking = {"utm_source": "FB", "utm_campaign": "Black|120210000000000001", "sck": None}
    venda = kiwify.interpretar(amostras.kiwify(tracking=tracking))
    assert venda.status == StatusVenda.APROVADA
    assert venda.metodo_pagamento == MetodoPagamento.CARTAO
    assert (venda.valor_bruto_cent, venda.valor_liquido_cent) == (9700, 8803)
    assert venda.rastreio["utm_campaign"] == "Black|120210000000000001"
    assert venda.cliente_telefone == "5521988887777"
    # "2025-10-05 10:15" sem fuso = horário de Brasília
    assert venda.criada_em == datetime(2025, 10, 5, 13, 15, tzinfo=timezone.utc)


def test_kiwify_pix_gerado_e_reembolso():
    assert kiwify.interpretar(amostras.kiwify(status="waiting_payment", evento="pix_created",
                                              metodo="pix")).status == StatusVenda.PENDENTE
    assert kiwify.interpretar(amostras.kiwify(status="refunded", evento="order_refunded")).status == \
        StatusVenda.REEMBOLSADA


def test_kiwify_carrinho_abandonado():
    with pytest.raises(EventoIgnorado):
        kiwify.interpretar({"webhook_event_type": "abandoned_cart", "checkout_link": "x", "email": "a@b.com"})


def test_kiwify_assinatura():
    corpo = json.dumps(amostras.kiwify()).encode()
    assinatura = hmac.new(b"token-kiwify", corpo, hashlib.sha1).hexdigest()
    assert kiwify.verificar(corpo, {}, {"signature": assinatura}, "token-kiwify")
    assert not kiwify.verificar(corpo, {}, {"signature": "0" * 40}, "token-kiwify")


def test_generico():
    venda = generico.interpretar({
        "id": "ped-1", "status": "pago", "valor": "197,00", "valor_liquido": 180.5, "metodo_pagamento": "cartão",
        "data": "2026-10-05T14:30:00-03:00", "produto": {"nome": "Ebook"},
        "cliente": {"email": "x@y.com", "telefone": "(11) 99999-0000"}, "rastreio": {"utm_source": "google"},
    })
    assert venda.status == StatusVenda.APROVADA
    assert venda.metodo_pagamento == MetodoPagamento.CARTAO
    assert (venda.valor_bruto_cent, venda.valor_liquido_cent) == (19700, 18050)
    assert venda.cliente_telefone == "11999990000"
    assert venda.aprovada_em == venda.criada_em
    with pytest.raises(PayloadInvalido):
        generico.interpretar({"id": "x", "status": "talvez", "data": "2026-10-05"})
    with pytest.raises(EventoIgnorado):
        generico.interpretar({"teste": True})


def test_generico_assinatura():
    corpo = b'{"id":"1"}'
    assinatura = hmac.new(b"s3gredo", corpo, hashlib.sha256).hexdigest()
    assert generico.verificar(corpo, {"x-rastro-assinatura": f"sha256={assinatura}"}, {}, "s3gredo")
    assert generico.verificar(corpo, {"x-rastro-token": "s3gredo"}, {}, "s3gredo")
    assert not generico.verificar(corpo, {"x-rastro-token": "outro"}, {}, "s3gredo")


@pytest.mark.parametrize(("entrada", "esperado"), [
    (97, 9700), ("97.90", 9790), ("1.297,90", 129790), ("R$ 47,00", 4700), (None, 0), ("abc", 0), (0.1 + 0.2, 30),
])
def test_centavos(entrada, esperado):
    assert centavos(entrada) == esperado


def test_data_hora():
    assert data_hora(1759683600) == datetime(2025, 10, 5, 17, 0, tzinfo=timezone.utc)
    assert data_hora("05/10/2025 14:00") == datetime(2025, 10, 5, 17, 0, tzinfo=timezone.utc)
    assert data_hora("2025-10-05T17:00:00Z") == datetime(2025, 10, 5, 17, 0, tzinfo=timezone.utc)
    assert data_hora("lixo") is None
