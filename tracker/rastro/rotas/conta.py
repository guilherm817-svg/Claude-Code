"""API de conta: login, usuários, configurações, integrações de checkout, log de webhooks e Meta Ads."""

import threading
from datetime import date, timedelta
from typing import Literal
from zoneinfo import available_timezones

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from rastro.atribuicao import PADRAO_UTMS
from rastro.meta import ClienteMeta, ErroMeta
from rastro.modelos import (
    Conta, ContaAnuncio, Integracao, Produto, Usuario, Venda, WebhookRecebido, agora,
)
from rastro.plataformas import PLATAFORMAS
from rastro.rotas.dependencias import (
    COOKIE_SESSAO, conta_atual, sessao_db, usuario_admin, usuario_logado, usuario_opcional,
)
from rastro.rotas.publico import ip_cliente
from rastro.seguranca import DURACAO_SESSAO, conferir_senha, criar_cookie_sessao, gerar_hash_senha
from rastro.sincronizacao import (
    atualizar_contas_anuncio, hoje_no_fuso, sincronizar_conta, sincronizar_conta_anuncio,
)
from rastro.vendas import processar

rotas = APIRouter(prefix="/api")


def _url_publica(request: Request) -> str:
    return request.app.state.config.url_publica or str(request.base_url).rstrip("/")


def _mascarar(token: str | None) -> str | None:
    return f"••••{token[-6:]}" if token else None


def _iniciar_sessao(resposta: Response, request: Request, usuario: Usuario) -> None:
    valor = criar_cookie_sessao(usuario.id, usuario.versao_sessao, request.app.state.config.chave_secreta)
    resposta.set_cookie(COOKIE_SESSAO, valor, max_age=DURACAO_SESSAO, httponly=True, samesite="lax",
                        secure=_url_publica(request).startswith("https://"))


def _dados_usuario(usuario: Usuario) -> dict:
    return {"id": usuario.id, "nome": usuario.nome, "email": usuario.email, "admin": usuario.admin}


# ---------------------------------------------------------------- sessão


class Credenciais(BaseModel):
    email: str = Field(max_length=200)
    senha: str = Field(max_length=200)


class NovaConta(BaseModel):
    nome_conta: str = Field(min_length=1, max_length=120)
    nome: str = Field(min_length=1, max_length=120)
    email: str = Field(min_length=3, max_length=200)
    senha: str = Field(min_length=8, max_length=200)

    @field_validator("email")
    @classmethod
    def _email(cls, valor: str) -> str:
        valor = valor.strip().lower()
        if "@" not in valor:
            raise ValueError("E-mail inválido.")
        return valor


@rotas.get("/sessao")
def sessao_atual(request: Request, usuario: Usuario | None = Depends(usuario_opcional),
                 sessao: Session = Depends(sessao_db, scope="function")) -> dict:
    sem_usuarios = not sessao.scalar(select(func.count()).select_from(Usuario))
    if usuario is None:
        return {"logado": False, "precisa_configurar": sem_usuarios,
                "permite_cadastro": sem_usuarios or request.app.state.config.permitir_cadastro}
    conta = sessao.get(Conta, usuario.conta_id)
    return {"logado": True, "usuario": _dados_usuario(usuario),
            "conta": {"id": conta.id, "nome": conta.nome, "fuso": conta.fuso, "moeda": conta.moeda}}


@rotas.post("/configurar")
def configurar(dados: NovaConta, request: Request, resposta: Response, sessao: Session = Depends(sessao_db, scope="function")) -> dict:
    """Cria a primeira conta (ou uma nova, se RASTRO_PERMITIR_CADASTRO estiver ligado)."""
    tem_usuarios = sessao.scalar(select(func.count()).select_from(Usuario))
    if tem_usuarios and not request.app.state.config.permitir_cadastro:
        raise HTTPException(403, "O cadastro está fechado. Peça um acesso ao administrador.")
    if sessao.scalar(select(Usuario).where(Usuario.email == dados.email)):
        raise HTTPException(409, "Já existe um usuário com este e-mail.")
    conta = Conta(nome=dados.nome_conta.strip())
    sessao.add(conta)
    sessao.flush()
    usuario = Usuario(conta_id=conta.id, nome=dados.nome.strip(), email=dados.email,
                      senha_hash=gerar_hash_senha(dados.senha), admin=True, versao_sessao=1)
    sessao.add(usuario)
    sessao.flush()
    _iniciar_sessao(resposta, request, usuario)
    return {"ok": True}


