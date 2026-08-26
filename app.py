import streamlit as st
import json
import requests
import os
import re
import textwrap
import asyncio
import numpy as np
import PIL.Image
import PIL.ImageDraw
import PIL.ImageFont
import uuid
import threading
import queue
import time
import shutil
import traceback
from pathlib import Path
from dotenv import load_dotenv

if not hasattr(PIL.Image, 'ANTIALIAS'):
    PIL.Image.ANTIALIAS = PIL.Image.LANCZOS

load_dotenv()

try:
    from moviepy.editor import VideoFileClip, concatenate_videoclips, AudioFileClip, ImageClip, CompositeVideoClip, VideoClip
    MOVIEPY_V1 = True
except ImportError:
    try:
        from moviepy import VideoFileClip, concatenate_videoclips, AudioFileClip, ImageClip, CompositeVideoClip, VideoClip
        MOVIEPY_V1 = False
    except ImportError:
        st.error("Error: MoviePy no está instalado adecuadamente en el entorno.")

try:
    import edge_tts
    EDGE_TTS_AVAILABLE = True
except ImportError:
    EDGE_TTS_AVAILABLE = False

try:
    from gtts import gTTS
    GTTS_AVAILABLE = True
except ImportError:
    GTTS_AVAILABLE = False

VOICES_CONFIG = {
    "🇲🇽 Español México - Jorge (Masculino Neural)": {"code": "es-MX-JorgeNeural", "lang": "Spanish", "flag": "🇲🇽"},
    "🇲🇽 Español México - Dalia (Femenino Neural)": {"code": "es-MX-DaliaNeural", "lang": "Spanish", "flag": "🇲🇽"},
    "🇪🇸 Español España - Álvaro (Masculino Neural)": {"code": "es-ES-AlvaroNeural", "lang": "Spanish", "flag": "🇪🇸"},
    "🇪🇸 Español España - Elvira (Femenino Neural)": {"code": "es-ES-ElviraNeural", "lang": "Spanish", "flag": "🇪🇸"},
    "🇺🇸 Español EE.UU. - Alonso (Masculino Neural)": {"code": "es-US-AlonsoNeural", "lang": "Spanish", "flag": "🇺🇸"},
    "🇺🇸 Español EE.UU. - Paloma (Femenino Neural)": {"code": "es-US-PalomaNeural", "lang": "Spanish", "flag": "🇺🇸"},
    "🇺🇸 English (US) - Guy (Male Neural)": {"code": "en-US-GuyNeural", "lang": "English", "flag": "🇺🇸"},
    "🇺🇸 English (US) - Jenny (Female Neural)": {"code": "en-US-JennyNeural", "lang": "English", "flag": "🇺🇸"},
    "🇬🇧 English (UK) - Ryan (Male Neural)": {"code": "en-GB-RyanNeural", "lang": "English", "flag": "🇬🇧"},
    "🇬🇧 English (UK) - Sonia (Female Neural)": {"code": "en-GB-SoniaNeural", "lang": "English", "flag": "🇬🇧"},
}

PRESETS_FORMATO = {
    "📱 TikTok / Reels / Shorts (Vertical 9:16)": {"res": (1080, 1920), "orient": "portrait", "icon": "📱"},
    "🎬 YouTube / Documental (Horizontal 16:9)": {"res": (1920, 1080), "orient": "landscape", "icon": "🎬"},
    "🟦 Post Cuadrado / LinkedIn (1:1)": {"res": (1080, 1080), "orient": "square", "icon": "🟦"},
    "📽️ Cine / Ultra-Wide (21:9)": {"res": (2560, 1080), "orient": "landscape", "icon": "📽️"}
}

PRESETS_CONTENIDO = [
    "🔥 Viral Trends & Datos Curiosos (Ritmo Rápido)",
    "💪 Motivación, Fitness & Mindset",
    "🚀 Tecnología, IA & Futuro",
    "💼 Negocios, Finanzas & Cripto",
    "🕵️‍♂️ Misterio, Historias & Relatos",
    "🧘 Meditación, Paisajes & Relax",
    "Personalizado"
]

