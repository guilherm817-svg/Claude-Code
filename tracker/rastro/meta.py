"""Cliente da Graph API do Meta: contas de anúncio, insights, status/orçamento e API de Conversões."""

import json
from collections.abc import Iterator
from datetime import date
from typing import Any

import httpx

URL_BASE = "https://graph.facebook.com"

CAMPOS_INSIGHTS = ",".join([
    "campaign_id", "campaign_name", "adset_id", "adset_name", "ad_id", "ad_name", "spend", "impressions",
    "clicks", "inline_link_clicks", "actions", "date_start",
])
CAMPOS_ENTIDADE = {
    "campanha": ("campaigns", "id,name,status,effective_status,daily_budget,lifetime_budget"),
    "conjunto": ("adsets", "id,name,status,effective_status,daily_budget,lifetime_budget,campaign_id"),
    "anuncio": ("ads", "id,name,status,effective_status,campaign_id,adset_id"),
}
# Primeiro tipo de ação encontrado vence (o Meta muda os nomes conforme o tipo de otimização).
ACOES = {
    "visualizacoes_pagina": ("landing_page_view", "omni_landing_page_view"),
    "checkouts_iniciados": ("initiate_checkout", "offsite_conversion.fb_pixel_initiate_checkout",
                            "omni_initiated_checkout"),
    "compras_meta": ("purchase", "offsite_conversion.fb_pixel_purchase", "omni_purchase"),
}


class ErroMeta(Exception):
    def __init__(self, mensagem: str, codigo: int | None = None):
        super().__init__(mensagem)
        self.codigo = codigo


def _explicar(erro: dict[str, Any]) -> ErroMeta:
    codigo = erro.get("code")
    mensagem = erro.get("error_user_msg") or erro.get("message") or "Erro desconhecido na API do Meta."
    if codigo == 190:
        mensagem = f"Token do Meta inválido ou expirado. Gere um novo token. ({mensagem})"
    elif codigo in (4, 17, 32, 613, 80004):
        mensagem = f"Limite de chamadas da API do Meta atingido; tenta de novo em alguns minutos. ({mensagem})"
    elif codigo in (10, 200, 294):
        mensagem = f"O token não tem a permissão necessária (ads_read / ads_management). ({mensagem})"
    return ErroMeta(mensagem, codigo)


def valor_acao(acoes: list[dict[str, Any]] | None, tipos: tuple[str, ...]) -> int:
    por_tipo = {a.get("action_type"): a.get("value") for a in acoes or []}
    for tipo in tipos:
        if tipo in por_tipo:
            try:
                return int(float(por_tipo[tipo]))
            except (TypeError, ValueError):
                return 0
    return 0


def para_centavos(valor: Any) -> int:
    try:
        return round(float(valor) * 100)
    except (TypeError, ValueError):
        return 0


class ClienteMeta:
    def __init__(self, token: str, versao: str = "v25.0", http: httpx.Client | None = None):
        self.token = token
        self.versao = versao
        self.http = http or httpx.Client(timeout=60)

    def _url(self, caminho: str) -> str:
        return f"{URL_BASE}/{self.versao}/{caminho.lstrip('/')}"

    def _tratar(self, resposta: httpx.Response) -> dict[str, Any]:
        try:
            dados = resposta.json()
        except ValueError:
            raise ErroMeta(f"Resposta inesperada do Meta (HTTP {resposta.status_code}).") from None
        if isinstance(dados, dict) and "error" in dados:
            raise _explicar(dados["error"])
        if resposta.status_code >= 400:
            raise ErroMeta(f"Erro HTTP {resposta.status_code} na API do Meta.")
        return dados

    def get(self, caminho: str, **params: Any) -> dict[str, Any]:
        params["access_token"] = self.token
        return self._tratar(self.http.get(self._url(caminho), params=params))

    def post(self, caminho: str, **dados: Any) -> dict[str, Any]:
        dados["access_token"] = self.token
        return self._tratar(self.http.post(self._url(caminho), data=dados))

    def paginar(self, caminho: str, **params: Any) -> Iterator[dict[str, Any]]:
        pagina = self.get(caminho, **params)
        while True:
            yield from pagina.get("data", [])
            proxima = (pagina.get("paging") or {}).get("next")
            if not proxima:
                return
            # O "next" já traz o token e todos os parâmetros.
            pagina = self._tratar(self.http.get(proxima))

    def eu(self) -> dict[str, Any]:
        return self.get("me", fields="id,name")

    def contas_anuncio(self) -> list[dict[str, Any]]:
        return list(self.paginar("me/adaccounts", fields="id,name,currency,timezone_name,account_status",
                                 limit=200))

    def insights(self, conta_meta_id: str, inicio: date, fim: date) -> Iterator[dict[str, Any]]:
        """Uma linha por anúncio por dia, já convertida para os campos de GastoDiario."""
        linhas = self.paginar(
            f"{conta_meta_id}/insights", level="ad", time_increment=1, fields=CAMPOS_INSIGHTS, limit=500,
            time_range=json.dumps({"since": inicio.isoformat(), "until": fim.isoformat()}),
        )
        for linha in linhas:
            yield {
                "dia": date.fromisoformat(linha["date_start"]),
                "campanha_id": linha.get("campaign_id") or "",
                "campanha_nome": linha.get("campaign_name") or "",
                "conjunto_id": linha.get("adset_id") or "",
                "conjunto_nome": linha.get("adset_name") or "",
                "anuncio_id": linha.get("ad_id") or "",
                "anuncio_nome": linha.get("ad_name") or "",
                "gasto_cent": para_centavos(linha.get("spend")),
                "impressoes": int(linha.get("impressions") or 0),
                "cliques": int(linha.get("clicks") or 0),
                "cliques_link": int(linha.get("inline_link_clicks") or 0),
                **{campo: valor_acao(linha.get("actions"), tipos) for campo, tipos in ACOES.items()},
            }

    def entidades(self, conta_meta_id: str, nivel: str) -> Iterator[dict[str, Any]]:
        borda, campos = CAMPOS_ENTIDADE[nivel]
        yield from self.paginar(f"{conta_meta_id}/{borda}", fields=campos, limit=500)

    def alterar_status(self, objeto_id: str, status: str) -> None:
        self.post(objeto_id, status=status)

    def alterar_orcamento_diario(self, objeto_id: str, centavos: int) -> None:
        self.post(objeto_id, daily_budget=str(centavos))

    def enviar_eventos(self, pixel_id: str, eventos: list[dict[str, Any]],
                       codigo_teste: str | None = None) -> dict[str, Any]:
        dados: dict[str, Any] = {"data": json.dumps(eventos)}
        if codigo_teste:
            dados["test_event_code"] = codigo_teste
        return self.post(f"{pixel_id}/events", **dados)