@rotas.post("/entrar")
def entrar(dados: Credenciais, request: Request, resposta: Response, sessao: Session = Depends(sessao_db, scope="function")) -> dict:
    limite = request.app.state.limite_login
    chave = ip_cliente(request) or "?"
    if limite.bloqueado(chave):
        raise HTTPException(429, "Muitas tentativas. Espere 15 minutos e tente de novo.")
    usuario = sessao.scalar(select(Usuario).where(Usuario.email == dados.email.strip().lower()))
    if usuario is None or not conferir_senha(dados.senha, usuario.senha_hash):
        limite.falhou(chave)
        raise HTTPException(401, "E-mail ou senha incorretos.")
    limite.limpar(chave)
    _iniciar_sessao(resposta, request, usuario)
    return {"ok": True}


@rotas.post("/sair")
def sair(resposta: Response) -> dict:
    resposta.delete_cookie(COOKIE_SESSAO)
    return {"ok": True}


# ---------------------------------------------------------------- usuários


class NovoUsuario(NovaConta):
    nome_conta: str = ""
    admin: bool = False


class TrocaSenha(BaseModel):
    atual: str = Field(max_length=200)
    nova: str = Field(min_length=8, max_length=200)


@rotas.get("/usuarios")
def listar_usuarios(usuario: Usuario = Depends(usuario_logado), sessao: Session = Depends(sessao_db, scope="function")) -> list[dict]:
    usuarios = sessao.scalars(select(Usuario).where(Usuario.conta_id == usuario.conta_id).order_by(Usuario.nome))
    return [_dados_usuario(u) for u in usuarios]


@rotas.post("/usuarios")
def criar_usuario(dados: NovoUsuario, admin: Usuario = Depends(usuario_admin),
                  sessao: Session = Depends(sessao_db, scope="function")) -> dict:
    if sessao.scalar(select(Usuario).where(Usuario.email == dados.email)):
        raise HTTPException(409, "Já existe um usuário com este e-mail.")
    novo = Usuario(conta_id=admin.conta_id, nome=dados.nome.strip(), email=dados.email,
                   senha_hash=gerar_hash_senha(dados.senha), admin=dados.admin, versao_sessao=1)
    sessao.add(novo)
    sessao.flush()
    return _dados_usuario(novo)


@rotas.delete("/usuarios/{usuario_id}")
def remover_usuario(usuario_id: int, admin: Usuario = Depends(usuario_admin),
                    sessao: Session = Depends(sessao_db, scope="function")) -> dict:
    alvo = sessao.get(Usuario, usuario_id)
    if alvo is None or alvo.conta_id != admin.conta_id:
        raise HTTPException(404, "Usuário não encontrado.")
    if alvo.id == admin.id:
        raise HTTPException(400, "Você não pode remover a si mesmo.")
    sessao.delete(alvo)
    return {"ok": True}


@rotas.post("/usuarios/senha")
def trocar_senha(dados: TrocaSenha, request: Request, resposta: Response,
                 usuario: Usuario = Depends(usuario_logado)) -> dict:
    if not conferir_senha(dados.atual, usuario.senha_hash):
        raise HTTPException(400, "A senha atual está incorreta.")
    usuario.senha_hash = gerar_hash_senha(dados.nova)
    usuario.versao_sessao += 1  # derruba as outras sessões abertas
    _iniciar_sessao(resposta, request, usuario)
    return {"ok": True}


# ---------------------------------------------------------------- configurações e produtos


class Ajustes(BaseModel):
    nome: str | None = Field(None, min_length=1, max_length=120)
    fuso: str | None = None
    imposto_pct: float | None = Field(None, ge=0, le=100)
    imposto_anuncios_pct: float | None = Field(None, ge=0, le=100)
    capi_ativo: bool | None = None
    capi_pixel_id: str | None = Field(None, max_length=40)
    capi_token: str | None = Field(None, max_length=1000)  # "" apaga; ausente mantém
    capi_codigo_teste: str | None = Field(None, max_length=40)


