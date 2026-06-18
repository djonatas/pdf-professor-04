#!/usr/bin/env python3
"""
GERADOR DE SLIDES HIBRIDO V3
Gemini gera background + codigo sobrepoe texto.
GARANTE: 100% preenchimento, contraste, direcao correta.

Uso: python3 _gerar-slides-hibrido.py [CODIGO]
     python3 _gerar-slides-hibrido.py EF01LP01
"""
import json, sys, os, requests, base64, time, shutil, re
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
import fitz

REPO = Path(__file__).parent
MODEL = "gemini-3.1-flash-image-preview"  # Model name for Google API
SLIDE_W, SLIDE_H = 1920, 1080  # 16:9 Full HD
NUNITO_FONT = str(REPO / "canvas-fonts" / "Nunito-Variable.ttf")
GOOGLE_API_KEY = None


def load_font(size, bold=False):
    """Carrega a Nunito (fonte variavel) no tamanho/peso pedido."""
    f = ImageFont.truetype(NUNITO_FONT, size)
    try:
        f.set_variation_by_name("Bold" if bold else "Regular")
    except Exception:
        pass
    return f

# ── Sempre usa Gemini (mais barato) ────────────────────────────

def load_env():
    """Carrega chaves do .env."""
    global GOOGLE_API_KEY
    # 1. Tenta GOOGLE_API_KEY no .env local
    env_path = REPO / ".env"
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if line.startswith("GOOGLE_API_KEY="):
                GOOGLE_API_KEY = line.split("=", 1)[1]
    # 2. Tenta GEMINI_API_KEY no .env local
    if not GOOGLE_API_KEY and env_path.exists():
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if line.startswith("GEMINI_API_KEY="):
                GOOGLE_API_KEY = line.split("=", 1)[1]
    # 3. Tenta GEMINI_API_KEY no .hermes/.env
    if not GOOGLE_API_KEY:
        hermes_env = Path.home() / ".hermes" / ".env"
        if hermes_env.exists():
            for line in hermes_env.read_text().splitlines():
                line = line.strip()
                if line.startswith("GEMINI_API_KEY="):
                    GOOGLE_API_KEY = line.split("=", 1)[1]
    # 4. Fallback env var
    if not GOOGLE_API_KEY:
        GOOGLE_API_KEY = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")

load_env()

def get_key():
    return GOOGLE_API_KEY

def cover_resize(img, target_w, target_h):
    """Redimensiona imagem para preencher EXATAMENTE o retangulo (corta bordas)."""
    w, h = img.size
    target_ratio = target_w / target_h
    img_ratio = w / h
    
    if img_ratio > target_ratio:
        new_h = target_h
        new_w = int(new_h * img_ratio)
    else:
        new_w = target_w
        new_h = int(new_w / img_ratio)
    
    img = img.resize((new_w, new_h), Image.LANCZOS)
    
    left = (new_w - target_w) // 2
    top = (new_h - target_h) // 2
    return img.crop((left, top, left + target_w, top + target_h))

def strip_markdown(texto):
    """Remove formatacao markdown inline: **negrito**, *italico*, __sublinhado__."""
    if not texto:
        return texto
    texto = re.sub(r'\*\*(.+?)\*\*', r'\1', texto)  # **negrito**
    texto = re.sub(r'__(.+?)__', r'\1', texto)        # __sublinhado__
    texto = re.sub(r'\*(.+?)\*', r'\1', texto)        # *italico*
    return texto


def wrap_text(texto, font, max_width, draw):
    """Quebra o texto em multiplas linhas para nao ultrapassar max_width (px).

    - Mede a largura com draw.textbbox().
    - Quebra nos espacos.
    - Se uma palavra sozinha for mais larga que max_width, corta a palavra
      caractere a caractere.
    """
    palavras = texto.split()
    if not palavras:
        return [""]

    def largura(s):
        bb = draw.textbbox((0, 0), s, font=font)
        return bb[2] - bb[0]

    linhas = []
    atual = ""
    for palavra in palavras:
        teste = palavra if not atual else f"{atual} {palavra}"
        if largura(teste) <= max_width:
            atual = teste
            continue
        # Nao coube: fecha a linha atual
        if atual:
            linhas.append(atual)
            atual = ""
        # Palavra isolada maior que max_width -> corta caractere a caractere
        if largura(palavra) > max_width:
            pedaco = ""
            for ch in palavra:
                if largura(pedaco + ch) <= max_width or not pedaco:
                    pedaco += ch
                else:
                    linhas.append(pedaco)
                    pedaco = ch
            atual = pedaco
        else:
            atual = palavra
    if atual:
        linhas.append(atual)
    return linhas


