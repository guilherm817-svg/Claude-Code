"""Tabelas do banco. Valores em dinheiro ficam em centavos (inteiros), datas em UTC."""

import secrets
from datetime import date, datetime, timezone

from sqlalchemy import (
    BigInteger, Boolean, Date, DateTime, Float, ForeignKey, Index, Integer, String, Text, TypeDecorator,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from rastro.db import Base


def agora() -> datetime:
    return datetime.now(timezone.utc)


class DataHoraUTC(TypeDecorator):
    """Grava em UTC sem fuso e devolve sempre com fuso UTC (o SQLite perderia o fuso)."""

    impl = DateTime
    cache_ok = True

    def process_bind_param(self, valor, dialeto):
        if valor is None:
            return None
        if valor.tzinfo is None:
            valor = valor.replace(tzinfo=timezone.utc)
        return valor.astimezone(timezone.utc).replace(tzinfo=None)

    def process_result_value(self, valor, dialeto):
        return valor.replace(tzinfo=timezone.utc) if valor is not None else None


def gerar_token(prefixo: str, tamanho: int = 24) -> str:
    return prefixo + secrets.token_urlsafe(tamanho).replace("-", "").replace("_", "")[:tamanho]


class StatusVenda:
    APROVADA = "aprovada"
    PENDENTE = "pendente"  # boleto ou Pix gerado, aguardando pagamento
    RECUSADA = "recusada"
    CANCELADA = "cancelada"  # expirada ou cancelada antes de pagar
    REEMBOLSADA = "reembolsada"
    CHARGEBACK = "chargeback"

    TODOS = (APROVADA, PENDENTE, RECUSADA, CANCELADA, REEMBOLSADA, CHARGEBACK)
    # Um status de nível menor nunca sobrescreve um de nível maior: webhooks chegam fora de ordem.
    NIVEL = {PENDENTE: 0, RECUSADA: 1, CANCELADA: 1, APROVADA: 2, REEMBOLSADA: 3, CHARGEBACK: 3}


class MetodoPagamento:
    PIX = "pix"
    CARTAO = "cartao"
    BOLETO = "boleto"
    OUTRO = "outro"

    TODOS = (PIX, CARTAO, BOLETO, OUTRO)


class Conta(Base):
    """Uma operação (empresa/workspace). Tudo no banco pertence a uma conta."""

    __tablename__ = "contas"

    id: Mapped[int] = mapped_column(primary_key=True)
    nome: Mapped[str] = mapped_column(String(120))
    chave_publica: Mapped[str] = mapped_column(String(40), unique=True, default=lambda: gerar_token("pk_", 20))
    fuso: Mapped[str] = mapped_column(String(64), default="America/Sao_Paulo")
    moeda: Mapped[str] = mapped_column(String(3), default="BRL")
    imposto_pct: Mapped[float] = mapped_column(Float, default=0.0)  # sobre o faturamento líquido
    imposto_anuncios_pct: Mapped[float] = mapped_column(Float, default=0.0)  # somado ao gasto com anúncios
    meta_token: Mapped[str | None] = mapped_column(Text)
    meta_usuario: Mapped[str | None] = mapped_column(String(200))
    capi_ativo: Mapped[bool] = mapped_column(Boolean, default=False)
    capi_pixel_id: Mapped[str | None] = mapped_column(String(40))
    capi_token: Mapped[str | None] = mapped_column(Text)
    capi_codigo_teste: Mapped[str | None] = mapped_column(String(40))
    criado_em: Mapped[datetime] = mapped_column(DataHoraUTC, default=agora)


class Usuario(Base):
    __tablename__ = "usuarios"

    id: Mapped[int] = mapped_column(primary_key=True)
    conta_id: Mapped[int] = mapped_column(ForeignKey("contas.id", ondelete="CASCADE"), index=True)
    nome: Mapped[str] = mapped_column(String(120))
    email: Mapped[str] = mapped_column(String(200), unique=True)
    senha_hash: Mapped[str] = mapped_column(String(300))
    admin: Mapped[bool] = mapped_column(Boolean, default=False)
    # Muda quando a senha muda: invalida as sessões abertas com a senha antiga.
    versao_sessao: Mapped[int] = mapped_column(Integer, default=1)
    criado_em: Mapped[datetime] = mapped_column(DataHoraUTC, default=agora)


class Integracao(Base):
    """Um endereço de webhook para uma plataforma de venda (Hotmart, Kiwify...)."""

    __tablename__ = "integracoes"

    id: Mapped[int] = mapped_column(primary_key=True)
    conta_id: Mapped[int] = mapped_column(ForeignKey("contas.id", ondelete="CASCADE"), index=True)
    plataforma: Mapped[str] = mapped_column(String(30))
    nome: Mapped[str] = mapped_column(String(120))
    token: Mapped[str] = mapped_column(String(60), unique=True, default=lambda: gerar_token("wh_", 32))
    segredo: Mapped[str | None] = mapped_column(String(200))  # hottok da Hotmart, token da Kiwify...
    # De quem é a comissão que conta como faturamento líquido (Hotmart): produtor, coprodutor ou afiliado.
    papel: Mapped[str] = mapped_column(String(20), default="produtor")
    ativo: Mapped[bool] = mapped_column(Boolean, default=True)
    criado_em: Mapped[datetime] = mapped_column(DataHoraUTC, default=agora)
    ultimo_recebimento: Mapped[datetime | None] = mapped_column(DataHoraUTC)


class WebhookRecebido(Base):
    """Cada chamada de webhook, guardada crua para auditoria e reprocessamento."""

    __tablename__ = "webhooks_recebidos"

    id: Mapped[int] = mapped_column(primary_key=True)
    conta_id: Mapped[int] = mapped_column(ForeignKey("contas.id", ondelete="CASCADE"))
    integracao_id: Mapped[int] = mapped_column(ForeignKey("integracoes.id", ondelete="CASCADE"))
    recebido_em: Mapped[datetime] = mapped_column(DataHoraUTC, default=agora)
    corpo: Mapped[str] = mapped_column(Text)
    situacao: Mapped[str] = mapped_column(String(20))  # processado, ignorado, erro
    mensagem: Mapped[str | None] = mapped_column(Text)
    venda_id: Mapped[int | None] = mapped_column(ForeignKey("vendas.id", ondelete="SET NULL"))

    __table_args__ = (Index("ix_webhooks_conta_data", "conta_id", "recebido_em"),)


class Visita(Base):
    """Uma chegada rastreada pelo pixel. O id ("tk...") vai para o checkout no parâmetro sck."""

    __tablename__ = "visitas"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    conta_id: Mapped[int] = mapped_column(ForeignKey("contas.id", ondelete="CASCADE"))
    visitante_id: Mapped[str | None] = mapped_column(String(40))
    criado_em: Mapped[datetime] = mapped_column(DataHoraUTC, default=agora)
    atualizado_em: Mapped[datetime] = mapped_column(DataHoraUTC, default=agora)
    dia: Mapped[date] = mapped_column(Date)
    utm_source: Mapped[str | None] = mapped_column(String(300))
    utm_medium: Mapped[str | None] = mapped_column(String(300))
    utm_campaign: Mapped[str | None] = mapped_column(String(300))
    utm_content: Mapped[str | None] = mapped_column(String(300))
    utm_term: Mapped[str | None] = mapped_column(String(300))
    campanha_id: Mapped[str | None] = mapped_column(String(40))
    conjunto_id: Mapped[str | None] = mapped_column(String(40))
    anuncio_id: Mapped[str | None] = mapped_column(String(40))
    fbclid: Mapped[str | None] = mapped_column(String(500))
    gclid: Mapped[str | None] = mapped_column(String(500))
    ttclid: Mapped[str | None] = mapped_column(String(500))
    fbp: Mapped[str | None] = mapped_column(String(200))
    fbc: Mapped[str | None] = mapped_column(String(600))
    ip: Mapped[str | None] = mapped_column(String(64))
    user_agent: Mapped[str | None] = mapped_column(String(500))
    url_entrada: Mapped[str | None] = mapped_column(String(1000))
    referrer: Mapped[str | None] = mapped_column(String(1000))
    paginas: Mapped[int] = mapped_column(Integer, default=0)
    checkouts: Mapped[int] = mapped_column(Integer, default=0)

    __table_args__ = (Index("ix_visitas_conta_dia", "conta_id", "dia"),)


class Produto(Base):
    """Criado automaticamente na primeira venda. O custo é preenchido no painel."""

    __tablename__ = "produtos"

    id: Mapped[int] = mapped_column(primary_key=True)
    conta_id: Mapped[int] = mapped_column(ForeignKey("contas.id", ondelete="CASCADE"))
    plataforma: Mapped[str] = mapped_column(String(30))
    id_externo: Mapped[str] = mapped_column(String(120))
    nome: Mapped[str] = mapped_column(String(300))
    custo_cent: Mapped[int] = mapped_column(BigInteger, default=0)  # custo por venda (frete, produção...)

    __table_args__ = (UniqueConstraint("conta_id", "plataforma", "id_externo"),)


class Venda(Base):
    __tablename__ = "vendas"

    id: Mapped[int] = mapped_column(primary_key=True)
    conta_id: Mapped[int] = mapped_column(ForeignKey("contas.id", ondelete="CASCADE"))
    plataforma: Mapped[str] = mapped_column(String(30))
    id_externo: Mapped[str] = mapped_column(String(120))
    status: Mapped[str] = mapped_column(String(20))
    metodo_pagamento: Mapped[str] = mapped_column(String(20), default=MetodoPagamento.OUTRO)
    moeda: Mapped[str] = mapped_column(String(3), default="BRL")
    valor_bruto_cent: Mapped[int] = mapped_column(BigInteger, default=0)  # o que o cliente pagou
    valor_liquido_cent: Mapped[int] = mapped_column(BigInteger, default=0)  # o que fica para você
    produto_id: Mapped[int | None] = mapped_column(ForeignKey("produtos.id", ondelete="SET NULL"))
    produto_nome: Mapped[str | None] = mapped_column(String(300))
    cliente_nome: Mapped[str | None] = mapped_column(String(200))
    cliente_email: Mapped[str | None] = mapped_column(String(200))
    cliente_telefone: Mapped[str | None] = mapped_column(String(40))
    cliente_documento: Mapped[str | None] = mapped_column(String(40))
    cliente_ip: Mapped[str | None] = mapped_column(String(64))
    criada_em: Mapped[datetime] = mapped_column(DataHoraUTC)
    aprovada_em: Mapped[datetime | None] = mapped_column(DataHoraUTC)
    atualizada_em: Mapped[datetime] = mapped_column(DataHoraUTC, default=agora)
    dia: Mapped[date] = mapped_column(Date)  # dia da venda no fuso da conta (base dos filtros)
    utm_source: Mapped[str | None] = mapped_column(String(300))
    utm_medium: Mapped[str | None] = mapped_column(String(300))
    utm_campaign: Mapped[str | None] = mapped_column(String(300))
    utm_content: Mapped[str | None] = mapped_column(String(300))
    utm_term: Mapped[str | None] = mapped_column(String(300))
    src: Mapped[str | None] = mapped_column(String(300))
    sck: Mapped[str | None] = mapped_column(String(300))
    visita_id: Mapped[str | None] = mapped_column(ForeignKey("visitas.id", ondelete="SET NULL"))
    campanha_id: Mapped[str | None] = mapped_column(String(40))
    campanha_nome: Mapped[str | None] = mapped_column(String(300))
    conjunto_id: Mapped[str | None] = mapped_column(String(40))
    conjunto_nome: Mapped[str | None] = mapped_column(String(300))
    anuncio_id: Mapped[str | None] = mapped_column(String(40))
    anuncio_nome: Mapped[str | None] = mapped_column(String(300))
    capi_situacao: Mapped[str | None] = mapped_column(String(20))  # pendente, enviado, erro
    capi_enviado_em: Mapped[datetime | None] = mapped_column(DataHoraUTC)
    capi_erro: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        UniqueConstraint("conta_id", "plataforma", "id_externo"),
        Index("ix_vendas_conta_dia", "conta_id", "dia"),
    )