@rotas.get("/configuracoes")
def ler_configuracoes(request: Request, conta: Conta = Depends(conta_atual)) -> dict:
    url = _url_publica(request)
    return {
        "nome": conta.nome, "fuso": conta.fuso, "moeda": conta.moeda,
        "imposto_pct": conta.imposto_pct, "imposto_anuncios_pct": conta.imposto_anuncios_pct,
        "capi_ativo": conta.capi_ativo, "capi_pixel_id": conta.capi_pixel_id,
        "capi_token": _mascarar(conta.capi_token), "capi_codigo_teste": conta.capi_codigo_teste,
        "url_publica": url,
        "url_publica_configurada": bool(request.app.state.config.url_publica),
        "chave_publica": conta.chave_publica,
        "script_pixel": f'<script src="{url}/p.js" data-conta="{conta.chave_publica}" async></script>',
        "padrao_utms": PADRAO_UTMS,
    }


@rotas.put("/configuracoes")
def salvar_configuracoes(dados: Ajustes, request: Request, admin: Usuario = Depends(usuario_admin),
                         sessao: Session = Depends(sessao_db, scope="function")) -> dict:
    conta = sessao.get(Conta, admin.conta_id)
    if dados.fuso is not None:
        if dados.fuso not in available_timezones():
            raise HTTPException(400, "Fuso horário inválido.")
        conta.fuso = dados.fuso
    for campo in ("nome", "imposto_pct", "imposto_anuncios_pct", "capi_ativo"):
        valor = getattr(dados, campo)
        if valor is not None:
            setattr(conta, campo, valor)
    for campo in ("capi_pixel_id", "capi_token", "capi_codigo_teste"):
        valor = getattr(dados, campo)
        if valor is not None:
            setattr(conta, campo, valor.strip() or None)
    if conta.capi_ativo and not (conta.capi_pixel_id and conta.capi_token):
        raise HTTPException(400, "Para ligar a API de Conversões, informe o ID do pixel e o token.")
    sessao.flush()
    return ler_configuracoes(request, conta)


class CustoProduto(BaseModel):
    custo: float = Field(ge=0, le=10_000_000)


@rotas.get("/produtos")
def listar_produtos(conta: Conta = Depends(conta_atual), sessao: Session = Depends(sessao_db, scope="function")) -> list[dict]:
    vendas = dict(sessao.execute(select(Venda.produto_id, func.count()).where(Venda.conta_id == conta.id)
                                 .group_by(Venda.produto_id)).all())
    produtos = sessao.scalars(select(Produto).where(Produto.conta_id == conta.id).order_by(Produto.nome))
    return [{"id": p.id, "nome": p.nome, "plataforma": p.plataforma, "id_externo": p.id_externo,
             "custo": p.custo_cent / 100, "vendas": vendas.get(p.id, 0)} for p in produtos]


@rotas.patch("/produtos/{produto_id}")
def alterar_produto(produto_id: int, dados: CustoProduto, admin: Usuario = Depends(usuario_admin),
                    sessao: Session = Depends(sessao_db, scope="function")) -> dict:
    produto = sessao.get(Produto, produto_id)
    if produto is None or produto.conta_id != admin.conta_id:
        raise HTTPException(404, "Produto não encontrado.")
    produto.custo_cent = round(dados.custo * 100)
    return {"ok": True}


# ---------------------------------------------------------------- integrações de checkout


class DadosIntegracao(BaseModel):
    plataforma: str | None = None
    nome: str | None = Field(None, min_length=1, max_length=120)
    segredo: str | None = Field(None, max_length=200)
    papel: Literal["produtor", "coprodutor", "afiliado"] | None = None
    ativo: bool | None = None


def _dados_integracao(request: Request, integracao: Integracao, totais: dict) -> dict:
    return {
        "id": integracao.id, "plataforma": integracao.plataforma,
        "plataforma_nome": PLATAFORMAS[integracao.plataforma].NOME, "nome": integracao.nome,
        "url": f"{_url_publica(request)}/webhook/{integracao.token}",
        "tem_segredo": bool(integracao.segredo), "papel": integracao.papel, "ativo": integracao.ativo,
        "ultimo_recebimento": integracao.ultimo_recebimento,
        "recebidos": totais.get((integracao.id, "processado"), 0) + totais.get((integracao.id, "ignorado"), 0)
        + totais.get((integracao.id, "erro"), 0),
        "erros": totais.get((integracao.id, "erro"), 0),
    }