def draw_rect(draw, box, radius=0, **kwargs):
    """Retangulo com cantos arredondados (fallback p/ retangulo reto se nao suportado)."""
    if isinstance(box[0], (tuple, list)):
        (x0, y0), (x1, y1) = box
        box = [x0, y0, x1, y1]
    if radius and hasattr(draw, "rounded_rectangle"):
        try:
            draw.rounded_rectangle(box, radius=radius, **kwargs)
            return
        except Exception:
            pass
    draw.rectangle(box, **kwargs)


def gerar_background(prompt_fundo, key):
    """Gera background com Gemini via API Google."""
    prompt = f"Cenario infantil colorido e alegre para um slide de alfabetizacao 16:9 widescreen. {prompt_fundo} IMPORTANTE: Preencher o quadro INTEIRO borda a borda, sem margens. Sem texto, sem letras na imagem. Ilustracao vetorial, cores vibrantes."
    
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "responseModalities": ["IMAGE"]
        }
    }
    
    try:
        resp = requests.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent?key={key}",
            headers={"Content-Type": "application/json"},
            json=payload, timeout=120
        )
        data = resp.json()
        
        if 'candidates' in data:
            for part in data['candidates'][0]['content']['parts']:
                if 'inlineData' in part:
                    img_bytes = base64.b64decode(part['inlineData']['data'])
                    # Google retorna ~1400x768, upscale via PIL
                    from PIL import Image as Img
                    from io import BytesIO
                    img_original = Img.open(BytesIO(img_bytes))
                    img_upscaled = cover_resize(img_original, SLIDE_W, SLIDE_H)
                    buf = BytesIO()
                    img_upscaled.save(buf, format="PNG")
                    return buf.getvalue()
        err_msg = data.get('error', {}).get('message', '')
        if 'quota' in err_msg.lower():
            print(f"⚠️ Quota Google esgotada, pulando slide (sem fallback via Gemini direto)")
            return None
        print(f"⚠️ Resposta inesperada: {err_msg[:100]}")
        return None
    except Exception as e:
        print(f"❌ {e}")
        return None

