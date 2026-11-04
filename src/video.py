#!/usr/bin/env python3
"""
Compoe o video vertical (1080x1920):
  fundo desfocado da propria foto + card do produto + avatar sem verde
  + legenda curta queimada + narracao.
"""

import os
import shutil
import subprocess
import tempfile

LARGURA = 1080
ALTURA = 1920
FPS = 30

AVATAR_PADRAO = "avatar.png"
AVATAR_ALPHA = "avatar_alpha.png"

VERDE_AUTODETECT = True
VERDE_MANUAL = "0x00B140"
SIMILARIDADE = 0.28
SUAVIZAR = 0.08

FONTES = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf",
]


def _roda(cmd):
    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode != 0:
        raise RuntimeError("ffmpeg falhou:\n%s" % (p.stderr or "")[-1500:])
    return (p.stdout or "").strip()


def _esc(caminho):
    return str(caminho).replace("\\", "\\\\").replace(":", "\\:")


def _fonte():
    for c in FONTES:
        if os.path.exists(c):
            return "fontfile=%s" % _esc(c)
    return "font=Sans"


def _dim_frames(caminho):
    out = _roda(["ffprobe", "-v", "error", "-select_streams", "v:0",
                 "-show_entries", "stream=width,height",
                 "-of", "csv=p=0:s=x", caminho])
    w, h = out.split("x")[:2]
    return int(w), int(h)


def duracao_audio(caminho):
    out = _roda(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                 "-of", "csv=p=0", caminho])
    try:
        return max(2.0, float(out))
    except ValueError:
        return 5.0


def _pixel(imagem, x, y):
    try:
        p = subprocess.run(
            ["ffmpeg", "-v", "error", "-i", imagem,
             "-vf", "crop=1:1:%d:%d" % (x, y),
             "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
            capture_output=True)
        d = p.stdout
        if len(d) < 3:
            return None
        return d[0], d[1], d[2]
    except Exception:
        return None


def detectar_verde(imagem):
    """Amostra os quatro cantos — o fundo do avatar deve ser uniforme."""
    try:
        w, h = _dim_frames(imagem)
    except Exception:
        return None
    pontos = [(2, 2), (max(0, w - 3), 2), (2, max(0, h - 3)),
              (max(0, w - 3), max(0, h - 3))]
    cores = [c for c in (_pixel(imagem, x, y) for x, y in pontos) if c]
    if not cores:
        return None
    r = sorted(c[0] for c in cores)[len(cores) // 2]
    g = sorted(c[1] for c in cores)[len(cores) // 2]
    b = sorted(c[2] for c in cores)[len(cores) // 2]
    if g < 90 or g < r + 25 or g < b + 25:
        print("   aviso: fundo do avatar nao parece verde uniforme")
    return "0x%02X%02X%02X" % (r, g, b)


def preparar_avatar(origem, cache=AVATAR_ALPHA):
    """Remove o verde uma unica vez e reusa o PNG com alpha."""
    if not origem or not os.path.exists(origem):
        print("   aviso: avatar '%s' nao encontrado — video sem avatar" % origem)
        return None

    if os.path.exists(cache) and os.path.getmtime(cache) >= os.path.getmtime(origem):
        return cache

    cor = VERDE_MANUAL
    if VERDE_AUTODETECT:
        cor = detectar_verde(origem) or VERDE_MANUAL
    print("   chroma key em %s" % cor)

    base = "format=rgba,chromakey=%s:%.2f:%.2f" % (cor, SIMILARIDADE, SUAVIZAR)
    for filtro in (base + ",despill=type=green", base):
        try:
            _roda(["ffmpeg", "-y", "-i", origem, "-vf", filtro,
                   "-frames:v", "1", cache])
            return cache
        except RuntimeError:
            continue

    print("   aviso: falha ao remover o fundo — video sem avatar")
    return None


def quebrar_texto(texto, limite=18, max_linhas=3):
    palavras = str(texto).split()
    linhas, atual = [], ""
    for p in palavras:
        if not atual:
            atual = p
        elif len(atual) + 1 + len(p) <= limite:
            atual = atual + " " + p
        else:
            linhas.append(atual)
            atual = p
    if atual:
        linhas.append(atual)
    return "\n".join(linhas[:max_linhas])


def montar_video(imagem, audio, texto, saida, avatar=None):
    pasta = os.path.dirname(saida)
    if pasta:
        os.makedirs(pasta, exist_ok=True)

    dur = duracao_audio(audio)
    av = preparar_avatar(avatar or AVATAR_PADRAO)
    fonte = _fonte()

    tmp = tempfile.mkdtemp(prefix="vid_")
    try:
        txt = os.path.join(tmp, "legenda.txt")
        with open(txt, "w", encoding="utf-8") as f:
            f.write(quebrar_texto(texto))

        entradas = ["-loop", "1", "-framerate", str(FPS), "-t", "%.2f" % dur,
                    "-i", imagem]
        if av:
            entradas += ["-loop", "1", "-framerate", str(FPS), "-t", "%.2f" % dur,
                         "-i", av]
        entradas += ["-i", audio]
        idx_audio = 2 if av else 1

        if av:
            card, y_card, fs, y_txt = 860, 170, 64, 1120
        else:
            card, y_card, fs, y_txt = 980, 280, 76, 1350

        partes = [
            "[0:v]split=2[pbg][pc]",
            "[pbg]scale=%d:%d:force_original_aspect_ratio=increase,"
            "crop=%d:%d,gblur=sigma=48,eq=brightness=-0.32:saturation=0.58[bg]"
            % (LARGURA, ALTURA, LARGURA, ALTURA),
            "[pc]scale=%d:%d:force_original_aspect_ratio=decrease,"
            "pad=%d:%d:(ow-iw)/2:(oh-ih)/2:color=white,"
            "zoompan=z='min(1+0.0005*on,1.07)':d=1:"
            "x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s=%dx%d:fps=%d[card]"
            % (card, card, card, card, card, card, FPS),
            "[bg][card]overlay=(W-w)/2:%d[base]" % y_card,
        ]

        atual = "base"
        if av:
            partes.append("[1:v]scale=390:-1[avt]")
            partes.append("[%s][avt]overlay=W-w-26:H-h-26:format=auto[withav]"
                          % atual)
            atual = "withav"

        partes.append(
            "[%s]drawtext=textfile=%s:%s:fontsize=%d:fontcolor=white:"
            "line_spacing=16:box=1:boxcolor=black@0.55:boxborderw=26:"
            "x=(w-text_w)/2:y=%d[out]"
            % (atual, _esc(txt), fonte, fs, y_txt))

        cmd = (["ffmpeg", "-y"] + entradas +
               ["-filter_complex", ";".join(partes),
                "-map", "[out]", "-map", "%d:a" % idx_audio,
                "-c:v", "libx264", "-preset", "medium", "-crf", "21",
                "-pix_fmt", "yuv420p", "-r", str(FPS),
                "-c:a", "aac", "-b:a", "128k",
                "-shortest", "-movflags", "+faststart", saida])
        _roda(cmd)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    return saida
