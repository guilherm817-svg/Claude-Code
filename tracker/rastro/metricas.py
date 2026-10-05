"""Números do painel: faturamento, gasto, lucro, ROAS, CPA... no total, por dia e por campanha/conjunto/anúncio.

Definições (as mesmas mostradas nas dicas do painel):
- Faturamento líquido: o que fica para você das vendas aprovadas (já sem as taxas da plataforma).
- Gasto com anúncios: gasto do Meta × cotação da conta de anúncio × (1 + imposto sobre anúncios).
- Lucro: faturamento líquido − gasto com anúncios − impostos − custo dos produtos.
- ROAS: faturamento líquido ÷ gasto com anúncios.     ROI: lucro ÷ (gasto + impostos + custo dos produtos).
- CPA: gasto com anúncios ÷ vendas aprovadas.          Margem: lucro ÷ faturamento líquido.
"""

from dataclasses import dataclass, replace
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import Select, case, func, or_, select
from sqlalchemy.orm import Session

from rastro.modelos import (
    Conta, ContaAnuncio, EntidadeAnuncio, GastoDiario, MetodoPagamento, Produto, StatusVenda, Venda, Visita,
)

PAGAS = (StatusVenda.APROVADA, StatusVenda.REEMBOLSADA, StatusVenda.CHARGEBACK)
NIVEIS = ("campanha", "conjunto", "anuncio")


@dataclass(frozen=True)
class Filtros:
    inicio: date
    fim: date
    plataforma: str | None = None
    produto_id: int | None = None
    conta_anuncio_id: int | None = None
    campanha: str | None = None  # trecho do nome da campanha

    def periodo_anterior(self) -> "Filtros":
        dias = (self.fim - self.inicio).days + 1
        return replace(self, inicio=self.inicio - timedelta(days=dias), fim=self.inicio - timedelta(days=1))


def reais(centavos: float | int | None) -> float:
    return round(float(centavos or 0) / 100, 2)


def _dividir(a: float, b: float) -> float | None:
    return round(float(a) / float(b), 4) if b else None


def _filtrar_vendas(consulta: Select, conta_id: int, f: Filtros) -> Select:
    consulta = consulta.where(Venda.conta_id == conta_id, Venda.dia >= f.inicio, Venda.dia <= f.fim)
    if f.plataforma:
        consulta = consulta.where(Venda.plataforma == f.plataforma)
    if f.produto_id:
        consulta = consulta.where(Venda.produto_id == f.produto_id)
    if f.campanha:
        consulta = consulta.where(Venda.campanha_nome.ilike(f"%{f.campanha}%"))
    if f.conta_anuncio_id:
        campanhas = select(EntidadeAnuncio.id).where(EntidadeAnuncio.conta_id == conta_id,
                                                     EntidadeAnuncio.conta_anuncio_id == f.conta_anuncio_id)
        consulta = consulta.where(Venda.campanha_id.in_(campanhas))
    return consulta


def _filtrar_gastos(consulta: Select, conta_id: int, f: Filtros) -> Select:
    consulta = consulta.where(GastoDiario.conta_id == conta_id, GastoDiario.dia >= f.inicio,
                              GastoDiario.dia <= f.fim)
    if f.conta_anuncio_id:
        consulta = consulta.where(GastoDiario.conta_anuncio_id == f.conta_anuncio_id)
    if f.campanha:
        consulta = consulta.where(GastoDiario.campanha_nome.ilike(f"%{f.campanha}%"))
    return consulta


_GASTO = func.coalesce(func.sum(GastoDiario.gasto_cent * ContaAnuncio.cotacao), 0)


def _soma_se(condicao, valor=1):
    return func.coalesce(func.sum(case((condicao, valor), else_=0)), 0)