def aplicar_overlay(bg_img_bytes, num, total, titulo, textos, setas_dir, flip_h=False):
    """Aplica texto e setas sobre o background, garantindo 100% preenchimento."""
    
    bg_temp = f"/tmp/bg_temp_{os.getpid()}.png"
    with open(bg_temp, "wb") as f:
        f.write(bg_img_bytes)
    bg = Image.open(bg_temp).convert("RGBA")
    
    if flip_h:
        bg = bg.transpose(Image.FLIP_LEFT_RIGHT)
    
    bg = cover_resize(bg, SLIDE_W, SLIDE_H)
    
    overlay = Image.new("RGBA", (SLIDE_W, SLIDE_H), (0,0,0,0))
    draw = ImageDraw.Draw(overlay)
    
    font_tit = load_font(int(SLIDE_H*0.07), bold=True)
    font_sub = load_font(int(SLIDE_H*0.05), bold=True)
    font_txt = load_font(int(SLIDE_H*0.04), bold=False)
    font_lbl = load_font(int(SLIDE_H*0.035), bold=True)
    
    # Barra superior (titulo) - fundo semi-transparente com cantos arredondados.
    # Inset lateral pequeno para o arredondamento ficar visivel nas laterais.
    barra_h = int(SLIDE_H * 0.14)
    barra_mx = int(SLIDE_W * 0.03)
    barra_top = int(SLIDE_H * 0.02)
    draw_rect(draw, [(barra_mx, barra_top), (SLIDE_W - barra_mx, barra_top + barra_h)],
              radius=32, fill=(255, 255, 255, 215))
    draw.text((SLIDE_W//2, barra_top + barra_h//2), strip_markdown(titulo),
              fill=(26, 82, 118, 255), font=font_tit, anchor="mm")

    # Bloco de texto
    if textos:
        lh = int(SLIDE_H * 0.06)
        mx = int(SLIDE_W * 0.10)              # margem lateral 10% p/ mais area de leitura
        pad = 20                               # padding interno do retangulo (20px)
        by = (barra_top + barra_h) + int(SLIDE_H * 0.10)  # 10% de espacamento abaixo da barra
        max_w_txt = SLIDE_W - 2*mx - 2*pad     # largura util dentro do retangulo (com padding)

        # Quebra cada texto nas linhas que cabem na largura util
        linhas_render = []  # (linha, font, cor)
        for i, t in enumerate(textos):
            f = font_sub if i == 0 else font_txt
            c = (26, 82, 118, 255) if i == 0 else (44, 62, 80, 255)
            for ln in wrap_text(strip_markdown(t), f, max_w_txt, draw):
                linhas_render.append((ln, f, c))

        bloco_h = len(linhas_render) * lh + 2*pad
        draw_rect(draw, [(mx, by), (SLIDE_W-mx, by+bloco_h)], radius=28,
                  fill=(255, 255, 255, 215), outline=(26, 82, 118, 70), width=2)

        ty = by + pad
        for idx, (ln, f, c) in enumerate(linhas_render):
            draw.text((SLIDE_W//2, ty + lh//2 + idx*lh), ln, fill=c, font=f, anchor="mm")
    
    # Setas
    if setas_dir == "direita":
        sy = int(SLIDE_H * 0.72)
        sw = int(SLIDE_W * 0.45)
        sx_start = SLIDE_W//2 - sw//2
        sx_end = SLIDE_W//2 + sw//2
        thick = int(SLIDE_H * 0.025)
        
        draw.rectangle([(sx_start-30, sy-thick-15), (sx_end+30, sy+thick+15)], fill=(255,255,255,200))
        draw.line([(sx_start, sy), (sx_end, sy)], fill=(76, 175, 80, 220), width=thick)
        asz = int(SLIDE_H * 0.05)
        draw.polygon([(sx_end, sy), (sx_end-asz, sy-asz), (sx_end-asz, sy+asz)], fill=(76, 175, 80, 220))
        
        for texto, x_center in [("ESQUERDA", sx_start), ("DIREITA", sx_end)]:
            lb = font_lbl.getbbox(texto)
            lw = lb[2] - lb[0] + 24 if lb else 160
            lh_lbl = int(SLIDE_H * 0.05)
            lx = x_center - lw // 2
            ly = sy - lh_lbl // 2
            draw.rectangle([(lx, ly), (lx+lw, ly+lh_lbl)], fill=(230, 126, 34, 230), outline=(255,255,255,220), width=2)
            draw.text((x_center, sy), texto, fill=(255, 255, 255, 255), font=font_lbl, anchor="mm")
    
    elif setas_dir == "ambas":
        for x_pct in [0.2, 0.5, 0.8]:
            x = int(SLIDE_W * x_pct)
            y = int(SLIDE_H * 0.65)
            tam = int(SLIDE_H * 0.07)
            draw.rectangle([(x-tam, y-tam), (x+tam, y+tam)], fill=(33, 150, 243, 210))
            draw.text((x, y), "→", fill=(255, 255, 255, 255), font=font_sub, anchor="mm")
    
    # Numero do slide
    draw.rectangle([(SLIDE_W-85, SLIDE_H-50), (SLIDE_W-10, SLIDE_H-10)], fill=(200,200,200,180))
    draw.text((SLIDE_W-47, SLIDE_H-30), f"{num}/{total}", fill=(80,80,80,200), font=font_txt, anchor="mm")
    
    final = Image.alpha_composite(bg, overlay).convert("RGB")
    return final


def parse_slides_from_md(md_texto, codigo):
    """
    Le o slides-ppt.md e extrai secoes de slides.
    Suporta formatos: ---slide--- separador, ## titulo, ### titulo, # titulo
    Retorna lista de dicts: {titulo, textos, prompt_fundo, flip, setas}
    """
    # Primeiro tenta separar por ---slide--- markers
    partes = re.split(r'---slide---', md_texto)
    
    if len(partes) > 1:
        # Formato com separador ---slide---
        slides = []
        for parte in partes:
            parte = parte.strip()
            if not parte:
                continue
            linhas = parte.split('\n')
            titulo = ''
            textos = []
            for linha in linhas:
                linha_strip = linha.strip()
                if linha_strip.startswith('# ') or linha_strip.startswith('## ') or linha_strip.startswith('### '):
                    if not titulo:
                        titulo = linha_strip.lstrip('#').strip()
                    else:
                        textos.append(linha_strip)
                elif linha_strip and not re.match(r'\{+\s*ilustracao', linha_strip):
                    textos.append(linha_strip)
            if titulo:
                slides.append({
                    "titulo": titulo,
                    "textos": textos,
                    "prompt_fundo": None,
                    "flip": False,
                    "setas": None
                })
        if slides:
            return finalizar_slides(slides, codigo)

    # Fallback: APENAS ## (hash duplo) inicia slide; --- separa slides.
    linhas = md_texto.split("\n")
    slides = []
    slide_atual = None

    def novo_slide(titulo=""):
        return {
            "titulo": titulo,
            "textos": [],
            "prompt_fundo": None,
            "flip": False,
            "setas": None
        }

    for linha in linhas:
        linha_strip = linha.strip()

        # Separador --- (travessao triplo) entre slides
        if re.fullmatch(r'-{3,}', linha_strip):
            if slide_atual and slide_atual.get("textos"):
                slides.append(slide_atual)
            slide_atual = None
            continue

        # Inicio de slide: APENAS ## (hash duplo) ou **SLIDE N —**.
        # #, ### e #### NAO iniciam slide -> sao tratados como conteudo.
        if linha_strip.startswith("## ") or \
           re.match(r'\*\*SLIDE\s+\d+\s*[—\-–]+\s*', linha_strip, re.IGNORECASE):
            if slide_atual and slide_atual.get("textos"):
                slides.append(slide_atual)

            titulo = linha_strip.lstrip("#").strip()
            slide_atual = novo_slide(titulo)
        elif linha_strip and not re.match(r'\{+\s*ilustracao', linha_strip):
            # Conteudo (inclui #, ### e #### com os hashes removidos do texto)
            if slide_atual is None:
                slide_atual = novo_slide()
            slide_atual["textos"].append(re.sub(r'^#{1,6}\s*', '', linha_strip))

    # Ultimo slide
    if slide_atual and slide_atual.get("textos"):
        slides.append(slide_atual)

    return finalizar_slides(slides, codigo)


def finalizar_slides(slides, codigo):
    """Gera prompts para cada slide baseado no conteudo."""
    for s in slides:
        titulo = s["titulo"]
        titulo_clean = re.sub(r'^\*?\*?SLIDE\s+\d+\s*[—\-–]+\s*\*?\*?\s*', '', titulo, flags=re.IGNORECASE).strip()
        titulo_clean = re.sub(r'\*+$', '', titulo_clean).strip()

        if titulo_clean and titulo_clean.lower() not in ["título", "capa", "title", "cover"]:
            titulo_usar = titulo_clean
        else:
            primeiro_texto = s["textos"][0] if s["textos"] else "atividade educativa"
            titulo_usar = primeiro_texto.replace("*", "").replace("_", "").strip()[:60]

        s["prompt_fundo"] = (
            f"Cenario infantil colorido e alegre para slide de alfabetizacao. "
            f"Tema: {titulo_usar}. "
            f"Aula {codigo}. "
            f"Estilo ilustracao vetorial, cores vibrantes, fundo preenchido completamente. "
            f"Sem texto, sem letras na imagem."
        )
    return slides


def main():
    key = get_key()
    if not key:
        print("ERRO: Chave Google Gemini nao encontrada (GEMINI_API_KEY)")
        sys.exit(1)
    
    # Pega codigo da aula
    if len(sys.argv) >= 2:
        codigo = sys.argv[1].upper()
    else:
        codigo = "EF01LP01"
    
    print(f"🎨 Gerando slides para {codigo}")
    print(f"{'='*50}")
    
    # Le slides-ppt.md
    md_path = REPO / "aulas-geradas" / codigo / "slides-ppt.md"
    if not md_path.exists():
        print(f"❌ slides-ppt.md nao encontrado em {md_path}")
        sys.exit(1)
    
    md_texto = md_path.read_text(encoding="utf-8")
    slides_config = parse_slides_from_md(md_texto, codigo)
    
    if not slides_config:
        print(f"❌ Nenhum slide encontrado no arquivo")
        sys.exit(1)
    
    # Ajustes especificos para EF01LP01 (setas, flip)
    if codigo == "EF01LP01":
        for s in slides_config:
            t = s["titulo"].lower()
            if "segredo" in t or "começamos" in t:
                s["setas"] = "direita"
            elif "seta" in t or "siga" in t:
                s["setas"] = "ambas"
            elif "trenzinho" in t or "trem" in t:
                s["flip"] = True
                s["setas"] = None
            s["prompt_fundo"] = prompts_especificos.get(s["titulo"], s["prompt_fundo"])
    
    total_slides = len(slides_config)
    print(f"📝 {total_slides} slides detectados")
    
    saida_dir = REPO / f"slides-hibrido-{os.getpid()}"
    saida_dir.mkdir(parents=True, exist_ok=True)
    
    for i, s in enumerate(slides_config):
        num = i + 1
        print(f"  Slide {num}/{total_slides}: {s['titulo'][:40]}...", end=" ", flush=True)
        
        # Gemini (Google direto)
        bg_bytes = gerar_background(s["prompt_fundo"], key)
        if not bg_bytes:
            print("❌")
            continue
        
        slide_img = aplicar_overlay(bg_bytes, num, total_slides, s["titulo"], s["textos"], s["setas"], s["flip"])
        out_path = saida_dir / f"slide_{num:02d}.png"
        slide_img.save(out_path, "PNG", optimize=True)
        print(f"✅ ({out_path.stat().st_size//1024}KB)")
        
        # Delay de 20s entre slides para respeitar rate limit de 4 RPM
        if num < total_slides:
            print(f"    ⏳ aguardando 20s...", end=" ", flush=True)
            time.sleep(20)
    
    # Gera PDF
    print(f"\n📦 Gerando PDF...")
    doc = fitz.open()
    for i, s in enumerate(slides_config):
        path = saida_dir / f"slide_{i+1:02d}.png"
        if path.exists():
            page = doc.new_page(width=SLIDE_W, height=SLIDE_H)
            page.insert_image(fitz.Rect(0, 0, SLIDE_W, SLIDE_H), filename=str(path))
    
    pasta = REPO / "aulas-publicar" / codigo
    pasta.mkdir(parents=True, exist_ok=True)
    pdf_path = pasta / f"{codigo}-slides-hibrido.pdf"
    
    if doc.page_count == 0:
        print(f"⚠️ Nenhum slide gerado, pulando PDF")
        doc.close()
        shutil.rmtree(saida_dir, ignore_errors=True)
        return
    
    doc.save(str(pdf_path))
    doc.close()
    
    print(f"✅ PDF: {pdf_path} ({pdf_path.stat().st_size//1024}KB)")
    
    # Limpa
    shutil.rmtree(saida_dir)
    print(f"\n✨ Concluido!")


# Prompts especificos bem testados para EF01LP01
prompts_especificos = {
    "Para Que Lado a Gente Lê?": "Yellow background, green caterpillar Lele on left pointing right. Stars, clouds, sun. Colorful letters floating. Full frame.",
    "Segredo da Lelê": "Blue sky background, green caterpillar Lele on left, path of flowers going from left to right. Clouds, sun.",
    "Começamos na ESQUERDA!": "Blue sky background, green caterpillar Lele on left, path of flowers going from left to right. Clouds, sun.",
    "Meu Dedinho Leitor!": "Light blue background, child's hand on left pointing right. Book on right. Stars, crayons.",
    "Cantando Aprendemos!": "Pink background, musical notes everywhere, green caterpillar Lele with microphone. Colorful elements.",
    "Siga as Setas!": "Orange background, colorful footprints going left to right across full frame. Green caterpillar Lele on left pointing right.",
    "Trenzinho das Letrinhas!": "Green field, colorful toy steam train with 4 cars, green caterpillar Lele as conductor waving. Sun, clouds, flowers, heart-shaped smoke.",
    "Hora da Folhinha!": "Purple background, paper with dotted lines, green caterpillar Lele holding pencil. Crayons and colored pencils.",
    "Parabéns, Super Leitores!": "Rainbow background, confetti, balloons, stars everywhere. Green caterpillar Lele with golden trophy and party hat in center.",
}


if __name__ == "__main__":
    main()