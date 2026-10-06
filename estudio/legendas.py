"""Legendas automáticas: agrupa as palavras transcritas em telas, diagrama cada tela no quadro do vídeo e gera o
.ass que o libass queima na exportação.

O mesmo algoritmo existe em JavaScript (static/legendas.js), que desenha a prévia. Os dois precisam dar resultados
idênticos, e tests/casos_legendas.json confere isso dos dois lados: mudou um, mude o outro. Por isso as contas
evitam o que difere entre as linguagens (o round do Python, o tamanho de texto em UTF-16 do JavaScript).
"""

import math
import unicodedata

VERSAO = 1  # entra no .ass: mudar a receita das legendas refaz os trechos já exportados

# A fonte (Poppins, licença OFL) fica em static/fontes/ e é a mesma na prévia e na exportação.
FONTES = {
    "black": {"familia": "Poppins Black", "peso": 900, "arquivo": "Poppins-Black.ttf"},
    "extrabold": {"familia": "Poppins ExtraBold", "peso": 800, "arquivo": "Poppins-ExtraBold.ttf"},
}
# O libass mede o Fontsize pela altura usWinAscent + usWinDescent da fonte (1135 + 627 milésimos do em na Poppins),
# não pelo em como o canvas. Com \an5, o centro vertical da linha fica 0,254 em acima da linha de base.
FATOR_ASS = 1.762
DESLOCAMENTO_ASS = 0.254
ALTURA_MAIUSCULA = 0.71
ACIMA, ABAIXO = 1.01, 0.28  # até onde chegam os acentos das maiúsculas e as pernas do g e do ç, em ems

# Largura de cada caractere, em milésimos do em (tabela hmtx das fontes). Serve para reduzir a linha que não
# caberia e para o tamanho das caixas; a posição de cada letra quem decide é o desenho do texto.
CARACTERES = ("".join(map(chr, range(32, 127))) + "".join(chr(c) for c in range(0xA1, 0x100) if c != 0xAD)
              + "‘’“”–—…•€")
_LARGURAS = {
    "black": [
        170, 455, 490, 933, 665, 938, 831, 265, 463, 463, 561, 551, 342, 576, 319, 399, 662, 399, 566, 615, 704, 660,
        633, 512, 657, 597, 319, 385, 497, 626, 497, 538, 1129, 773, 684, 753, 743, 556, 575, 752, 755, 322, 590, 755,
        506, 951, 779, 788, 649, 788, 670, 625, 616, 719, 763, 1100, 764, 730, 630, 533, 878, 533, 758, 764, 324, 680,
        680, 609, 680, 616, 385, 680, 697, 322, 320, 676, 322, 1076, 697, 636, 680, 680, 467, 579, 436, 697, 671, 903,
        668, 677, 518, 484, 262, 484, 711, 455, 579, 679, 603, 730, 432, 595, 417, 771, 481, 618, 778, 511, 451, 496,
        551, 422, 403, 279, 751, 778, 349, 343, 285, 470, 618, 879, 928, 1024, 538, 773, 773, 773, 773, 773, 773, 986,
        753, 556, 556, 556, 556, 322, 322, 322, 322, 743, 779, 788, 788, 788, 788, 788, 581, 788, 719, 719, 719, 719,
        730, 649, 815, 680, 680, 680, 680, 680, 680, 1054, 609, 616, 616, 616, 616, 372, 372, 372, 372, 643, 697, 636,
        636, 636, 636, 636, 551, 621, 697, 697, 697, 697, 677, 680, 677, 378, 378, 648, 648, 683, 936, 869, 536, 790,
    ],
    "extrabold": [
        191, 423, 451, 919, 661, 904, 814, 243, 470, 470, 548, 589, 314, 578, 301, 426, 657, 387, 569, 610, 691, 655,
        635, 523, 653, 606, 302, 366, 524, 661, 519, 538, 1104, 755, 671, 758, 735, 548, 561, 757, 743, 308, 584, 726,
        491, 935, 765, 787, 636, 788, 661, 620, 604, 712, 747, 1076, 739, 701, 613, 522, 840, 521, 733, 772, 307, 680,
        680, 607, 680, 616, 373, 680, 686, 308, 307, 647, 308, 1067, 686, 636, 680, 680, 447, 568, 421, 686, 649, 885,
        628, 655, 507, 492, 277, 492, 674, 423, 605, 671, 590, 701, 407, 591, 392, 775, 475, 588, 748, 512, 436, 480,
        590, 403, 389, 270, 728, 743, 324, 328, 267, 464, 588, 833, 874, 957, 538, 755, 755, 755, 755, 755, 755, 971,
        758, 548, 548, 548, 548, 308, 308, 308, 308, 738, 765, 787, 787, 787, 787, 787, 609, 787, 712, 712, 712, 712,
        701, 636, 788, 680, 680, 680, 680, 680, 680, 1061, 607, 616, 616, 616, 616, 347, 347, 347, 347, 641, 686, 636,
        636, 636, 636, 636, 581, 625, 686, 686, 686, 686, 655, 680, 655, 346, 346, 595, 595, 689, 933, 815, 519, 793,
    ],
}
LARGURAS = {fonte: dict(zip(CARACTERES, valores, strict=True)) for fonte, valores in _LARGURAS.items()}
LARGURA_DESCONHECIDA = 1000  # emoji ou outro alfabeto: sai em outra fonte, então conta como largo