_APROVADA = Venda.status == StatusVenda.APROVADA
_COLUNAS_VENDAS = (
    _soma_se(_APROVADA).label("aprovadas"),
    _soma_se(_APROVADA, Venda.valor_bruto_cent).label("bruto"),
    _soma_se(_APROVADA, Venda.valor_liquido_cent).label("liquido"),
    _soma_se(_APROVADA, func.coalesce(Produto.custo_cent, 0)).label("custo"),
    _soma_se(Venda.status == StatusVenda.PENDENTE).label("pendentes"),
    _soma_se(Venda.status == StatusVenda.PENDENTE, Venda.valor_bruto_cent).label("pendentes_valor"),
    _soma_se(Venda.status == StatusVenda.REEMBOLSADA).label("reembolsadas"),
    _soma_se(Venda.status == StatusVenda.REEMBOLSADA, Venda.valor_bruto_cent).label("reembolsadas_valor"),
    _soma_se(Venda.status == StatusVenda.CHARGEBACK).label("chargebacks"),
    _soma_se(Venda.status == StatusVenda.CHARGEBACK, Venda.valor_bruto_cent).label("chargebacks_valor"),
    _soma_se(Venda.status == StatusVenda.RECUSADA).label("recusadas"),
)


def _calcular(conta: Conta, v: dict[str, Any], gasto_meta_cent: float) -> dict[str, Any]:
    """Deriva lucro, ROAS etc. a partir das somas de vendas e do gasto bruto do Meta (em centavos)."""
    # O PostgreSQL devolve SUM() como Decimal.
    v = {chave: float(valor) if isinstance(valor, Decimal) else valor for chave, valor in v.items()}
    gasto = gasto_meta_cent * (1 + conta.imposto_anuncios_pct / 100)
    impostos = v["liquido"] * conta.imposto_pct / 100
    custos = gasto + impostos + v["custo"]
    lucro = v["liquido"] - custos
    return {
        "vendas": int(v["aprovadas"]),
        "faturamento_bruto": reais(v["bruto"]),
        "faturamento_liquido": reais(v["liquido"]),
        "gasto": reais(gasto),
        "impostos": reais(impostos),
        "custo_produtos": reais(v["custo"]),
        "lucro": reais(lucro),
        "roas": _dividir(v["liquido"], gasto),
        "roi": _dividir(lucro, custos),
        "margem": _dividir(lucro, v["liquido"]),
        "cpa": reais(gasto / v["aprovadas"]) if v["aprovadas"] else None,
        "ticket_medio": reais(v["bruto"] / v["aprovadas"]) if v["aprovadas"] else None,
        "pendentes": int(v["pendentes"]),
        "pendentes_valor": reais(v["pendentes_valor"]),
        "reembolsadas": int(v["reembolsadas"]),
        "reembolsadas_valor": reais(v["reembolsadas_valor"]),
        "chargebacks": int(v["chargebacks"]),
        "chargebacks_valor": reais(v["chargebacks_valor"]),
        "recusadas": int(v["recusadas"]),
        "taxa_reembolso": _dividir(v["reembolsadas"] + v["chargebacks"],
                                   v["aprovadas"] + v["reembolsadas"] + v["chargebacks"]),
    }


def _somas_vendas(sessao: Session, conta: Conta, f: Filtros) -> dict[str, Any]:
    consulta = select(*_COLUNAS_VENDAS).select_from(Venda).outerjoin(Produto, Produto.id == Venda.produto_id)
    return dict(sessao.execute(_filtrar_vendas(consulta, conta.id, f)).mappings().one())


def _gasto_meta(sessao: Session, conta: Conta, f: Filtros) -> float:
    consulta = select(_GASTO).select_from(GastoDiario).join(ContaAnuncio,
                                                             ContaAnuncio.id == GastoDiario.conta_anuncio_id)
    return float(sessao.scalar(_filtrar_gastos(consulta, conta.id, f)) or 0)


def resumo(sessao: Session, conta: Conta, f: Filtros) -> dict[str, Any]:
    dados = _calcular(conta, _somas_vendas(sessao, conta, f), _gasto_meta(sessao, conta, f))

    sem_origem = _filtrar_vendas(
        select(func.count()).select_from(Venda).where(_APROVADA, Venda.utm_source.is_(None),
                                                      Venda.campanha_id.is_(None), Venda.visita_id.is_(None)),
        conta.id, f)
    dados["vendas_sem_origem"] = int(sessao.scalar(sem_origem) or 0)

    visitas = sessao.execute(select(func.count(), func.coalesce(func.sum(Visita.checkouts), 0)).where(
        Visita.conta_id == conta.id, Visita.dia >= f.inicio, Visita.dia <= f.fim)).one()
    dados["visitas"], dados["cliques_checkout"] = int(visitas[0]), int(visitas[1])
    return dados


