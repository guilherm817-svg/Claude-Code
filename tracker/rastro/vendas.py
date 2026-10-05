"""Recebe webhooks, grava a venda (criando ou atualizando) e registra o resultado no log."""

import json
import logging
from datetime import date, datetime
from urllib.parse import parse_qsl
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session

from rastro.atribuicao import atribuir
from rastro.modelos import Conta, Integracao, Produto, StatusVenda, Venda, WebhookRecebido, agora
from rastro.plataformas import PLATAFORMAS, EventoIgnorado, PayloadInvalido, VendaNormalizada

log = logging.getLogger(__name__)


def dia_local(momento: datetime, fuso: str) -> date:
    return momento.astimezone(ZoneInfo(fuso)).date()


def ler_corpo(corpo: bytes) -> object:
    """JSON, ou formulário (application/x-www-form-urlencoded) como dicionário."""
    texto = corpo.decode("utf-8", errors="replace").strip()
    if not texto:
        raise PayloadInvalido("Corpo vazio.")
    try:
        return json.loads(texto)
    except json.JSONDecodeError:
        pares = parse_qsl(texto, keep_blank_values=True)
        if not pares:
            raise PayloadInvalido("O corpo não é JSON nem formulário.") from None
        return dict(pares)


def _produto(sessao: Session, conta_id: int, plataforma: str, normalizada: VendaNormalizada) -> Produto | None:
    chave = normalizada.produto_id or normalizada.produto_nome
    if not chave:
        return None
    produto = sessao.scalar(select(Produto).where(
        Produto.conta_id == conta_id, Produto.plataforma == plataforma, Produto.id_externo == chave))
    if produto is None:
        produto = Produto(conta_id=conta_id, plataforma=plataforma, id_externo=chave,
                          nome=normalizada.produto_nome or chave, custo_cent=0)
        sessao.add(produto)
        sessao.flush()
    elif normalizada.produto_nome and produto.nome != normalizada.produto_nome:
        produto.nome = normalizada.produto_nome
    return produto


def registrar_venda(sessao: Session, conta: Conta, plataforma: str, normalizada: VendaNormalizada) -> Venda:
    # FOR UPDATE: dois webhooks da mesma venda ao mesmo tempo (ex.: aprovada e reembolsada) são aplicados um
    # depois do outro, e a regra de status nunca volta atrás vale mesmo assim.
    venda = sessao.scalar(select(Venda).where(
        Venda.conta_id == conta.id, Venda.plataforma == plataforma, Venda.id_externo == normalizada.id_externo)
        .with_for_update())
    status_anterior = venda.status if venda else None
    if venda is None:
        venda = Venda(conta_id=conta.id, plataforma=plataforma, id_externo=normalizada.id_externo,
                      status=normalizada.status, criada_em=normalizada.criada_em)
        sessao.add(venda)

    if status_anterior is None or StatusVenda.NIVEL[normalizada.status] >= StatusVenda.NIVEL[status_anterior]:
        venda.status = normalizada.status
    venda.metodo_pagamento = normalizada.metodo_pagamento
    venda.moeda = normalizada.moeda
    # Reembolsos às vezes chegam com valor zerado: mantém o valor original da venda.
    if normalizada.valor_bruto_cent or not venda.valor_bruto_cent:
        venda.valor_bruto_cent = normalizada.valor_bruto_cent
    if normalizada.valor_liquido_cent or not venda.valor_liquido_cent:
        venda.valor_liquido_cent = normalizada.valor_liquido_cent
    venda.criada_em = min(venda.criada_em, normalizada.criada_em) if venda.criada_em else normalizada.criada_em
    venda.aprovada_em = venda.aprovada_em or normalizada.aprovada_em
    if venda.status == StatusVenda.APROVADA and venda.aprovada_em is None:
        venda.aprovada_em = agora()
    venda.dia = dia_local(venda.criada_em, conta.fuso)
    for campo in ("cliente_nome", "cliente_email", "cliente_telefone", "cliente_documento", "cliente_ip"):
        setattr(venda, campo, getattr(normalizada, campo) or getattr(venda, campo))
    produto = _produto(sessao, conta.id, plataforma, normalizada)
    if produto is not None:
        venda.produto_id = produto.id
        venda.produto_nome = produto.nome
    venda.atualizada_em = agora()

    atribuir(sessao, venda, normalizada.rastreio)

    if (conta.capi_ativo and venda.status == StatusVenda.APROVADA and status_anterior != StatusVenda.APROVADA
            and venda.capi_situacao is None):
        venda.capi_situacao = "pendente"
    sessao.flush()
    return venda


def processar(sessao: Session, integracao: Integracao, registro: WebhookRecebido) -> Venda | None:
    """Interpreta um webhook já guardado e atualiza seu resultado. Não levanta exceção."""
    conta = sessao.get(Conta, integracao.conta_id)
    modulo = PLATAFORMAS[integracao.plataforma]
    try:
        dados = ler_corpo(registro.corpo.encode())
        normalizada = modulo.interpretar(dados, papel=integracao.papel, fuso=conta.fuso)
        with sessao.begin_nested():
            venda = registrar_venda(sessao, conta, integracao.plataforma, normalizada)
    except EventoIgnorado as erro:
        registro.situacao, registro.mensagem = "ignorado", str(erro)
        return None
    except PayloadInvalido as erro:
        registro.situacao, registro.mensagem = "erro", str(erro)
        return None
    except (IntegrityError, OperationalError):
        raise  # conflito com uma gravação simultânea: quem chamou repete a transação inteira
    except Exception as erro:  # noqa: BLE001 — o webhook fica no log para reprocessar depois
        log.exception("Falha ao processar webhook %s", registro.id)
        registro.situacao, registro.mensagem = "erro", f"Erro interno: {erro}"
        return None
    registro.situacao = "processado"
    registro.mensagem = f"Venda {venda.id_externo} · {venda.status}"
    registro.venda_id = venda.id
    return venda


def receber(sessao: Session, integracao: Integracao, corpo: bytes) -> tuple[WebhookRecebido, Venda | None]:
    registro = WebhookRecebido(conta_id=integracao.conta_id, integracao_id=integracao.id,
                               corpo=corpo.decode("utf-8", errors="replace")[:500_000], situacao="erro")
    sessao.add(registro)
    sessao.flush()
    integracao.ultimo_recebimento = agora()
    venda = processar(sessao, integracao, registro)
    return registro, venda
