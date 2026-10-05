"""Liga cada venda à visita rastreada e ao anúncio do Meta que a trouxe.

Padrão de UTMs recomendado nos anúncios (o mesmo usado no mercado):
utm_source=FB&utm_campaign={{campaign.name}}|{{campaign.id}}&utm_medium={{adset.name}}|{{adset.id}}
&utm_content={{ad.name}}|{{ad.id}}&utm_term={{placement}}
"""

import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from rastro.modelos import EntidadeAnuncio, Venda, Visita

PADRAO_UTMS = (
    "utm_source=FB&utm_campaign={{campaign.name}}|{{campaign.id}}&utm_medium={{adset.name}}|{{adset.id}}"
    "&utm_content={{ad.name}}|{{ad.id}}&utm_term={{placement}}"
)
ID_VISITA = re.compile(r"^tk[0-9a-z]{16,30}$")
_ID_META = re.compile(r"^\d{6,25}$")
FONTES_META = {"fb", "facebook", "ig", "instagram", "meta", "an", "audience_network", "messenger"}
CAMPOS_UTM = ("utm_source", "utm_medium", "utm_campaign", "utm_content", "utm_term")


def separar_nome_id(valor: str | None) -> tuple[str | None, str | None]:
    """"Campanha X|1202" → ("Campanha X", "1202"); "1202" → (None, "1202"); "Campanha X" → ("Campanha X", None)."""
    if not valor:
        return None, None
    valor = valor.strip()
    if "|" in valor:
        nome, possivel_id = valor.rsplit("|", 1)
        if _ID_META.match(possivel_id.strip()):
            return nome.strip() or None, possivel_id.strip()
    if _ID_META.match(valor):
        return None, valor
    return valor, None


def niveis_meta(utms: dict[str, str | None]) -> dict[str, tuple[str | None, str | None]]:
    """Extrai (nome, id) de campanha, conjunto e anúncio das UTMs."""
    fonte = (utms.get("utm_source") or "").strip().lower()
    eh_meta = fonte in FONTES_META
    resultado = {"campanha": separar_nome_id(utms.get("utm_campaign"))}
    for nivel, campo in (("conjunto", "utm_medium"), ("anuncio", "utm_content")):
        nome, id_ = separar_nome_id(utms.get(campo))
        # utm_medium=cpc ou utm_content=video1 em tráfego que não é do Meta não são conjunto/anúncio.
        resultado[nivel] = (nome, id_) if (id_ or eh_meta) else (None, None)
    return resultado


def achar_id_visita(rastreio: dict[str, str | None]) -> str | None:
    for campo in ("sck", "src", "xcod", "utm_term", "utm_content"):
        valor = (rastreio.get(campo) or "").strip().lower()
        if ID_VISITA.match(valor):
            return valor
    return None


def _completar_com_entidades(sessao: Session, conta_id: int, nivel: str, nome: str | None,
                             id_: str | None) -> tuple[str | None, str | None]:
    if id_ and not nome:
        entidade = sessao.get(EntidadeAnuncio, (conta_id, id_))
        return (entidade.nome if entidade else None), id_
    if nome and not id_:
        ids = sessao.scalars(
            select(EntidadeAnuncio.id).where(EntidadeAnuncio.conta_id == conta_id, EntidadeAnuncio.nivel == nivel,
                                             EntidadeAnuncio.nome == nome).limit(2)
        ).all()
        if len(ids) == 1:  # nome repetido em duas campanhas: melhor não adivinhar
            return nome, ids[0]
    return nome, id_


def atribuir(sessao: Session, venda: Venda, rastreio: dict[str, str | None]) -> None:
    """Preenche UTMs, visita e campanha/conjunto/anúncio da venda."""
    venda.src = rastreio.get("src") or venda.src
    venda.sck = rastreio.get("sck") or venda.sck

    id_visita = achar_id_visita(rastreio) or venda.visita_id
    visita = sessao.get(Visita, id_visita) if id_visita else None
    if visita is not None and visita.conta_id != venda.conta_id:
        visita = None
    if visita is not None:
        venda.visita_id = visita.id

    for campo in CAMPOS_UTM:
        valor = rastreio.get(campo)
        if valor and ID_VISITA.match(valor.strip().lower()):
            valor = None  # o id da visita no utm_term não é uma UTM de verdade
        if not valor and visita is not None:
            valor = getattr(visita, campo)
        setattr(venda, campo, valor or getattr(venda, campo))

    utms = {campo: getattr(venda, campo) for campo in CAMPOS_UTM}
    for nivel, (nome, id_) in niveis_meta(utms).items():
        nome, id_ = _completar_com_entidades(sessao, venda.conta_id, nivel, nome, id_)
        setattr(venda, f"{nivel}_nome", nome)
        setattr(venda, f"{nivel}_id", id_)