def _totais_webhooks(sessao: Session, conta_id: int) -> dict:
    linhas = sessao.execute(select(WebhookRecebido.integracao_id, WebhookRecebido.situacao, func.count())
                            .where(WebhookRecebido.conta_id == conta_id)
                            .group_by(WebhookRecebido.integracao_id, WebhookRecebido.situacao)).all()
    return {(integracao_id, situacao): total for integracao_id, situacao, total in linhas}


@rotas.get("/integracoes")
def listar_integracoes(request: Request, conta: Conta = Depends(conta_atual),
                       sessao: Session = Depends(sessao_db, scope="function")) -> dict:
    integracoes = sessao.scalars(select(Integracao).where(Integracao.conta_id == conta.id).order_by(Integracao.id))
    totais = _totais_webhooks(sessao, conta.id)
    return {
        "integracoes": [_dados_integracao(request, i, totais) for i in integracoes],
        "plataformas": [{"id": chave, "nome": modulo.NOME} for chave, modulo in PLATAFORMAS.items()],
    }


@rotas.post("/integracoes")
def criar_integracao(dados: DadosIntegracao, request: Request, admin: Usuario = Depends(usuario_admin),
                     sessao: Session = Depends(sessao_db, scope="function")) -> dict:
    if dados.plataforma not in PLATAFORMAS:
        raise HTTPException(400, "Plataforma inválida.")
    integracao = Integracao(conta_id=admin.conta_id, plataforma=dados.plataforma,
                            nome=(dados.nome or PLATAFORMAS[dados.plataforma].NOME).strip(),
                            segredo=(dados.segredo or "").strip() or None, papel=dados.papel or "produtor",
                            ativo=True)
    sessao.add(integracao)
    sessao.flush()
    return _dados_integracao(request, integracao, {})


@rotas.patch("/integracoes/{integracao_id}")
def alterar_integracao(integracao_id: int, dados: DadosIntegracao, request: Request,
                       admin: Usuario = Depends(usuario_admin), sessao: Session = Depends(sessao_db, scope="function")) -> dict:
    integracao = sessao.get(Integracao, integracao_id)
    if integracao is None or integracao.conta_id != admin.conta_id:
        raise HTTPException(404, "Integração não encontrada.")
    if dados.nome is not None:
        integracao.nome = dados.nome.strip()
    if dados.segredo is not None:
        integracao.segredo = dados.segredo.strip() or None
    if dados.papel is not None:
        integracao.papel = dados.papel
    if dados.ativo is not None:
        integracao.ativo = dados.ativo
    sessao.flush()
    return _dados_integracao(request, integracao, _totais_webhooks(sessao, admin.conta_id))


@rotas.delete("/integracoes/{integracao_id}")
def remover_integracao(integracao_id: int, admin: Usuario = Depends(usuario_admin),
                       sessao: Session = Depends(sessao_db, scope="function")) -> dict:
    integracao = sessao.get(Integracao, integracao_id)
    if integracao is None or integracao.conta_id != admin.conta_id:
        raise HTTPException(404, "Integração não encontrada.")
    sessao.delete(integracao)  # as vendas já recebidas continuam no painel
    return {"ok": True}


# ---------------------------------------------------------------- log de webhooks


@rotas.get("/webhooks")
def listar_webhooks(integracao_id: int | None = None, situacao: str | None = None, pagina: int = Query(1, ge=1),
                    conta: Conta = Depends(conta_atual), sessao: Session = Depends(sessao_db, scope="function")) -> dict:
    consulta = select(WebhookRecebido).where(WebhookRecebido.conta_id == conta.id)
    if integracao_id:
        consulta = consulta.where(WebhookRecebido.integracao_id == integracao_id)
    if situacao:
        consulta = consulta.where(WebhookRecebido.situacao == situacao)
    total = sessao.scalar(select(func.count()).select_from(consulta.subquery()))
    itens = sessao.scalars(consulta.order_by(WebhookRecebido.id.desc()).offset((pagina - 1) * 50).limit(50))
    nomes = dict(sessao.execute(select(Integracao.id, Integracao.nome).where(Integracao.conta_id == conta.id)).all())
    return {"total": total, "pagina": pagina, "itens": [{
        "id": w.id, "integracao": nomes.get(w.integracao_id), "recebido_em": w.recebido_em,
        "situacao": w.situacao, "mensagem": w.mensagem, "corpo": w.corpo[:20000],
    } for w in itens]}