AMARELO, BRANCO, PRETO = "#FFDD00", "#FFFFFF", "#000000"

# tamanho: em da fonte no tamanho M, em fração do lado menor do vídeo. caracteres: limite por linha em cada
# tamanho. entrelinha: distância entre as linhas de base, em ems. contorno: espessura do traço preto, em ems.
PRESETS = {
    "destaque": {"fonte": "black", "tamanho": 0.082, "palavras": 3, "linhas": 2,
                 "caracteres": {"P": 18, "M": 14, "G": 11}, "entrelinha": 1.12, "contorno": 0.12,
                 "cor": BRANCO, "destaque": AMARELO, "caixa": None},
    "uma_palavra": {"fonte": "black", "tamanho": 0.13, "palavras": 1, "linhas": 1,
                    "caracteres": {"P": 40, "M": 40, "G": 40}, "entrelinha": 1.0, "contorno": 0.1,
                    "cor": AMARELO, "destaque": None, "caixa": None},
    "classica": {"fonte": "extrabold", "tamanho": 0.058, "palavras": 7, "linhas": 2,
                 "caracteres": {"P": 27, "M": 22, "G": 18}, "entrelinha": 1.18, "contorno": 0.09,
                 "cor": BRANCO, "destaque": None, "caixa": None},
    "caixa": {"fonte": "extrabold", "tamanho": 0.064, "palavras": 4, "linhas": 2,
              "caracteres": {"P": 22, "M": 18, "G": 15}, "entrelinha": 1.36, "contorno": 0.0,
              "cor": BRANCO, "destaque": None,
              "caixa": {"cor": PRETO, "opacidade": 0.62, "folga": 0.36, "altura": 1.36, "raio": 0.22}},
}
FATOR_TAMANHO = {"P": 0.82, "M": 1.0, "G": 1.22}
POSICOES = {"alto": 0.28, "centro": 0.5, "baixo": 0.66}  # centro do bloco de texto, em fração da altura
LIMITE_TOPO, LIMITE_BASE = 0.12, 0.75  # o Reels cobre o topo e os 25% de baixo com a interface dele
LARGURA_UTIL = 0.84

SOBREPOSICAO_MINIMA = 0.02  # s: palavra que mal encosta no corte fica de fora
PAUSA_QUEBRA = 0.5  # s: pausa maior que isso começa outra tela
SOBRA_FINAL = 0.6  # s que a tela fica depois da última palavra
EMENDA = 0.25  # s: vão menor que isso entre duas telas some, para a legenda não piscar
POP = ((0.0, 0.75), (0.09, 1.08), (0.15, 1.0))  # (segundos desde o começo da tela, escala)