def safe_subclip(clip, start, duration):
    max_duration = clip.duration if clip.duration is not None else duration
    end = min(start + duration, max_duration)
    if end <= start: end = max_duration
    if hasattr(clip, "subclipped"): return clip.subclipped(start, end)
    elif hasattr(clip, "subclip"): return clip.subclip(start, end)
    return clip

def safe_resize(clip, target_resolution):
    w_target, h_target = target_resolution
    if hasattr(clip, "resized"): return clip.resized(new_size=(w_target, h_target))
    elif hasattr(clip, "resize"): return clip.resize(newsize=(w_target, h_target))
    return clip

def agregar_subtitulos_a_clip(clip, texto_subtitulo, target_resolution, fontsize=42):
    if not texto_subtitulo: return clip
    w, h = target_resolution
    sub_img = PIL.Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw = PIL.ImageDraw.Draw(sub_img)
    font = None
    font_paths = ["/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", "DejaVuSans-Bold.ttf", "arial.ttf"]
    for fp in font_paths:
        try:
            font = PIL.ImageFont.truetype(fp, fontsize)
            break
        except Exception: pass
    if not font: font = PIL.ImageFont.load_default()
    max_char_width = 25 if w <= 1080 else 40
    lines = textwrap.wrap(texto_subtitulo, width=max_char_width)
    full_text = "\n".join(lines)
    bbox = draw.multiline_textbbox((0, 0), full_text, font=font, align="center")
    text_w = bbox[2] - bbox[0]
    text_h = bbox[3] - bbox[1]
    x = (w - text_w) / 2
    y = h - text_h - int(h * 0.15)
    padding = 20
    draw.rectangle([max(0, x - padding), max(0, y - padding), min(w, x + text_w + padding), min(h, y + text_h + padding)], fill=(10, 15, 30, 200))
    draw.rectangle([max(0, x - padding), max(0, y - padding), min(w, x + text_w + padding), min(h, y + text_h + padding)], outline=(255, 75, 75, 255), width=3)
    offset = 2
    for dx, dy in [(-offset, -offset), (offset, -offset), (-offset, offset), (offset, offset)]:
        draw.multiline_text((x + dx, y + dy), full_text, font=font, fill=(0, 0, 0, 255), align="center")
    draw.multiline_text((x, y), full_text, font=font, fill=(255, 255, 255, 255), align="center")
    arr = np.array(sub_img)
    img_clip = ImageClip(arr).set_duration(clip.duration)
    return CompositeVideoClip([clip, img_clip])

def generar_audio_tts_isolated(texto, voice_code, audio_filename):
    if not texto: return None
    if os.path.exists(audio_filename):
        try: os.remove(audio_filename)
        except Exception: pass
    if EDGE_TTS_AVAILABLE:
        try:
            async def _save_audio():
                communicate = edge_tts.Communicate(texto, voice_code)
                await communicate.save(audio_filename)
            asyncio.run(_save_audio())
            if os.path.exists(audio_filename) and os.path.getsize(audio_filename) > 100:
                return audio_filename
        except Exception as e: print(f"Edge-TTS Error: {e}")
    if GTTS_AVAILABLE:
        try:
            tts = gTTS(text=texto, lang="es", slow=False)
            tts.save(audio_filename)
            return audio_filename
        except Exception: return None
    return None