def _reprocessar(sessao: Session, registro: WebhookRecebido) -> None:
    integracao = sessao.get(Integracao, registro.integracao_id)
    processar(sessao, integracao, registro)


@rotas.post("/webhooks/{webhook_id}/reprocessar")
def reprocessar(webhook_id: int, admin: Usuario = Depends(usuario_admin), sessao: Session = Depends(sessao_db, scope="function")) -> dict:
    registro = sessao.get(WebhookRecebido, webhook_id)
    if registro is None or registro.conta_id != admin.conta_id:
        raise HTTPException(404, "Webhook não encontrado.")
    _reprocessar(sessao, registro)
    return {"situacao": registro.situacao, "mensagem": registro.mensagem}


@rotas.post("/webhooks/reprocessar-erros")
def reprocessar_erros(admin: Usuario = Depends(usuario_admin), sessao: Session = Depends(sessao_db, scope="function")) -> dict:
    registros = sessao.scalars(select(WebhookRecebido).where(WebhookRecebido.conta_id == admin.conta_id,
                                                             WebhookRecebido.situacao == "erro")
                               .order_by(WebhookRecebido.id).limit(5000)).all()
    for registro in registros:
        _reprocessar(sessao, registro)
    return {"reprocessados": len(registros),
            "ainda_com_erro": sum(1 for r in registros if r.situacao == "erro")}


# ---------------------------------------------------------------- Meta Ads


class TokenMeta(BaseModel):
    token: str = Field(min_length=20, max_length=1000)


class AjusteContaAnuncio(BaseModel):
    ativo: bool | None = None
    cotacao: float | None = Field(None, gt=0, le=10_000)


class PedidoSincronizacao(BaseModel):
    inicio: date | None = None
    fim: date | None = None


def _dados_meta(sessao: Session, conta: Conta, request: Request) -> dict:
    contas = sessao.scalars(select(ContaAnuncio).where(ContaAnuncio.conta_id == conta.id)
                            .order_by(ContaAnuncio.nome)).all()
    return {
        "conectado": bool(conta.meta_token), "usuario": conta.meta_usuario, "token": _mascarar(conta.meta_token),
        "sincronizando": conta.id in request.app.state.sincronizando,
        "contas_anuncio": [{
            "id": c.id, "meta_id": c.meta_id, "nome": c.nome, "moeda": c.moeda, "fuso": c.fuso, "ativo": c.ativo,
            "cotacao": c.cotacao, "ultima_sincronizacao": c.ultima_sincronizacao, "erro": c.erro,
        } for c in contas],
    }


@rotas.get("/meta")
def ler_meta(request: Request, conta: Conta = Depends(conta_atual), sessao: Session = Depends(sessao_db, scope="function")) -> dict:
    return _dados_meta(sessao, conta, request)


@rotas.post("/meta/token")
def conectar_meta(dados: TokenMeta, request: Request, admin: Usuario = Depends(usuario_admin),
                  sessao: Session = Depends(sessao_db, scope="function")) -> dict:
    conta = sessao.get(Conta, admin.conta_id)
    cliente = ClienteMeta(dados.token.strip(), request.app.state.config.meta_versao_api)
    try:
        eu = cliente.eu()
        conta.meta_token = dados.token.strip()
        conta.meta_usuario = eu.get("name") or eu.get("id")
        atualizar_contas_anuncio(sessao, conta, cliente)
    except ErroMeta as erro:
        raise HTTPException(400, str(erro)) from None
    return _dados_meta(sessao, conta, request)


@rotas.delete("/meta/token")
def desconectar_meta(request: Request, admin: Usuario = Depends(usuario_admin),
                     sessao: Session = Depends(sessao_db, scope="function")) -> dict:
    conta = sessao.get(Conta, admin.conta_id)
    conta.meta_token = None
    conta.meta_usuario = None
    sessao.execute(update(ContaAnuncio).where(ContaAnuncio.conta_id == conta.id).values(ativo=False))
    return _dados_meta(sessao, conta, request)


