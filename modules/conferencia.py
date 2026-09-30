"""Conferência de jogos guardados contra um sorteio já registado."""

from collections import Counter

from modules.totoloto import avaliar_aposta


ROTULOS_PREMIO = {
    "primeiro": "1.º Prémio",
    "segundo": "2.º Prémio",
    "terceiro": "3.º Prémio",
    "quarto": "4.º Prémio",
}


def _numeros_do_jogo(valor):
    return [int(parte.strip()) for parte in str(valor or "").split(",") if parte.strip()]


def conferir_jogos(jogos, resultado):
    """Confere jogos individualmente, isolando dados malformados."""
    categorias = Counter({chave: 0 for chave in ROTULOS_PREMIO})
    premiados = []
    erros = []
    conferidos = 0
    for jogo in jogos or []:
        try:
            avaliacao = avaliar_aposta(_numeros_do_jogo(jogo.get("numeros")), resultado)
            conferidos += 1
            premios = {chave: int(valor) for chave, valor in avaliacao["premios"].items() if valor}
            for chave, quantidade in premios.items():
                categorias[chave] += quantidade
            if premios:
                premiados.append({
                    "id": jogo.get("id"),
                    "numeros": jogo.get("numeros"),
                    "acertos": avaliacao["melhor_acerto"],
                    "premios": premios,
                    "categorias": [ROTULOS_PREMIO[chave] for chave in premios],
                })
        except Exception as exc:
            erros.append({"id": jogo.get("id"), "mensagem": str(exc)})
    return {
        "jogos_conferidos": conferidos,
        "jogos_premiados": premiados,
        "premios_por_categoria": dict(categorias),
        "erros": erros,
    }