def descargar_clip_pexels_isolated(query, pexels_key, duracion, index, job_workspace, orientation="landscape"):
    if not pexels_key: return None, None, "No Pexels API Key"
    headers = {"Authorization": pexels_key}
    url = f"https://api.pexels.com/videos/search?query={query}&per_page=3&orientation={orientation}"
    try:
        res = requests.get(url, headers=headers, timeout=15)
        if res.status_code != 200: return None, None, f"Error Pexels API ({res.status_code})"
        data = res.json()
        if data.get("videos") and len(data["videos"]) > 0:
            video_files = data["videos"][0]["video_files"]
            hd_file = next((f for f in video_files if f.get("quality") == "hd"), video_files[0])
            video_url = hd_file["link"]
            filename = str(job_workspace / f"clip_{index}.mp4")
            v_res = requests.get(video_url, timeout=30)
            with open(filename, "wb") as f: f.write(v_res.content)
            return filename, video_url, None
        else: return None, None, f"No se encontró metraje para '{query}'"
    except Exception as e: return None, None, str(e)

def generar_clip_fallback_imagen_isolated(query, duracion, index, target_res, job_workspace):
    w, h = target_res
    filename = str(job_workspace / f"fallback_{index}.jpg")
    try:
        clean_prompt = requests.utils.quote(f"cinematic photo of {query}, 8k, detailed, photorealistic, dramatic lighting")
        img_url = f"https://image.pollinations.ai/prompt/{clean_prompt}?width={w}&height={h}&nologo=true&seed={index+100}"
        res = requests.get(img_url, timeout=10)
        if res.status_code == 200:
            with open(filename, "wb") as f: f.write(res.content)
            return filename, None
    except Exception: pass
    img = PIL.Image.new("RGB", (w, h), color=(15, 23, 42))
    draw = PIL.ImageDraw.Draw(img)
    draw.rectangle([40, 40, w - 40, h - 40], outline=(124, 58, 237), width=6)
    img.save(filename)
    return filename, None

RENDER_DIR = Path("renders")
JOBS_DIR = RENDER_DIR / "jobs"
OUTPUT_DIR = RENDER_DIR / "output"
TEMP_DIR = RENDER_DIR / "temp"

for d in [RENDER_DIR, JOBS_DIR, OUTPUT_DIR, TEMP_DIR]:
    d.mkdir(parents=True, exist_ok=True)

