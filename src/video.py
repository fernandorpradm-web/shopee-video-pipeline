import subprocess
import tempfile

def montar_video(imagem: str, audio: str, texto_tela: str, saida: str):
    """Monta vídeo vertical 1080x1920: imagem com zoom lento + texto no topo + narração."""
    # Texto da tela vai em arquivo temporário (evita problemas de escape/acentos)
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8") as f:
        f.write(texto_tela)
        textfile = f.name

    filtro = (
        "[0:v]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,"
        "zoompan=z='min(zoom+0.0006,1.18)':d=1200:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':fps=30,"
        "drawtext=textfile='%s':font='DejaVu Sans':fontsize=68:fontcolor=white:"
        "borderw=6:bordercolor=black:x=(w-text_w)/2:y=h*0.12[v]"
    ) % textfile

    cmd = [
        "ffmpeg", "-y",
        "-loop", "1", "-i", imagem,
        "-i", audio,
        "-filter_complex", filtro,
        "-map", "[v]", "-map", "1:a",
        "-c:v", "libx264", "-preset", "fast", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "128k",
        "-shortest", saida,
    ]
    subprocess.run(cmd, check=True, capture_output=True)