ESTILO_PADRAO = {"preset": "destaque", "tamanho": "M", "posicao": "baixo", "maiusculas": True, "animacao": True}


def arred(valor: float, casas: int) -> float:
    """Arredonda meio para cima, como o Math.round do JavaScript (o round do Python arredonda para o par)."""
    fator = 10 ** casas
    return math.floor(valor * fator + 0.5) / fator


def termina_frase(texto: str) -> bool:
    return texto.rstrip("\"'”’»)]").endswith((".", "!", "?", "…"))


def largura_em(texto: str, fonte: str) -> float:
    tabela = LARGURAS[fonte]
    return sum(tabela.get(c, LARGURA_DESCONHECIDA) for c in texto) / 1000


def quebrar_linhas(textos: list[str], limite: int, max_linhas: int) -> list[list[int]] | None:
    """Divide as palavras em linhas de até `limite` caracteres, o mais equilibradas possível. Uma palavra sozinha
    pode passar do limite (ela é reduzida depois, no diagrama). None se não couber em `max_linhas` linhas."""
    tamanhos = [len(t) for t in textos]

    def comprimento(a: int, b: int) -> int:
        return sum(tamanhos[a:b]) + (b - a - 1)

    def cabe(a: int, b: int) -> bool:
        return b - a == 1 or comprimento(a, b) <= limite

    n = len(textos)
    if cabe(0, n):
        return [list(range(n))]
    if max_linhas < 2:
        return None
    melhor = None
    for k in range(1, n):
        if cabe(0, k) and cabe(k, n):
            maior = max(comprimento(0, k), comprimento(k, n))
            if melhor is None or maior < melhor[0]:
                melhor = (maior, k)
    return None if melhor is None else [list(range(melhor[1])), list(range(melhor[1], n))]


def palavras_no_corte(palavras: list[dict], entrada: float, saida: float) -> list[dict]:
    """As palavras dentro do corte, recortadas a ele e no tempo do trecho (0 = começo do corte)."""
    resultado = []
    for p in palavras:
        inicio, fim = max(p["inicio"], entrada), min(p["fim"], saida)
        if fim - inicio > SOBREPOSICAO_MINIMA:
            resultado.append({"texto": p["texto"], "inicio": inicio - entrada, "fim": fim - entrada})
    return resultado


def montar_telas(palavras: list[dict], entrada: float, saida: float, estilo: dict) -> list[dict]:
    """Agrupa as palavras de um trecho da linha do tempo nas telas de legenda, com o tempo de cada uma."""
    preset = PRESETS[estilo["preset"]]
    limite = preset["caracteres"][estilo["tamanho"]]
    duracao = saida - entrada
    locais = palavras_no_corte(palavras, entrada, saida)
    for p in locais:
        p["texto"] = p["texto"].upper() if estilo["maiusculas"] else p["texto"]

    grupos: list[list[dict]] = []
    atual: list[dict] = []
    for p in locais:
        if atual:
            anterior = atual[-1]
            if (len(atual) >= preset["palavras"] or p["inicio"] - anterior["fim"] > PAUSA_QUEBRA
                    or termina_frase(anterior["texto"])
                    or quebrar_linhas([q["texto"] for q in [*atual, p]], limite, preset["linhas"]) is None):
                grupos.append(atual)
                atual = []
        atual.append(p)
    if atual:
        grupos.append(atual)

    telas = []
    for n, grupo in enumerate(grupos):
        fim = min(grupo[-1]["fim"] + SOBRA_FINAL, duracao)
        if n + 1 < len(grupos):
            proxima = grupos[n + 1][0]["inicio"]
            fim = min(fim, proxima)
            if proxima - fim < EMENDA:
                fim = proxima
        # Os tempos saem em centésimos, a precisão do .ass: assim a prévia mostra o mesmo que o vídeo.
        inicio, fim = arred(grupo[0]["inicio"], 2), arred(fim, 2)
        if fim <= inicio:
            continue
        exibidas = [{"texto": p["texto"], "inicio": arred(p["inicio"], 2), "fim": arred(p["fim"], 2)} for p in grupo]
        destaques = None
        if preset["destaque"]:
            destaques = []
            for k, p in enumerate(exibidas):
                a = max(p["inicio"], inicio)
                b = min(exibidas[k + 1]["inicio"] if k + 1 < len(exibidas) else fim, fim)
                destaques.append([a, max(a, b)])
        telas.append({"inicio": inicio, "fim": fim, "palavras": exibidas,
                      "linhas": quebrar_linhas([p["texto"] for p in grupo], limite, preset["linhas"]),
                      "destaques": destaques})
    return telas