class RenderQueueManager:
    def __init__(self):
        self.queue = queue.Queue()
        self.is_running = True
        self.worker_thread = threading.Thread(target=self._worker_loop, daemon=True)
        self.worker_thread.start()
        self._recover_pending_jobs()

    def _recover_pending_jobs(self):
        jobs = self.list_jobs()
        for job in reversed(jobs):
            if job.get("status") in ["queued", "rendering"]:
                job["status"] = "queued"
                self.save_job(job)
                self.queue.put(job["job_id"])

    def add_job(self, job_data):
        job_id = f"job_{int(time.time())}_{uuid.uuid4().hex[:6]}"
        output_file = str(OUTPUT_DIR / f"{job_id}.mp4")
        job_info = {
            "job_id": job_id, "status": "queued", "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "completed_at": None, "progress": 0.0, "current_scene": 0, "total_scenes": len(job_data.get("escenas", [])),
            "status_message": "En cola para renderizar...", "title": job_data.get("titulo_video", "Sin Título"),
            "nicho": job_data.get("nicho", ""), "voice_code": job_data.get("voice_code", ""),
            "voz_name": job_data.get("voz_name", ""), "target_res": job_data.get("target_res", [1080, 1920]),
            "pexels_orientation": job_data.get("pexels_orientation", "portrait"), "duracion_minima": job_data.get("duracion_minima", 3),
            "incluir_narracion": job_data.get("incluir_narracion", True), "incluir_subtitulos": job_data.get("incluir_subtitulos", True),
            "pexels_api_key": job_data.get("pexels_api_key", ""), "escenas": job_data.get("escenas", []),
            "output_path": output_file, "error": None
        }
        self.save_job(job_info)
        self.queue.put(job_id)
        return job_id

    def save_job(self, job_info):
        job_file = JOBS_DIR / f"{job_info['job_id']}.json"
        with open(job_file, "w", encoding="utf-8") as f:
            json.dump(job_info, f, ensure_ascii=False, indent=2)

    def load_job(self, job_id):
        job_file = JOBS_DIR / f"{job_id}.json"
        if job_file.exists():
            try:
                with open(job_file, "r", encoding="utf-8") as f: return json.load(f)
            except Exception: pass
        return None

    def list_jobs(self):
        jobs = []
        for job_file in sorted(JOBS_DIR.glob("*.json"), key=os.path.getmtime, reverse=True):
            try:
                with open(job_file, "r", encoding="utf-8") as f: jobs.append(json.load(f))
            except Exception: pass
        return jobs

    def delete_job(self, job_id):
        job_file = JOBS_DIR / f"{job_id}.json"
        output_file = OUTPUT_DIR / f"{job_id}.mp4"
        temp_workspace = TEMP_DIR / job_id
        if job_file.exists():
            try: os.remove(job_file)
            except Exception: pass
        if output_file.exists():
            try: os.remove(output_file)
            except Exception: pass
        if temp_workspace.exists():
            try: shutil.rmtree(temp_workspace, ignore_errors=True)
            except Exception: pass

    def _worker_loop(self):
        while self.is_running:
            try:
                job_id = self.queue.get(timeout=3)
                job_info = self.load_job(job_id)
                if job_info and job_info.get("status") == "queued":
                    self._process_job(job_info)
                self.queue.task_done()
            except queue.Empty: time.sleep(1)
            except Exception as e:
                print(f"Queue Worker Exception: {e}")
                time.sleep(2)

    def _process_job(self, job_info):
        job_id = job_info["job_id"]
        job_workspace = TEMP_DIR / job_id
        job_workspace.mkdir(parents=True, exist_ok=True)
        job_info["status"] = "rendering"
        job_info["status_message"] = "Iniciando renderizado..."
        job_info["progress"] = 0.05
        self.save_job(job_info)
        escenas = job_info.get("escenas", [])
        total_escenas = len(escenas)
        target_res = tuple(job_info.get("target_res", (1080, 1920)))
        duracion_minima = job_info.get("duracion_minima", 3)
        voice_code = job_info.get("voice_code", "es-MX-JorgeNeural")
        pexels_api_key = job_info.get("pexels_api_key", "")
        pexels_orientation = job_info.get("pexels_orientation", "portrait")
        incluir_narracion = job_info.get("incluir_narracion", True)
        incluir_subtitulos = job_info.get("incluir_subtitulos", True)
        nicho = job_info.get("nicho", "General")
        clips = []
        archivos_temp_video = []
        archivos_temp_audio = []
        try:
            for i, escena in enumerate(escenas):
                job_info["current_scene"] = i + 1
                job_info["status_message"] = f"Procesando escena {i+1}/{total_escenas}..."
                job_info["progress"] = min(0.9, (i + 0.1) / max(1, total_escenas))
                self.save_job(job_info)
                query = escena.get("query_video", nicho)
                texto_narracion = escena.get("texto_narracion", "")
                audio_clip = None
                duracion_locucion = duracion_minima
                if incluir_narracion and texto_narracion:
                    audio_filename = str(job_workspace / f"audio_{i}.mp3")
                    audio_path = generar_audio_tts_isolated(texto_narracion, voice_code, audio_filename)
                    if audio_path and os.path.exists(audio_path):
                        archivos_temp_audio.append(audio_path)
                        audio_clip = AudioFileClip(audio_path)
                        duracion_locucion = max(duracion_minima, audio_clip.duration + 0.3)
                fname_video, url_v, err = descargar_clip_pexels_isolated(query, pexels_api_key, duracion_locucion, i, job_workspace, orientation=pexels_orientation)
                if not fname_video: fname_video, url_v, err = descargar_clip_pexels_isolated(nicho, pexels_api_key, duracion_locucion, i, job_workspace, orientation=pexels_orientation)
                if not fname_video: fname_video, err_fb = generar_clip_fallback_imagen_isolated(query, duracion_locucion, i, target_res, job_workspace)
                if fname_video and os.path.exists(fname_video):
                    archivos_temp_video.append(fname_video)
                    if fname_video.endswith(".jpg") or fname_video.endswith(".png"): clip_src = ImageClip(fname_video).set_duration(duracion_locucion)
                    else: clip_src = VideoFileClip(fname_video)
                    if clip_src.duration and clip_src.duration < duracion_locucion:
                        n_repetir = int(duracion_locucion / clip_src.duration) + 1
                        clip_extendido = concatenate_videoclips([clip_src] * n_repetir)
                        clip_cortado = safe_subclip(clip_extendido, 0, duracion_locucion)
                    else: clip_cortado = safe_subclip(clip_src, 0, duracion_locucion)
                    clip_resized = safe_resize(clip_cortado, target_res)
                    if audio_clip:
                        if hasattr(clip_resized, "set_audio"): clip_resized = clip_resized.set_audio(audio_clip)
                        elif hasattr(clip_resized, "with_audio"): clip_resized = clip_resized.with_audio(audio_clip)
                    if incluir_subtitulos and texto_narracion: clip_resized = agregar_subtitulos_a_clip(clip_resized, texto_narracion, target_res)
                    clips.append(clip_resized)
                job_info["progress"] = min(0.95, (i + 1) / max(1, total_escenas))
                self.save_job(job_info)
            if clips:
                job_info["status_message"] = "Ensamblando y renderizando archivo MP4 final..."
                job_info["progress"] = 0.96
                self.save_job(job_info)
                video_final = concatenate_videoclips(clips, method="compose")
                output_path = job_info["output_path"]
                video_final.write_videofile(output_path, fps=24, codec="libx264", audio_codec="aac" if incluir_narracion else None, preset="ultrafast", threads=4, logger=None)
                video_final.close()
                for c in clips:
                    try: c.close()
                    except Exception: pass
                job_info["status"] = "completed"
                job_info["status_message"] = "¡Renderizado finalizado con éxito!"
                job_info["progress"] = 1.0
                job_info["completed_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
                self.save_job(job_info)
            else:
                job_info["status"] = "failed"
                job_info["status_message"] = "Error: No se pudieron procesar clips de video."
                job_info["error"] = "No clips generated."
                self.save_job(job_info)
        except Exception as e:
            err_trace = traceback.format_exc()
            job_info["status"] = "failed"
            job_info["status_message"] = f"Error en renderizado: {str(e)}"
            job_info["error"] = err_trace
            self.save_job(job_info)
        finally:
            try: shutil.rmtree(job_workspace, ignore_errors=True)
            except Exception: pass

@st.cache_resource
def get_render_queue(): return RenderQueueManager()
render_queue_mgr = get_render_queue()

def parse_groq_json(raw_text):
    if "</think>" in raw_text: raw_text = raw_text.split("</think>")[-1]
    match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw_text, re.DOTALL)
    if match: return json.loads(match.group(1))
    start_idx = raw_text.find("{")
    end_idx = raw_text.rfind("}")
    if start_idx != -1 and end_idx != -1 and end_idx > start_idx: return json.loads(raw_text[start_idx:end_idx+1])
    return json.loads(raw_text)

