"""Senhas (scrypt), cookie de sessão assinado e limite de tentativas de login."""

import base64
import hashlib
import hmac
import secrets
import threading
import time

_N, _R, _P = 2**14, 8, 1
DURACAO_SESSAO = 30 * 24 * 3600


def gerar_hash_senha(senha: str) -> str:
    sal = secrets.token_bytes(16)
    chave = hashlib.scrypt(senha.encode(), salt=sal, n=_N, r=_R, p=_P, dklen=32)
    return f"scrypt${_N}${_R}${_P}${sal.hex()}${chave.hex()}"


def conferir_senha(senha: str, guardado: str) -> bool:
    try:
        _, n, r, p, sal, chave = guardado.split("$")
        calculada = hashlib.scrypt(senha.encode(), salt=bytes.fromhex(sal), n=int(n), r=int(r), p=int(p),
                                   dklen=len(bytes.fromhex(chave)))
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(calculada.hex(), chave)


def _assinar(dados: str, chave: str) -> str:
    return hmac.new(chave.encode(), dados.encode(), hashlib.sha256).hexdigest()


def criar_cookie_sessao(usuario_id: int, versao: int, chave: str, agora: float | None = None) -> str:
    expira = int((agora or time.time()) + DURACAO_SESSAO)
    dados = f"{usuario_id}:{versao}:{expira}"
    bruto = f"{dados}:{_assinar(dados, chave)}"
    return base64.urlsafe_b64encode(bruto.encode()).decode()


def ler_cookie_sessao(valor: str, chave: str, agora: float | None = None) -> tuple[int, int] | None:
    """Devolve (usuario_id, versao_sessao) se o cookie for válido e não estiver expirado."""
    try:
        bruto = base64.urlsafe_b64decode(valor.encode()).decode()
        usuario_id, versao, expira, assinatura = bruto.split(":")
    except (ValueError, UnicodeDecodeError):
        return None
    if not hmac.compare_digest(assinatura, _assinar(f"{usuario_id}:{versao}:{expira}", chave)):
        return None
    if int(expira) < (agora or time.time()):
        return None
    return int(usuario_id), int(versao)


class LimiteTentativas:
    """Bloqueia um IP por alguns minutos depois de muitas senhas erradas seguidas."""

    def __init__(self, maximo: int = 8, janela: int = 15 * 60):
        self.maximo = maximo
        self.janela = janela
        self._falhas: dict[str, list[float]] = {}
        self._trava = threading.Lock()

    def bloqueado(self, chave: str) -> bool:
        with self._trava:
            recentes = [t for t in self._falhas.get(chave, []) if t > time.time() - self.janela]
            self._falhas[chave] = recentes
            return len(recentes) >= self.maximo

    def falhou(self, chave: str) -> None:
        with self._trava:
            self._falhas.setdefault(chave, []).append(time.time())

    def limpar(self, chave: str) -> None:
        with self._trava:
            self._falhas.pop(chave, None)