def diagramar(tela: dict, estilo: dict, largura: int, altura: int) -> dict:
    """Onde e em que tamanho cada linha da tela fica no quadro, em pixels do vídeo exportado."""
    preset = PRESETS[estilo["preset"]]
    fonte = FONTES[preset["fonte"]]
    caixa = preset["caixa"]
    textos = [" ".join(tela["palavras"][i]["texto"] for i in linha) for linha in tela["linhas"]]
    larguras = [largura_em(t, preset["fonte"]) for t in textos]

    em = min(largura, altura) * preset["tamanho"] * FATOR_TAMANHO[estilo["tamanho"]]
    lado = caixa["folga"] if caixa else preset["contorno"]
    ocupado = (max(larguras) + 2 * lado) * em
    escala = min(1.0, math.floor(largura * LARGURA_UTIL / ocupado * 1000) / 1000)
    em = em * escala
    contorno = preset["contorno"] * em
    passo = preset["entrelinha"] * em
    meio = ALTURA_MAIUSCULA / 2 * em
    n = len(textos)

    # O centro do bloco (meio das maiúsculas da primeira à última linha) vai na altura escolhida, sem invadir as
    # faixas que a interface do Reels cobre.
    base = altura * POSICOES[estilo["posicao"]] + meio - (n - 1) * passo / 2
    if caixa:
        acima = meio + caixa["altura"] / 2 * em
        abaixo = caixa["altura"] / 2 * em - meio
    else:
        acima = ACIMA * em + contorno
        abaixo = ABAIXO * em + contorno
    topo, fundo = base - acima, base + (n - 1) * passo + abaixo
    minimo, maximo = altura * LIMITE_TOPO, altura * LIMITE_BASE
    if fundo - topo > maximo - minimo:
        base += (minimo + maximo) / 2 - (topo + fundo) / 2
    elif fundo > maximo:
        base -= fundo - maximo
    elif topo < minimo:
        base += minimo - topo

    linhas, caixas = [], []
    for i, texto in enumerate(textos):
        b = base + i * passo
        linhas.append({"texto": texto, "palavras": list(tela["linhas"][i]), "x": arred(largura / 2, 2),
                       "y": arred(b - DESLOCAMENTO_ASS * em, 2), "base": arred(b, 2),
                       "largura": arred(larguras[i] * em, 2)})
        if caixa:
            caixas.append({"x": arred(largura / 2, 2), "y": arred(b - meio, 2),
                           "largura": arred((larguras[i] + 2 * caixa["folga"]) * em, 2),
                           "altura": arred(caixa["altura"] * em, 2), "raio": arred(caixa["raio"] * em, 2)})
    return {"fonte": fonte["familia"], "peso": fonte["peso"], "em": arred(em, 2), "fs": arred(em * FATOR_ASS, 2),
            "contorno": arred(contorno, 2), "escala": escala, "linhas": linhas, "caixas": caixas}


def escala_pop(t: float) -> float:
    """Escala da tela t segundos depois de ela aparecer (a animação "pop")."""
    if t <= POP[0][0]:
        return POP[0][1]
    for (t0, e0), (t1, e1) in zip(POP, POP[1:]):
        if t < t1:
            return e0 + (e1 - e0) * (t - t0) / (t1 - t0)
    return POP[-1][1]


def legendas_do_trecho(palavras: list[dict], entrada: float, saida: float, estilo: dict, largura: int,
                       altura: int) -> list[tuple[dict, dict]]:
    return [(tela, diagramar(tela, estilo, largura, altura)) for tela in montar_telas(palavras, entrada, saida, estilo)]