def generar_guion_groq(nicho, num_escenas, idioma, api_key, custom_prompt=""):
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    instrucciones_extra = f"\nINSTRUCCIONES ADICIONALES: {custom_prompt}\n" if custom_prompt.strip() else ""
    prompt = f"Crea un guion estructurado en formato JSON para un video sobre el tema '{nicho}'. IDIOMA: {idioma}. {instrucciones_extra} El arreglo escenas DEBE contener exactamente {num_escenas} objetos. Devuelve SOLO un JSON valido: {{\"titulo\": \"...\", \"escenas\": [{{\"id\": 1, \"query_video\": \"...\", \"texto_narracion\": \"...\"}}]}}"
    modelos_candidatos = ["qwen/qwen3.6-27b", "groq/compound", "groq/compound-mini", "openai/gpt-oss-20b", "llama-3.3-70b-versatile", "llama3-70b-8192"]
    try:
        models_res = requests.get("https://api.groq.com/openai/v1/models", headers=headers, timeout=10)
        if models_res.status_code == 200:
            active_models = [m["id"] for m in models_res.json().get("data", []) if "whisper" not in m["id"] and "guard" not in m["id"]]
            if active_models:
                preferred = [m for m in ["qwen/qwen3.6-27b", "groq/compound", "openai/gpt-oss-20b", "llama-3.3-70b-versatile"] if m in active_models]
                modelos_candidatos = preferred + [m for m in active_models if m not in preferred]
    except Exception: pass
    last_error = ""
    for model_name in modelos_candidatos:
        payload = {"model": model_name, "messages": [{"role": "system", "content": f"Eres un director experto de contenido viral. Respondes exclusivamente en JSON. Narración en {idioma}."}, {"role": "user", "content": prompt}], "temperature": 0.7}
        try:
            res = requests.post("https://api.groq.com/openai/v1/chat/completions", headers=headers, json=payload, timeout=30)
            if res.status_code == 200:
                raw_content = res.json()['choices'][0]['message']['content']
                return parse_groq_json(raw_content)
            else: last_error = f"Modelo '{model_name}': {res.text}"
        except Exception as e: last_error = str(e)
    raise Exception(f"No se pudo generar con Groq. {last_error}")

