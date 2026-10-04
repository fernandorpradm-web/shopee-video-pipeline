import subprocess
import tempfile

def montar_video(imagem: str, audio: str, texto_tela: str, saida: str):
    """Vídeo vertical 1080x1920 com composição profissional:
    fundo desfocado preenchendo o quadro, produto inteiro em destaque
    (sem corte e sem esticar), zoom sutil, texto fixo no topo e narração."""
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8") as f:
        f.write(texto_tela)
        textfile = f.name

    filtro = (
        "[0:v]split=2[bg][p];"
        "[bg]scale=540:960:force_original_aspect_ratio=increase,crop=540:960,"
        "gblur=sigma=20,eq=brightness=-0.07,scale=1080:1920[bgb];"
        "[p]scale=950:1000:force_original_aspect_ratio=decrease[pf];"
        "[bgb][pf]overlay=(W-w)/2:(H-h)/2+68[comp];"
        "[comp]zoompan=z='min(zoom+0.00015,1.12)':d=1800:"
        "x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s=1080x1920:fps=30,"
        "fade=t=in:st=0:d=0.4,"
        "drawtext=textfile='%s':font='DejaVu Sans':fontsize=62:fontcolor=white:"
        "borderw=6:bordercolor=black:x=(w-text_w)/2:y=h*0.15:line_spacing=18[v]"
    ) % textfile

    cmd = [
        "ffmpeg", "-y",
        "-i", imagem,
        "-i", audio,
        "-filter_complex", filtro,
        "-map", "[v]", "-map", "1:a",
        "-c:v", "libx264", "-preset", "fast", "-crf", "20", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "128k",
        "-shortest", saida,
    ]
    subprocess.run(cmd, check=True, capture_output=True)