# Realinhamento do texto corrigido


def _distribuir(textos: list[str], a: float, b: float) -> list[dict]:
    """Espalha as palavras em [a, b], cada uma com um tempo proporcional ao tamanho dela."""
    pesos = [len(t) for t in textos]
    total = sum(pesos)
    resultado, acumulado = [], 0
    for texto, peso in zip(textos, pesos):
        inicio = a + (b - a) * acumulado / total
        acumulado += peso
        fim = a + (b - a) * acumulado / total
        resultado.append({"inicio": arred(inicio, 3), "fim": arred(fim, 3), "texto": texto})
    return resultado


def realinhar(palavras: list[dict], texto: str, intervalo: tuple[float, float] | None = None) -> list[dict]:
    """Aplica o texto corrigido pela pessoa às palavras com tempo.

    Com o mesmo número de palavras, cada uma mantém o seu tempo. Se mudou, as palavras iguais do começo e do fim
    mantêm o tempo e só o trecho alterado é redistribuído, do início da primeira ao fim da última palavra dele, na
    proporção do tamanho de cada palavra. `intervalo` é usado quando ainda não havia palavra nenhuma.
    """
    novas = unicodedata.normalize("NFC", texto).split()
    if not novas:
        return []
    if len(novas) == len(palavras):
        return [{"inicio": p["inicio"], "fim": p["fim"], "texto": t} for p, t in zip(palavras, novas)]
    if not palavras:
        return _distribuir(novas, intervalo[0], intervalo[1]) if intervalo else []
    antigas = [p["texto"] for p in palavras]
    i = 0
    while i < len(novas) and i < len(antigas) and novas[i] == antigas[i]:
        i += 1
    j = 0
    while j < len(novas) - i and j < len(antigas) - i and novas[-1 - j] == antigas[-1 - j]:
        j += 1
    if i + j == len(antigas):
        # Só entrou palavra: a vizinha divide o tempo dela com as novas.
        if i > 0:
            i -= 1
        else:
            j -= 1
    meio_antigo = palavras[i:len(palavras) - j]
    meio_novo = novas[i:len(novas) - j]
    meio = _distribuir(meio_novo, meio_antigo[0]["inicio"], meio_antigo[-1]["fim"]) if meio_novo else []
    return [dict(p) for p in palavras[:i]] + meio + [dict(p) for p in palavras[len(palavras) - j:]]


# Arquivo .ass para o libass


def _num(valor: float) -> str:
    return f"{valor:.2f}".rstrip("0").rstrip(".")


def _cs(segundos: float) -> int:
    return math.floor(segundos * 100 + 0.5)


