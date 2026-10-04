import edge_tts

async def gerar_audio(texto: str, saida: str, voz: str = "pt-BR-FranciscaNeural"):
    """Gera a narração em MP3 com voz neural gratuita (edge-tts)."""
    comunicador = edge_tts.Communicate(texto, voz, rate="+8%")
    await comunicador.save(saida)
