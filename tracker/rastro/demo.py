"""Cria uma operação de demonstração com 30 dias de gastos e vendas fictícias.

    python -m rastro.demo            (login: demo@rastro.local / demo12345)
"""

import random
import unicodedata
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import select

from rastro.config import carregar
from rastro.db import Banco
from rastro.modelos import (
    Conta, ContaAnuncio, EntidadeAnuncio, GastoDiario, Integracao, MetodoPagamento, Produto, StatusVenda, Usuario,
    Venda,
)
from rastro.seguranca import gerar_hash_senha

EMAIL = "demo@rastro.local"
SENHA = "demo12345"
CAMPANHAS = [
    ("[VENDAS] Curso Tráfego · CBO · Público Aberto", 1.0),
    ("[VENDAS] Curso Tráfego · Remarketing 30D", 1.6),
    ("[TESTE] Criativos Novos · ABO", 0.45),
]
NOMES = ["Ana Souza", "Bruno Lima", "Carla Dias", "Diego Alves", "Elisa Rocha", "Fábio Nunes", "Gabi Costa", "Hugo Melo"]


def criar_demo(banco: Banco, semente: int = 7) -> None:
    aleatorio = random.Random(semente)
    with banco.sessao() as sessao:
        if sessao.scalar(select(Usuario).where(Usuario.email == EMAIL)):
            print(f"A demonstração já existe. Entre com {EMAIL} / {SENHA}.")
            return
        conta = Conta(nome="Operação Demo", imposto_pct=6.0, imposto_anuncios_pct=12.15)
        sessao.add(conta)
        sessao.flush()
        sessao.add(Usuario(conta_id=conta.id, nome="Demo", email=EMAIL, senha_hash=gerar_hash_senha(SENHA),
                           admin=True, versao_sessao=1))
        sessao.add(Integracao(conta_id=conta.id, plataforma="kiwify", nome="Kiwify — Curso de Tráfego", papel="produtor"))
        conta_anuncio = ContaAnuncio(conta_id=conta.id, meta_id="act_1029384756", nome="BM Principal", moeda="BRL",
                                     fuso="America/Sao_Paulo", ativo=True, cotacao=1.0,
                                     ultima_sincronizacao=datetime.now(timezone.utc))
        sessao.add(conta_anuncio)
        produtos = [Produto(conta_id=conta.id, plataforma="kiwify", id_externo="curso", nome="Curso de Tráfego Pago",
                            custo_cent=0),
                    Produto(conta_id=conta.id, plataforma="kiwify", id_externo="bump", nome="Pack de Criativos (bump)",
                            custo_cent=300)]
        sessao.add_all(produtos)
        sessao.flush()

        anuncios = []
        for c, (nome_campanha, qualidade) in enumerate(CAMPANHAS):
            id_campanha = f"12021000000000{c}000"
            sessao.add(EntidadeAnuncio(conta_id=conta.id, id=id_campanha, conta_anuncio_id=conta_anuncio.id,
                                       nivel="campanha", nome=nome_campanha, status="PAUSED" if c == 2 else "ACTIVE",
                                       status_efetivo="PAUSED" if c == 2 else "ACTIVE",
                                       orcamento_diario_cent=[30000, 12000, 8000][c], campanha_id=id_campanha))
            for s in range(2):
                id_conjunto = f"12021000000000{c}1{s}0"
                nome_conjunto = ["Aberto · 25-55 · BR", "Interesses · Marketing Digital"][s]
                sessao.add(EntidadeAnuncio(conta_id=conta.id, id=id_conjunto, conta_anuncio_id=conta_anuncio.id,
                                           nivel="conjunto", nome=nome_conjunto, status="ACTIVE",
                                           status_efetivo="CAMPAIGN_PAUSED" if c == 2 else "ACTIVE",
                                           campanha_id=id_campanha, conjunto_id=id_conjunto))
                for a in range(3):
                    id_anuncio = f"12021000000000{c}2{s}{a}"
                    nome_anuncio = ["VSL 01 · Gancho dor", "Depoimento Carla", "Carrossel 5 erros"][a]
                    sessao.add(EntidadeAnuncio(conta_id=conta.id, id=id_anuncio, conta_anuncio_id=conta_anuncio.id,
                                               nivel="anuncio", nome=nome_anuncio, status="ACTIVE",
                                               status_efetivo="CAMPAIGN_PAUSED" if c == 2 else "ACTIVE",
                                               campanha_id=id_campanha, conjunto_id=id_conjunto))
                    anuncios.append((nome_campanha, id_campanha, nome_conjunto, id_conjunto, nome_anuncio, id_anuncio,
                                     qualidade * [1.25, 0.95, 0.7][a]))

        fuso = ZoneInfo(conta.fuso)
        hoje = datetime.now(fuso).date()
        numero_pedido = 1000
        for dias_atras in range(29, -1, -1):
            dia = hoje - timedelta(days=dias_atras)
            fracao_dia = datetime.now(fuso).hour / 24 if dias_atras == 0 else 1
            for (campanha, id_c, conjunto, id_s, anuncio, id_a, qualidade) in anuncios:
                gasto = aleatorio.uniform(2500, 9000) * fracao_dia * (0.4 if "TESTE" in campanha else 1)
                impressoes = int(gasto / 100 / aleatorio.uniform(18, 32) * 1000)
                cliques = int(impressoes * aleatorio.uniform(0.008, 0.02))
                sessao.add(GastoDiario(
                    conta_id=conta.id, conta_anuncio_id=conta_anuncio.id, dia=dia, campanha_id=id_c,
                    campanha_nome=campanha, conjunto_id=id_s, conjunto_nome=conjunto, anuncio_id=id_a,
                    anuncio_nome=anuncio, gasto_cent=int(gasto), impressoes=impressoes, cliques=int(cliques * 1.4),
                    cliques_link=cliques, visualizacoes_pagina=int(cliques * 0.75),
                    checkouts_iniciados=int(cliques * aleatorio.uniform(0.05, 0.1)), compras_meta=0))
                vendas_esperadas = gasto / 100 / 97 * qualidade * 1.9
                for _ in range(_poisson(aleatorio, vendas_esperadas)):
                    numero_pedido += 1
                    metodo = aleatorio.choices([MetodoPagamento.PIX, MetodoPagamento.CARTAO, MetodoPagamento.BOLETO],
                                               [0.55, 0.38, 0.07])[0]
                    chance_paga = {"pix": 0.82, "cartao": 0.9, "boleto": 0.35}[metodo]
                    status = StatusVenda.APROVADA if aleatorio.random() < chance_paga else (
                        StatusVenda.RECUSADA if metodo == "cartao" else StatusVenda.PENDENTE)
                    if status == StatusVenda.APROVADA and aleatorio.random() < 0.04:
                        status = StatusVenda.REEMBOLSADA
                    if status == StatusVenda.PENDENTE and dias_atras > 3:
                        status = StatusVenda.CANCELADA
                    produto = produtos[0] if aleatorio.random() < 0.8 else produtos[1]
                    bruto = 19700 if produto is produtos[0] else 2700
                    momento = datetime.combine(dia, time(aleatorio.randint(7, 23), aleatorio.randint(0, 59)), fuso)
                    if momento > datetime.now(fuso):
                        momento = datetime.now(fuso) - timedelta(minutes=aleatorio.randint(1, 50))
                    nome = aleatorio.choice(NOMES)
                    sessao.add(Venda(
                        conta_id=conta.id, plataforma="kiwify", id_externo=f"KW{numero_pedido}", status=status,
                        metodo_pagamento=metodo, moeda="BRL", valor_bruto_cent=bruto,
                        valor_liquido_cent=int(bruto * 0.9101), produto_id=produto.id, produto_nome=produto.nome,
                        cliente_nome=nome, cliente_email=_email(nome),
                        criada_em=momento, aprovada_em=momento if status in (StatusVenda.APROVADA,
                                                                             StatusVenda.REEMBOLSADA) else None,
                        dia=dia, utm_source="FB", utm_campaign=f"{campanha}|{id_c}", utm_medium=f"{conjunto}|{id_s}",
                        utm_content=f"{anuncio}|{id_a}", utm_term="Instagram_Reels",
                        campanha_id=id_c, campanha_nome=campanha, conjunto_id=id_s, conjunto_nome=conjunto,
                        anuncio_id=id_a, anuncio_nome=anuncio))
            # Algumas vendas orgânicas, sem UTM
            for _ in range(_poisson(aleatorio, 0.8 * fracao_dia)):
                numero_pedido += 1
                momento = datetime.combine(dia, time(aleatorio.randint(8, 22), 0), fuso)
                if momento > datetime.now(fuso):
                    momento = datetime.now(fuso) - timedelta(minutes=5)
                sessao.add(Venda(conta_id=conta.id, plataforma="kiwify", id_externo=f"KW{numero_pedido}",
                                 status=StatusVenda.APROVADA, metodo_pagamento=MetodoPagamento.PIX, moeda="BRL",
                                 valor_bruto_cent=19700, valor_liquido_cent=17929, produto_id=produtos[0].id,
                                 produto_nome=produtos[0].nome, cliente_nome="Cliente Orgânico",
                                 criada_em=momento, aprovada_em=momento, dia=dia))
    print(f"Demonstração criada. Entre com {EMAIL} / {SENHA}.")


def _email(nome: str) -> str:
    sem_acento = unicodedata.normalize("NFKD", nome).encode("ascii", "ignore").decode()
    return sem_acento.lower().replace(" ", ".") + "@exemplo.com"


def _poisson(aleatorio: random.Random, media: float) -> int:
    limite, k, p = 2.718281828 ** -media, 0, 1.0
    while True:
        p *= aleatorio.random()
        if p <= limite:
            return k
        k += 1


if __name__ == "__main__":
    cfg = carregar()
    banco = Banco(cfg.url_banco)
    banco.criar_tabelas()
    criar_demo(banco)