def generar_guion(nicho, num_escenas, idioma, groq_key, custom_prompt=""):
    if not groq_key.strip(): raise Exception("Introduce tu Groq API Key.")
    return generar_guion_groq(nicho, num_escenas, idioma, groq_key, custom_prompt)

st.set_page_config(page_title="AI Studio 24/7", page_icon="🎬", layout="wide")
st.markdown("<h1 style='text-align: center; color: #7C3AED;'>🎬 AI Video Studio Pro (24/7 Async Render)</h1>", unsafe_allow_html=True)

with st.sidebar:
    st.title("Studio Controls")
    default_groq = os.getenv("GROQ_API_KEY", "")
    default_pexels = os.getenv("PEXELS_API_KEY", "")
    groq_api_key = st.text_input("Groq API Key", value=default_groq, type="password")
    pexels_api_key = st.text_input("Pexels API Key", value=default_pexels, type="password")
    formato_sel = st.selectbox("Plataforma", list(PRESETS_FORMATO.keys()), index=0)
    preset_fmt = PRESETS_FORMATO[formato_sel]
    target_res = preset_fmt["res"]
    pexels_orientation = preset_fmt["orient"]
    voz_sel = st.selectbox("Voz Neural", list(VOICES_CONFIG.keys()), index=0)
    voice_info = VOICES_CONFIG[voz_sel]
    voice_code = voice_info["code"]
    target_language = voice_info["lang"]
    estilo_sel = st.selectbox("Nicho / Estilo", PRESETS_CONTENIDO, index=0)
    nicho = st.text_input("Tema", "Tecnología e IA") if estilo_sel == "Personalizado" else estilo_sel
    num_escenas = st.slider("Escenas", 3, 40, 8)
    duracion_minima = st.slider("Duración Mínima (s)", 2, 10, 3)
    incluir_narracion = st.checkbox("Voz en Off Neural", value=True)
    incluir_subtitulos = st.checkbox("Subtítulos Cinemáticos", value=True)

if "titulo_video" not in st.session_state: st.session_state["titulo_video"] = "Video sobre " + nicho
if "escenas" not in st.session_state: st.session_state["escenas"] = []

tab1, tab2, tab3 = st.tabs(["📜 1. Editor de Guion", "⚡ 2. Estado de Renderizado 24/7", "📺 3. Galería de Videos"])