class ContaAnuncio(Base):
    """Conta de anúncios do Meta (act_...)."""

    __tablename__ = "contas_anuncio"

    id: Mapped[int] = mapped_column(primary_key=True)
    conta_id: Mapped[int] = mapped_column(ForeignKey("contas.id", ondelete="CASCADE"))
    meta_id: Mapped[str] = mapped_column(String(40))  # "act_123"
    nome: Mapped[str] = mapped_column(String(200))
    moeda: Mapped[str] = mapped_column(String(3), default="BRL")
    fuso: Mapped[str | None] = mapped_column(String(64))
    ativo: Mapped[bool] = mapped_column(Boolean, default=False)  # sincronizar gastos desta conta?
    # Multiplica o gasto para a moeda da conta (ex.: conta de anúncios em dólar → 5,40).
    cotacao: Mapped[float] = mapped_column(Float, default=1.0)
    ultima_sincronizacao: Mapped[datetime | None] = mapped_column(DataHoraUTC)
    erro: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (UniqueConstraint("conta_id", "meta_id"),)


class EntidadeAnuncio(Base):
    """Campanha, conjunto ou anúncio do Meta, com status e orçamento atuais."""

    __tablename__ = "entidades_anuncio"

    conta_id: Mapped[int] = mapped_column(ForeignKey("contas.id", ondelete="CASCADE"), primary_key=True)
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    conta_anuncio_id: Mapped[int] = mapped_column(ForeignKey("contas_anuncio.id", ondelete="CASCADE"))
    nivel: Mapped[str] = mapped_column(String(10))  # campanha, conjunto, anuncio
    nome: Mapped[str] = mapped_column(String(300))
    status: Mapped[str | None] = mapped_column(String(30))
    status_efetivo: Mapped[str | None] = mapped_column(String(40))
    orcamento_diario_cent: Mapped[int | None] = mapped_column(BigInteger)
    orcamento_total_cent: Mapped[int | None] = mapped_column(BigInteger)
    campanha_id: Mapped[str | None] = mapped_column(String(40))
    conjunto_id: Mapped[str | None] = mapped_column(String(40))
    atualizado_em: Mapped[datetime] = mapped_column(DataHoraUTC, default=agora)

    __table_args__ = (Index("ix_entidades_nome", "conta_id", "nivel", "nome"),)