def pagamentos(sessao: Session, conta: Conta, f: Filtros) -> list[dict[str, Any]]:
    """Por método: quantas foram geradas, quantas pagas e a taxa de conversão."""
    consulta = _filtrar_vendas(select(
        Venda.metodo_pagamento,
        func.count().label("geradas"),
        _soma_se(Venda.status.in_(PAGAS)).label("pagas"),
        _soma_se(_APROVADA).label("aprovadas"),
        _soma_se(_APROVADA, Venda.valor_liquido_cent).label("liquido"),
    ).group_by(Venda.metodo_pagamento), conta.id, f)
    linhas = {linha.metodo_pagamento: linha for linha in sessao.execute(consulta)}
    resultado = []
    for metodo in (MetodoPagamento.PIX, MetodoPagamento.CARTAO, MetodoPagamento.BOLETO, MetodoPagamento.OUTRO):
        linha = linhas.get(metodo)
        if linha is None and metodo == MetodoPagamento.OUTRO:
            continue
        geradas, pagas = (linha.geradas, linha.pagas) if linha else (0, 0)
        resultado.append({
            "metodo": metodo, "geradas": int(geradas), "pagas": int(pagas),
            "aprovadas": int(linha.aprovadas) if linha else 0,
            "faturamento_liquido": reais(linha.liquido if linha else 0),
            "conversao": _dividir(pagas, geradas),
        })
    return resultado


def serie_diaria(sessao: Session, conta: Conta, f: Filtros) -> list[dict[str, Any]]:
    vendas = sessao.execute(_filtrar_vendas(
        select(Venda.dia, *_COLUNAS_VENDAS).select_from(Venda)
        .outerjoin(Produto, Produto.id == Venda.produto_id).group_by(Venda.dia), conta.id, f)).mappings()
    por_dia = {linha["dia"]: dict(linha) for linha in vendas}
    gastos = sessao.execute(_filtrar_gastos(
        select(GastoDiario.dia, _GASTO).select_from(GastoDiario)
        .join(ContaAnuncio, ContaAnuncio.id == GastoDiario.conta_anuncio_id).group_by(GastoDiario.dia),
        conta.id, f)).all()
    gasto_por_dia = {dia: float(valor) for dia, valor in gastos}

    zeros = {coluna.name: 0 for coluna in _COLUNAS_VENDAS}
    resultado = []
    dia = f.inicio
    while dia <= f.fim:
        calculado = _calcular(conta, por_dia.get(dia, zeros), gasto_por_dia.get(dia, 0.0))
        resultado.append({"dia": dia.isoformat(), **{chave: calculado[chave] for chave in (
            "vendas", "faturamento_liquido", "gasto", "lucro", "roas")}})
        dia += timedelta(days=1)
    return resultado


def agrupar_vendas(sessao: Session, conta: Conta, f: Filtros, campo: str, limite: int = 12) -> list[dict[str, Any]]:
    """Vendas agrupadas por origem (utm_source), produto ou plataforma."""
    coluna = {"origem": Venda.utm_source, "produto": Venda.produto_nome, "plataforma": Venda.plataforma}[campo]
    consulta = _filtrar_vendas(
        select(coluna.label("chave"), *_COLUNAS_VENDAS).select_from(Venda)
        .outerjoin(Produto, Produto.id == Venda.produto_id).group_by(coluna), conta.id, f)
    linhas = []
    for linha in sessao.execute(consulta).mappings():
        calculado = _calcular(conta, linha, 0)
        if not calculado["vendas"] and not calculado["pendentes"]:
            continue
        linhas.append({"nome": linha["chave"], "vendas": calculado["vendas"],
                       "faturamento_liquido": calculado["faturamento_liquido"],
                       "pendentes": calculado["pendentes"]})
    linhas.sort(key=lambda linha: linha["faturamento_liquido"], reverse=True)
    return linhas[:limite]