def _tempo(segundos: float) -> str:
    h, resto = divmod(_cs(segundos), 360000)
    m, resto = divmod(resto, 6000)
    s, cs = divmod(resto, 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def cor_ass(cor: str, opacidade: float = 1.0, com_alfa: bool = False) -> str:
    """#RRGGBB vira &HBBGGRR& (ou &HAABBGGRR, com a transparência, no estilo)."""
    r, g, b = cor[1:3], cor[3:5], cor[5:7]
    if com_alfa:
        return f"&H{math.floor(255 * (1 - opacidade) + 0.5):02X}{b}{g}{r}".upper()
    return f"&H{b}{g}{r}&".upper()


def escapar(texto: str) -> str:
    """Chaves abririam um bloco de efeitos e a barra invertida um código (\\N, \\h...). O U+2060 é invisível."""
    return texto.replace("\\", "\\⁠").replace("{", "\\{").replace("}", "\\}")


def _pop_ass() -> str:
    (_, e0), *passos = POP
    tags = f"\\fscx{round(e0 * 100)}\\fscy{round(e0 * 100)}"
    anterior = 0
    for t, e in passos:
        fim = round(t * 1000)
        tags += f"\\t({anterior},{fim},\\fscx{round(e * 100)}\\fscy{round(e * 100)})"
        anterior = fim
    return tags


def _retangulo(largura: float, altura: float, raio: float) -> str:
    """Retângulo de cantos arredondados para o modo de desenho do .ass, com o canto de cima à esquerda em 0,0."""
    w, h, r = largura, altura, min(raio, largura / 2, altura / 2)
    c = r * 0.4477  # distância dos pontos de controle da curva até o canto (1 - 0,5523 do círculo)
    p = _num
    return (f"m {p(r)} 0 l {p(w - r)} 0 b {p(w - c)} 0 {p(w)} {p(c)} {p(w)} {p(r)} "
            f"l {p(w)} {p(h - r)} b {p(w)} {p(h - c)} {p(w - c)} {p(h)} {p(w - r)} {p(h)} "
            f"l {p(r)} {p(h)} b {p(c)} {p(h)} 0 {p(h - c)} 0 {p(h - r)} "
            f"l 0 {p(r)} b 0 {p(c)} {p(c)} 0 {p(r)} 0")


def gerar_ass(telas: list[tuple[dict, dict]], estilo: dict, largura: int, altura: int) -> str:
    """O .ass de um trecho: uma linha de diálogo por linha de texto de cada tela, no tempo do trecho."""
    preset = PRESETS[estilo["preset"]]
    familia = FONTES[preset["fonte"]]["familia"]
    cor, destaque = cor_ass(preset["cor"]), cor_ass(preset["destaque"] or preset["cor"])
    caixa = preset["caixa"] or {"cor": PRETO, "opacidade": 1.0}
    pop = _pop_ass() if estilo["animacao"] else ""
    linhas = [
        "[Script Info]",
        f"; Estúdio de Reels, legendas versão {VERSAO}",
        "ScriptType: v4.00+",
        f"PlayResX: {largura}",
        f"PlayResY: {altura}",
        "WrapStyle: 2",
        "ScaledBorderAndShadow: yes",
        "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, "
        "Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, "
        "MarginR, MarginV, Encoding",
        f"Style: Legenda,{familia},100,{cor_ass(preset['cor'], com_alfa=True)},{cor_ass(preset['cor'], com_alfa=True)},"
        "&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,0,0,5,0,0,0,1",
        f"Style: Caixa,{familia},100,{cor_ass(caixa['cor'], caixa['opacidade'], com_alfa=True)},&H00000000,"
        "&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,0,0,5,0,0,0,1",
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]
    for tela, diagrama in telas:
        inicio, fim = _tempo(tela["inicio"]), _tempo(tela["fim"])
        base_ms = _cs(tela["inicio"]) * 10
        duracao_ms = _cs(tela["fim"]) * 10 - base_ms
        for c in diagrama["caixas"]:
            linhas.append(f"Dialogue: 0,{inicio},{fim},Caixa,,0,0,0,,{{\\an5\\pos({_num(c['x'])},{_num(c['y'])})"
                          f"{pop}\\p1}}{_retangulo(c['largura'], c['altura'], c['raio'])}{{\\p0}}")
        for linha in diagrama["linhas"]:
            partes = []
            for i in linha["palavras"]:
                texto = escapar(tela["palavras"][i]["texto"])
                if not tela["destaques"]:
                    partes.append(texto)
                    continue
                # A cor de cada palavra troca no instante exato com \t(t,t,...): branca, amarela e branca de novo.
                a, b = (math.floor(v * 1000 + 0.5) - base_ms for v in tela["destaques"][i])
                if b <= a:
                    tags = f"\\1c{cor}"
                else:
                    tags = f"\\1c{destaque}" if a <= 0 else f"\\1c{cor}\\t({a},{a},\\1c{destaque})"
                    if b < duracao_ms:
                        tags += f"\\t({b},{b},\\1c{cor})"
                partes.append(f"{{{tags}}}{texto}")
            linhas.append(f"Dialogue: 1,{inicio},{fim},Legenda,,0,0,0,,{{\\pos({_num(linha['x'])},{_num(linha['y'])})"
                          f"\\fs{_num(diagrama['fs'])}\\bord{_num(diagrama['contorno'])}{pop}}}" + " ".join(partes))
    return "\n".join(linhas) + "\n"