with tab1:
    st.subheader("✍️ Guion del Video")
    custom_prompt = st.text_area("Prompt Adicional", value="", placeholder="Instrucciones para la IA...")
    col_btn1, col_btn2 = st.columns([2, 1])
    with col_btn1:
        if st.button("🧠 Generar Guion con Groq IA", type="primary", use_container_width=True):
            if not groq_api_key: st.error("Ingresa tu Groq API Key.")
            else:
                with st.spinner("Generando guion con IA..."):
                    try:
                        guion = generar_guion(nicho, num_escenas, target_language, groq_api_key, custom_prompt=custom_prompt)
                        st.session_state["titulo_video"] = guion.get("titulo", f"Video sobre {nicho}")
                        st.session_state["escenas"] = guion.get("escenas", [])
                        st.success("¡Guion generado con éxito!")
                    except Exception as e: st.error(str(e))
    with col_btn2:
        if st.button("➕ Añadir Escena", use_container_width=True):
            st.session_state["escenas"].append({"id": len(st.session_state["escenas"])+1, "query_video": nicho, "texto_narracion": "Nueva línea"})
            st.rerun()

    st.session_state["titulo_video"] = st.text_input("Título", value=st.session_state["titulo_video"])
    for idx, escena in enumerate(st.session_state["escenas"]):
        col_esc1, col_esc2, col_del = st.columns([3, 3, 1])
        with col_esc1: st.session_state["escenas"][idx]["query_video"] = st.text_input(f"Pexels #{idx+1}", value=escena.get("query_video", ""), key=f"q_{idx}")
        with col_esc2: st.session_state["escenas"][idx]["texto_narracion"] = st.text_area(f"Narración #{idx+1}", value=escena.get("texto_narracion", ""), key=f"n_{idx}", height=68)
        with col_del:
            if st.button("🗑️", key=f"d_{idx}"):
                st.session_state["escenas"].pop(idx)
                st.rerun()

    if st.session_state["escenas"]:
        if st.button("🚀 Encolar Renderizado 24/7", type="primary", use_container_width=True):
            if not pexels_api_key: st.error("Ingresa tu Pexels API Key.")
            else:
                job_data = {"titulo_video": st.session_state["titulo_video"], "nicho": nicho, "escenas": st.session_state["escenas"], "voice_code": voice_code, "voz_name": voz_sel, "target_res": list(target_res), "pexels_orientation": pexels_orientation, "duracion_minima": duracion_minima, "incluir_narracion": incluir_narracion, "incluir_subtitulos": incluir_subtitulos, "pexels_api_key": pexels_api_key}
                j_id = render_queue_mgr.add_job(job_data)
                st.success(f"¡Video enviado a la cola 24/7! ID: {j_id}")

with tab2:
    st.subheader("⚡ Estado de Renderizado en Segundo Plano")
    if st.button("🔄 Actualizar"): st.rerun()
    jobs_list = render_queue_mgr.list_jobs()
    for job in jobs_list:
        j_id = job["job_id"]
        with st.expander(f"🎬 [{job['status'].upper()}] {job.get('title')} ({j_id})", expanded=(job['status'] in ["rendering", "queued"])):
            st.write(f"Estado: {job.get('status_message')}")
            if job['status'] == "rendering": st.progress(job.get('progress', 0.0))
            elif job['status'] == "completed":
                st.progress(1.0)
                if os.path.exists(job.get('output_path', '')):
                    st.video(job['output_path'])
            elif job['status'] == "failed": st.error(job.get('error'))
            if st.button("🗑️ Borrar", key=f"del_j_{j_id}"):
                render_queue_mgr.delete_job(j_id)
                st.rerun()

with tab3:
    st.subheader("📺 Galería de Videos Finales")
    video_files = sorted(OUTPUT_DIR.glob("*.mp4"), key=os.path.getmtime, reverse=True)
    for v_path in video_files:
        st.video(str(v_path))
