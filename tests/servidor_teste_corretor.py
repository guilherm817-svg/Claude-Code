"""Servidor do Estúdio para o teste de tela do Corretor (tests/e2e_estudio_corretor.cjs).

Roda o Estúdio de verdade; só a rede até o Claude é trocada por uma resposta fixa (tests/dados/correcao_exemplo.json),
enviada em pedaços com pequenas pausas para a tela mostrar as etapas. Um prompt com "ERRO-401" simula chave inválida,
e um com "LENTO" deixa o "Claude" raciocinando (só pings) por 20 s, para testar o Cancelar.
O .env e os projetos ficam na pasta indicada, e o último pedido enviado ao "Claude" é gravado em ultimo_pedido.json.

    python tests/servidor_teste_corretor.py --porta 8710 --pasta /tmp/corretor-e2e
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

import anthropic  # noqa: E402
import httpx2  # noqa: E402
import uvicorn  # noqa: E402

RESPOSTA_FIXA = RAIZ / "tests" / "dados" / "correcao_exemplo.json"


def _evento(nome: str, dados: dict) -> bytes:
    return f"event: {nome}\ndata: {json.dumps(dados, ensure_ascii=False)}\n\n".encode()


def _sse(texto: str, pensando: float = 0.8):
    yield _evento("message_start", {"type": "message_start", "message": {
        "id": "msg_teste", "type": "message", "role": "assistant", "model": "claude-opus-5-5", "content": [],
        "stop_reason": None, "stop_sequence": None,
        "usage": {"input_tokens": 40, "output_tokens": 1, "cache_creation_input_tokens": 0, "cache_read_input_tokens": 9000}}})
    # Raciocínio (vem vazio, como na API) antes do texto.
    yield _evento("content_block_start", {"type": "content_block_start", "index": 0,
                                          "content_block": {"type": "thinking", "thinking": "", "signature": ""}})
    for _ in range(int(pensando / 0.2)):
        time.sleep(0.2)
        yield _evento("ping", {"type": "ping"})
    yield _evento("content_block_delta", {"type": "content_block_delta", "index": 0,
                                          "delta": {"type": "signature_delta", "signature": "assinatura"}})
    yield _evento("content_block_stop", {"type": "content_block_stop", "index": 0})
    yield _evento("content_block_start", {"type": "content_block_start", "index": 1,
                                          "content_block": {"type": "text", "text": ""}})
    for i in range(0, len(texto), 400):
        time.sleep(0.04)
        yield _evento("content_block_delta", {"type": "content_block_delta", "index": 1,
                                              "delta": {"type": "text_delta", "text": texto[i:i + 400]}})
    yield _evento("content_block_stop", {"type": "content_block_stop", "index": 1})
    yield _evento("message_delta", {"type": "message_delta", "delta": {"stop_reason": "end_turn", "stop_sequence": None},
                                    "usage": {"output_tokens": 4200}})
    yield _evento("message_stop", {"type": "message_stop"})


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--porta", type=int, required=True)
    parser.add_argument("--pasta", required=True)
    args = parser.parse_args()
    pasta = Path(args.pasta)
    pasta.mkdir(parents=True, exist_ok=True)
    os.environ["ESTUDIO_PASTA_DADOS"] = str(pasta / "dados")

    from estudio import config, corretor
    from estudio.servidor import criar_app

    # Depois de importar o config (que lê o .env real): o teste começa sem chave e grava a chave na pasta temporária.
    for nome in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN"):
        os.environ.pop(nome, None)
    config.ARQUIVO_ENV = pasta / ".env"
    resposta = RESPOSTA_FIXA.read_text(encoding="utf-8")

    def responder(request: httpx2.Request) -> httpx2.Response:
        corpo = json.loads(request.content)
        (pasta / "ultimo_pedido.json").write_text(json.dumps(corpo, ensure_ascii=False), encoding="utf-8")
        if "ERRO-401" in corpo["messages"][0]["content"]:
            return httpx2.Response(401, json={"type": "error", "error": {"type": "authentication_error",
                                                                          "message": "invalid x-api-key"}})
        pensando = 20 if "LENTO" in corpo["messages"][0]["content"] else 0.8
        texto = resposta
        if "LEGENDA-ESTUDIO" in corpo["messages"][0]["content"]:
            # Prompt que pedia legenda: a resposta traz o estilo para aplicar nas legendas do Estúdio.
            dados = json.loads(resposta)
            dados["estilo_de_legenda"] = "Uma palavra por vez, amarela com contorno preto, grande, abaixo do rosto."
            dados["legenda_no_estudio"] = {"preset": "uma_palavra", "tamanho": "G", "posicao": "baixo", "maiusculas": True}
            texto = json.dumps(dados, ensure_ascii=False)
        return httpx2.Response(200, headers={"content-type": "text/event-stream"}, content=_sse(texto, pensando))

    corretor._cliente = lambda: anthropic.Anthropic(
        max_retries=0, http_client=anthropic.DefaultHttpxClient(transport=httpx2.MockTransport(responder)))
    uvicorn.run(criar_app(), host="127.0.0.1", port=args.porta, log_level="warning")


if __name__ == "__main__":
    main()