class GastoDiario(Base):
    """Insights do Meta por anúncio e por dia (no fuso da conta de anúncios)."""

    __tablename__ = "gastos_diarios"

    id: Mapped[int] = mapped_column(primary_key=True)
    conta_id: Mapped[int] = mapped_column(ForeignKey("contas.id", ondelete="CASCADE"))
    conta_anuncio_id: Mapped[int] = mapped_column(ForeignKey("contas_anuncio.id", ondelete="CASCADE"))
    dia: Mapped[date] = mapped_column(Date)
    campanha_id: Mapped[str] = mapped_column(String(40))
    campanha_nome: Mapped[str] = mapped_column(String(300))
    conjunto_id: Mapped[str] = mapped_column(String(40))
    conjunto_nome: Mapped[str] = mapped_column(String(300))
    anuncio_id: Mapped[str] = mapped_column(String(40))
    anuncio_nome: Mapped[str] = mapped_column(String(300))
    gasto_cent: Mapped[int] = mapped_column(BigInteger, default=0)  # na moeda da conta de anúncios
    impressoes: Mapped[int] = mapped_column(BigInteger, default=0)
    cliques: Mapped[int] = mapped_column(BigInteger, default=0)
    cliques_link: Mapped[int] = mapped_column(BigInteger, default=0)
    visualizacoes_pagina: Mapped[int] = mapped_column(BigInteger, default=0)
    checkouts_iniciados: Mapped[int] = mapped_column(BigInteger, default=0)
    compras_meta: Mapped[int] = mapped_column(BigInteger, default=0)

    __table_args__ = (
        UniqueConstraint("conta_anuncio_id", "anuncio_id", "dia"),
        Index("ix_gastos_conta_dia", "conta_id", "dia"),
    )