def tabela_anuncios(sessao: Session, conta: Conta, f: Filtros, nivel: str,
                    pai: str | None = None) -> list[dict[str, Any]]:
    """Uma linha por campanha, conjunto ou anúncio: métricas do Meta + vendas atribuídas."""
    if nivel not in NIVEIS:
        raise ValueError(f"nível inválido: {nivel}")
    nivel_pai = {"conjunto": "campanha", "anuncio": "conjunto"}.get(nivel)

    id_gasto = getattr(GastoDiario, f"{nivel}_id")
    consulta_gastos = select(
        id_gasto.label("id"), func.max(getattr(GastoDiario, f"{nivel}_nome")).label("nome"),
        func.max(GastoDiario.campanha_id).label("campanha_id"), func.max(GastoDiario.conjunto_id).label("conjunto_id"),
        func.max(GastoDiario.conta_anuncio_id).label("conta_anuncio_id"),
        _GASTO.label("gasto"), func.sum(GastoDiario.impressoes).label("impressoes"),
        func.sum(GastoDiario.cliques_link).label("cliques_link"),
        func.sum(GastoDiario.visualizacoes_pagina).label("visualizacoes_pagina"),
        func.sum(GastoDiario.checkouts_iniciados).label("checkouts_iniciados"),
        func.sum(GastoDiario.compras_meta).label("compras_meta"),
    ).select_from(GastoDiario).join(ContaAnuncio, ContaAnuncio.id == GastoDiario.conta_anuncio_id).group_by(id_gasto)
    if pai and nivel_pai:
        consulta_gastos = consulta_gastos.where(getattr(GastoDiario, f"{nivel_pai}_id") == pai)
    gastos = {linha["id"]: dict(linha) for linha in
              sessao.execute(_filtrar_gastos(consulta_gastos, conta.id, f)).mappings()}

    id_venda, nome_venda = getattr(Venda, f"{nivel}_id"), getattr(Venda, f"{nivel}_nome")
    # Vendas com nome de campanha mas sem id (UTMs fora do padrão) viram linhas próprias, agrupadas pelo nome.
    chave_venda = func.coalesce(id_venda, "nome:" + func.coalesce(nome_venda, ""))
    consulta_vendas = select(chave_venda.label("chave"), func.max(id_venda).label("id"),
                             func.max(nome_venda).label("nome"), *_COLUNAS_VENDAS).select_from(Venda).outerjoin(
        Produto, Produto.id == Venda.produto_id).where(or_(id_venda.is_not(None), nome_venda.is_not(None)))
    if pai and nivel_pai:
        consulta_vendas = consulta_vendas.where(getattr(Venda, f"{nivel_pai}_id") == pai)
    vendas = {linha["chave"]: dict(linha) for linha in
              sessao.execute(_filtrar_vendas(consulta_vendas.group_by(chave_venda), conta.id, f)).mappings()}

    id_visita = getattr(Visita, f"{nivel}_id")
    consulta_visitas = select(id_visita, func.count(), func.coalesce(func.sum(Visita.checkouts), 0)).where(
        Visita.conta_id == conta.id, Visita.dia >= f.inicio, Visita.dia <= f.fim, id_visita.is_not(None))
    if pai and nivel_pai:
        consulta_visitas = consulta_visitas.where(getattr(Visita, f"{nivel_pai}_id") == pai)
    visitas = {chave: (int(total), int(checkouts)) for chave, total, checkouts in
               sessao.execute(consulta_visitas.group_by(id_visita))}

    chaves = list(gastos) + [chave for chave in vendas if chave not in gastos]
    ids_entidades = [chave for chave in chaves if not str(chave).startswith("nome:")]
    entidades = {e.id: e for e in sessao.scalars(select(EntidadeAnuncio).where(
        EntidadeAnuncio.conta_id == conta.id, EntidadeAnuncio.id.in_(ids_entidades)))} if ids_entidades else {}

    zeros = {coluna.name: 0 for coluna in _COLUNAS_VENDAS}
    linhas = []
    for chave in chaves:
        gasto = gastos.get(chave, {})
        venda = vendas.get(chave, zeros)
        entidade = entidades.get(chave)
        calculado = _calcular(conta, venda, float(gasto.get("gasto") or 0))
        impressoes = int(gasto.get("impressoes") or 0)
        cliques = int(gasto.get("cliques_link") or 0)
        gasto_reais = calculado["gasto"]
        n_visitas, n_checkouts = visitas.get(chave, (0, 0))
        linhas.append({
            "id": None if str(chave).startswith("nome:") else chave,
            "nome": (entidade.nome if entidade else None) or gasto.get("nome") or venda.get("nome") or "(sem nome)",
            "status": entidade.status if entidade else None,
            "status_efetivo": entidade.status_efetivo if entidade else None,
            "orcamento_diario": reais(entidade.orcamento_diario_cent) if entidade and entidade.orcamento_diario_cent
            else None,
            "orcamento_total": reais(entidade.orcamento_total_cent) if entidade and entidade.orcamento_total_cent
            else None,
            "rastreado_no_meta": bool(gasto) or entidade is not None,
            **calculado,
            "impressoes": impressoes,
            "cliques_link": cliques,
            "ctr": _dividir(cliques, impressoes),
            "cpc": round(gasto_reais / cliques, 2) if cliques else None,
            "cpm": round(gasto_reais / impressoes * 1000, 2) if impressoes else None,
            "visualizacoes_pagina": int(gasto.get("visualizacoes_pagina") or 0),
            "checkouts_iniciados": int(gasto.get("checkouts_iniciados") or 0),
            "compras_meta": int(gasto.get("compras_meta") or 0),
            "visitas": n_visitas,
            "cliques_checkout": n_checkouts,
        })
    linhas.sort(key=lambda linha: (linha["gasto"], linha["faturamento_liquido"]), reverse=True)
    return linhas