@rotas.post("/meta/contas/atualizar")
def atualizar_lista_contas(request: Request, admin: Usuario = Depends(usuario_admin),
                           sessao: Session = Depends(sessao_db, scope="function")) -> dict:
    conta = sessao.get(Conta, admin.conta_id)
    if not conta.meta_token:
        raise HTTPException(400, "Conecte o Meta Ads primeiro.")
    try:
        atualizar_contas_anuncio(sessao, conta, ClienteMeta(conta.meta_token,
                                                            request.app.state.config.meta_versao_api))
    except ErroMeta as erro:
        raise HTTPException(400, str(erro)) from None
    return _dados_meta(sessao, conta, request)


@rotas.patch("/meta/contas/{conta_anuncio_id}")
def ajustar_conta_anuncio(conta_anuncio_id: int, dados: AjusteContaAnuncio, request: Request,
                          admin: Usuario = Depends(usuario_admin), sessao: Session = Depends(sessao_db, scope="function")) -> dict:
    conta_anuncio = sessao.get(ContaAnuncio, conta_anuncio_id)
    if conta_anuncio is None or conta_anuncio.conta_id != admin.conta_id:
        raise HTTPException(404, "Conta de anúncio não encontrada.")
    ativou = dados.ativo and not conta_anuncio.ativo
    if dados.ativo is not None:
        conta_anuncio.ativo = dados.ativo
    if dados.cotacao is not None:
        conta_anuncio.cotacao = dados.cotacao
    sessao.commit()
    conta = sessao.get(Conta, admin.conta_id)
    if ativou and conta.meta_token:
        # Primeira ativação: traz os últimos 30 dias em segundo plano.
        _sincronizar_em_segundo_plano(request, conta.id, conta_anuncio.id, dias=30)
    return _dados_meta(sessao, conta, request)


def _sincronizar_em_segundo_plano(request: Request, conta_id: int, conta_anuncio_id: int | None = None,
                                  inicio: date | None = None, fim: date | None = None, dias: int | None = None) -> None:
    app = request.app
    if conta_id in app.state.sincronizando:
        return
    app.state.sincronizando.add(conta_id)

    def tarefa() -> None:
        try:
            with app.state.banco.sessao() as sessao:
                conta = sessao.get(Conta, conta_id)
                versao = app.state.config.meta_versao_api
                if conta_anuncio_id is not None:
                    fim_local = fim or hoje_no_fuso(conta.fuso)
                    inicio_local = inicio or fim_local - timedelta(days=(dias or 2) - 1)
                    sincronizar_conta_anuncio(sessao, sessao.get(ContaAnuncio, conta_anuncio_id),
                                              ClienteMeta(conta.meta_token, versao), inicio_local, fim_local)
                else:
                    sincronizar_conta(sessao, conta, versao, inicio, fim)
        finally:
            app.state.sincronizando.discard(conta_id)

    threading.Thread(target=tarefa, daemon=True).start()


@rotas.post("/meta/sincronizar")
def sincronizar_agora(dados: PedidoSincronizacao, request: Request, conta: Conta = Depends(conta_atual),
                      sessao: Session = Depends(sessao_db, scope="function")) -> dict:
    if not conta.meta_token:
        raise HTTPException(400, "Conecte o Meta Ads em Integrações primeiro.")
    if dados.inicio and dados.fim and (dados.fim - dados.inicio).days > 400:
        raise HTTPException(400, "Sincronize no máximo 400 dias por vez.")
    _sincronizar_em_segundo_plano(request, conta.id, inicio=dados.inicio, fim=dados.fim)
    return {"ok": True, "iniciado_em": agora()}


@rotas.post("/capi/reenviar")
def reenviar_capi(request: Request, admin: Usuario = Depends(usuario_admin),
                  sessao: Session = Depends(sessao_db, scope="function")) -> dict:
    """Coloca de volta na fila as vendas cujo envio para a API de Conversões falhou (até 7 dias) e envia."""
    resultado = sessao.execute(update(Venda).where(
        Venda.conta_id == admin.conta_id, Venda.capi_situacao == "erro",
        Venda.criada_em >= agora() - timedelta(days=7)).values(capi_situacao="pendente", capi_erro=None))
    sessao.commit()
    _sincronizar_em_segundo_plano(request, admin.conta_id)
    return {"reenfileiradas": resultado.rowcount}