def listar_vendas(sessao: Session, conta: Conta, f: Filtros, status: str | None = None, busca: str | None = None,
                  pagina: int = 1, por_pagina: int = 50) -> dict[str, Any]:
    consulta = _filtrar_vendas(select(Venda), conta.id, f)
    if status:
        consulta = consulta.where(Venda.status == status)
    if busca:
        termo = f"%{busca.strip()}%"
        consulta = consulta.where(or_(Venda.cliente_email.ilike(termo), Venda.cliente_nome.ilike(termo),
                                      Venda.id_externo.ilike(termo), Venda.produto_nome.ilike(termo),
                                      Venda.campanha_nome.ilike(termo), Venda.anuncio_nome.ilike(termo)))
    total = sessao.scalar(select(func.count()).select_from(consulta.subquery())) or 0
    vendas = sessao.scalars(consulta.order_by(Venda.criada_em.desc(), Venda.id.desc())
                            .offset((pagina - 1) * por_pagina).limit(por_pagina)).all()
    return {"total": total, "pagina": pagina, "por_pagina": por_pagina, "itens": [{
        "id": v.id, "plataforma": v.plataforma, "id_externo": v.id_externo, "status": v.status,
        "metodo_pagamento": v.metodo_pagamento, "moeda": v.moeda,
        "valor_bruto": reais(v.valor_bruto_cent), "valor_liquido": reais(v.valor_liquido_cent),
        "produto": v.produto_nome, "cliente_nome": v.cliente_nome, "cliente_email": v.cliente_email,
        "criada_em": v.criada_em.isoformat(), "aprovada_em": v.aprovada_em.isoformat() if v.aprovada_em else None,
        "utm_source": v.utm_source, "utm_medium": v.utm_medium, "utm_campaign": v.utm_campaign,
        "utm_content": v.utm_content, "utm_term": v.utm_term, "src": v.src, "sck": v.sck,
        "campanha": v.campanha_nome, "conjunto": v.conjunto_nome, "anuncio": v.anuncio_nome,
        "rastreada_pelo_pixel": v.visita_id is not None,
        "capi_situacao": v.capi_situacao, "capi_erro": v.capi_erro,
    } for v in vendas]}

