import streamlit as st
import requests
import os
import subprocess
import tempfile
import json
import time
from pathlib import Path

st.set_page_config(
    page_title="🎬 StreamEncoder",
    page_icon="🎬",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Bebas+Neue&family=DM+Mono:wght@300;400;500&family=DM+Sans:wght@300;400;500;600&display=swap');

:root {
    --bg:        #0a0a0c;
    --bg2:       #111116;
    --bg3:       #18181f;
    --border:    #2a2a35;
    --accent:    #e63946;
    --accent2:   #ff6b35;
    --gold:      #f4c542;
    --text:      #e8e6e0;
    --muted:     #666;
    --green:     #4ade80;
    --red:       #f87171;
}

html, body, [class*="css"] {
    font-family: 'DM Sans', sans-serif;
    background: var(--bg) !important;
    color: var(--text);
}

/* Sidebar */
[data-testid="stSidebar"] {
    background: var(--bg2) !important;
    border-right: 1px solid var(--border);
}

/* Main title */
.hero-title {
    font-family: 'Bebas Neue', sans-serif;
    font-size: 4rem;
    letter-spacing: 0.08em;
    line-height: 1;
    background: linear-gradient(135deg, #e63946 0%, #ff6b35 60%, #f4c542 100%);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    background-clip: text;
    margin: 0;
}
.hero-sub {
    font-family: 'DM Mono', monospace;
    font-size: 0.78rem;
    color: var(--muted);
    letter-spacing: 0.15em;
    text-transform: uppercase;
    margin-top: 4px;
    margin-bottom: 2rem;
}

/* Spec cards */
.spec-grid {
    display: grid;
    grid-template-columns: repeat(5, 1fr);
    gap: 10px;
    margin: 1.2rem 0;
}
.spec-card {
    background: var(--bg3);
    border: 1px solid var(--border);
    border-radius: 10px;
    padding: 14px 12px;
    text-align: center;
}
.spec-card .label {
    font-family: 'DM Mono', monospace;
    font-size: 0.65rem;
    color: var(--muted);
    letter-spacing: 0.12em;
    text-transform: uppercase;
    margin-bottom: 6px;
}
.spec-card .value {
    font-family: 'Bebas Neue', sans-serif;
    font-size: 1.15rem;
    letter-spacing: 0.05em;
    color: var(--gold);
}

/* URL input box */
.url-card {
    background: var(--bg3);
    border: 1px solid var(--border);
    border-radius: 12px;
    padding: 1.4rem;
    margin-bottom: 1rem;
}

/* Result cards */
.result-ok {
    background: #0d2418;
    border: 1px solid #1a4d30;
    border-radius: 12px;
    padding: 1rem 1.4rem;
    margin-bottom: 8px;
    font-family: 'DM Mono', monospace;
    font-size: 0.82rem;
    color: var(--green);
}
.result-err {
    background: #250d0d;
    border: 1px solid #4d1a1a;
    border-radius: 12px;
    padding: 1rem 1.4rem;
    margin-bottom: 8px;
    font-family: 'DM Mono', monospace;
    font-size: 0.82rem;
    color: var(--red);
}
.info-box {
    background: #0d1825;
    border: 1px solid #1a3050;
    border-radius: 10px;
    padding: 0.9rem 1.2rem;
    color: #60a5fa;
    font-size: 0.84rem;
    margin-bottom: 1rem;
}
.warn-box {
    background: #1f1800;
    border: 1px solid #4d3a00;
    border-radius: 10px;
    padding: 0.9rem 1.2rem;
    color: #fbbf24;
    font-size: 0.84rem;
    margin-bottom: 1rem;
}

/* Stat row */
.stat-row {
    display: flex;
    gap: 16px;
    margin: 1rem 0;
    flex-wrap: wrap;
}
.stat-item {
    background: var(--bg3);
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 8px 14px;
    font-family: 'DM Mono', monospace;
    font-size: 0.75rem;
    color: var(--muted);
}
.stat-item span {
    color: var(--text);
    font-weight: 500;
}

/* Buttons */
.stButton > button {
    background: linear-gradient(135deg, var(--accent), var(--accent2)) !important;
    color: #fff !important;
    border: none !important;
    border-radius: 8px !important;
    font-family: 'Bebas Neue', sans-serif !important;
    font-size: 1.1rem !important;
    letter-spacing: 0.08em !important;
    padding: 0.5rem 1.2rem !important;
    transition: opacity 0.2s !important;
}
.stButton > button:hover { opacity: 0.85 !important; }

/* Progress */
.encode-progress {
    font-family: 'DM Mono', monospace;
    font-size: 0.78rem;
    color: var(--muted);
    margin-top: 4px;
}

/* Divider */
hr { border-color: var(--border) !important; }
</style>
""", unsafe_allow_html=True)


# ─────────────────────────────────────────────
# AUTO-INSTALL FFMPEG
# ─────────────────────────────────────────────
@st.cache_resource(show_spinner=False)
def ensure_ffmpeg():
    if subprocess.run(["which","ffmpeg"], capture_output=True).returncode == 0:
        return True
    for cmd in [["apt-get","install","-y","ffmpeg"],["apt","install","-y","ffmpeg"]]:
        try:
            if subprocess.run(cmd, capture_output=True).returncode == 0:
                return True
        except FileNotFoundError:
            pass
    return False


# ─────────────────────────────────────────────
# DROPBOX HELPERS
# ─────────────────────────────────────────────
DBX_API     = "https://api.dropboxapi.com/2"
DBX_CONTENT = "https://content.dropboxapi.com/2"

def dbx_get_access_token(app_key, app_secret, refresh_token):
    try:
        r = requests.post("https://api.dropbox.com/oauth2/token",
            data={"grant_type":"refresh_token","refresh_token":refresh_token,
                  "client_id":app_key,"client_secret":app_secret}, timeout=15)
        d = r.json()
        return d.get("access_token"), d.get("error_description", d.get("error"))
    except Exception as e:
        return None, str(e)

def dbx_verify(token):
    try:
        r = requests.post(f"{DBX_API}/users/get_current_account",
            headers={"Authorization":f"Bearer {token}"}, timeout=10)
        return r.json() if r.status_code == 200 else None
    except: return None

def dbx_list_names(token, folder):
    try:
        r = requests.post(f"{DBX_API}/files/list_folder",
            headers={"Authorization":f"Bearer {token}","Content-Type":"application/json"},
            json={"path":folder,"recursive":False}, timeout=15)
        return {e["name"] for e in r.json().get("entries",[])} if r.status_code==200 else set()
    except: return set()

def unique_name(filename, existing):
    if filename not in existing: return filename
    stem, ext = Path(filename).stem, Path(filename).suffix
    i = 1
    while f"{stem}_{i}{ext}" in existing: i += 1
    return f"{stem}_{i}{ext}"

def dbx_upload(token, file_path, folder, filename):
    existing   = dbx_list_names(token, folder)
    final_name = unique_name(filename, existing)
    dest       = (folder + "/" + final_name).replace("//", "/")
    size       = os.path.getsize(file_path)
    CHUNK      = 148 * 1024 * 1024

    try:
        if size <= CHUNK:
            with open(file_path, "rb") as f:
                r = requests.post(f"{DBX_CONTENT}/files/upload",
                    headers={"Authorization":f"Bearer {token}",
                             "Dropbox-API-Arg":json.dumps({"path":dest,"mode":"add","autorename":False}),
                             "Content-Type":"application/octet-stream"},
                    data=f, timeout=600)
            if r.status_code != 200:
                return False, final_name, f"Upload error {r.status_code}: {r.text[:200]}", None
        else:
            with open(file_path, "rb") as f:
                chunk = f.read(CHUNK)
                r = requests.post(f"{DBX_CONTENT}/files/upload_session/start",
                    headers={"Authorization":f"Bearer {token}",
                             "Dropbox-API-Arg":'{"close":false}',
                             "Content-Type":"application/octet-stream"},
                    data=chunk, timeout=600)
                if r.status_code != 200:
                    return False, final_name, f"Session start error: {r.text[:200]}", None
                sid = r.json()["session_id"]; offset = len(chunk)
                while True:
                    chunk = f.read(CHUNK)
                    if not chunk: break
                    requests.post(f"{DBX_CONTENT}/files/upload_session/append_v2",
                        headers={"Authorization":f"Bearer {token}",
                                 "Dropbox-API-Arg":json.dumps({"cursor":{"session_id":sid,"offset":offset},"close":False}),
                                 "Content-Type":"application/octet-stream"},
                        data=chunk, timeout=600)
                    offset += len(chunk)
                r = requests.post(f"{DBX_CONTENT}/files/upload_session/finish",
                    headers={"Authorization":f"Bearer {token}",
                             "Dropbox-API-Arg":json.dumps({"cursor":{"session_id":sid,"offset":offset},"commit":{"path":dest,"mode":"add"}}),
                             "Content-Type":"application/octet-stream"},
                    data=b"", timeout=600)
                if r.status_code != 200:
                    return False, final_name, f"Session finish error: {r.text[:200]}", None

        r2 = requests.post(f"{DBX_API}/sharing/create_shared_link_with_settings",
            headers={"Authorization":f"Bearer {token}","Content-Type":"application/json"},
            json={"path":dest,"settings":{"requested_visibility":"public"}}, timeout=15)
        url = None
        if r2.status_code == 200:
            url = r2.json().get("url","").replace("www.dropbox.com","dl.dropboxusercontent.com").replace("?dl=0","?dl=1")
        elif r2.status_code == 409:
            raw = r2.json().get("error",{}).get("shared_link_already_exists",{}).get("metadata",{}).get("url","")
            if raw: url = raw.replace("www.dropbox.com","dl.dropboxusercontent.com").replace("?dl=0","?dl=1")
        return True, final_name, "OK", url
    except Exception as e:
        return False, final_name, str(e), None


# ─────────────────────────────────────────────
# DOWNLOAD HELPER
# ─────────────────────────────────────────────
def download_file(url, dest):
    hdrs = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    try:
        r = requests.get(url, stream=True, timeout=300, headers=hdrs, allow_redirects=True)
        r.raise_for_status()
        ct = r.headers.get("Content-Type","")
        if "text/html" in ct:
            return False, f"URL trả về HTML, không phải file video"
        size = 0
        with open(dest,"wb") as f:
            for chunk in r.iter_content(512*1024):
                f.write(chunk); size += len(chunk)
        if size < 1024:
            return False, f"File quá nhỏ ({size} bytes)"
        return True, f"{size//1024//1024:.1f} MB"
    except requests.exceptions.HTTPError as e:
        return False, f"HTTP {e.response.status_code}"
    except Exception as e:
        return False, str(e)


# ─────────────────────────────────────────────
# FFPROBE INFO
# ─────────────────────────────────────────────
def get_video_info(path):
    """Return dict with duration, width, height, fps, video_bitrate, audio_codec."""
    try:
        r = subprocess.run([
            "ffprobe","-v","quiet","-print_format","json","-show_streams","-show_format", path
        ], capture_output=True, text=True)
        data = json.loads(r.stdout)
        info = {}
        for s in data.get("streams",[]):
            if s.get("codec_type") == "video":
                info["width"]  = s.get("width",0)
                info["height"] = s.get("height",0)
                info["fps"]    = s.get("r_frame_rate","0/1")
                info["vcodec"] = s.get("codec_name","?")
                info["vbr"]    = int(s.get("bit_rate",0))//1000
            elif s.get("codec_type") == "audio":
                info["acodec"] = s.get("codec_name","?")
                info["abr"]    = int(s.get("bit_rate",0))//1000
                info["asr"]    = int(s.get("sample_rate",0))
        fmt = data.get("format",{})
        info["duration"] = float(fmt.get("duration",0))
        info["size_mb"]  = int(fmt.get("size",0))//1024//1024
        info["tbr"]      = int(fmt.get("bit_rate",0))//1000
        # Parse fps fraction
        if "/" in str(info.get("fps","")):
            a,b = info["fps"].split("/")
            info["fps_num"] = round(int(a)/int(b),2) if int(b) else 0
        else:
            info["fps_num"] = 0
        return info
    except Exception:
        return {}


# ─────────────────────────────────────────────
# ENCODE FUNCTION
# ─────────────────────────────────────────────
def encode_for_youtube(
    input_path, output_path,
    resolution="1280x720",
    bitrate=3500,
    fps=30,
    audio_bitrate=128,
):
    """
    Encode video to YouTube livestream optimal format:
    H.264 + AAC, target bitrate, fixed fps, exact resolution.
    """
    w, h = resolution.split("x")

    # Scale filter — letterbox to exact resolution
    vf = (
        f"scale={w}:{h}:force_original_aspect_ratio=decrease,"
        f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:black,"
        f"setsar=1"
    )

    cmd = [
        "ffmpeg", "-y",
        "-i", input_path,
        # Video
        "-c:v", "libx264",
        "-preset", "medium",
        "-profile:v", "high",
        "-level", "4.1",
        "-b:v", f"{bitrate}k",
        "-maxrate", f"{int(bitrate*1.2)}k",
        "-bufsize", f"{bitrate*2}k",
        "-r", str(fps),
        "-g", str(fps * 2),        # keyframe every 2s
        "-keyint_min", str(fps),
        "-sc_threshold", "0",
        "-vf", vf,
        # Audio
        "-c:a", "aac",
        "-b:a", f"{audio_bitrate}k",
        "-ar", "44100",
        "-ac", "2",
        # Container
        "-movflags", "+faststart",
        "-pix_fmt", "yuv420p",
        output_path
    ]
    start = time.time()
    r = subprocess.run(cmd, capture_output=True, text=True)
    elapsed = time.time() - start

    if r.returncode != 0:
        return False, r.stderr[-600:], 0
    return True, "OK", elapsed


# ─────────────────────────────────────────────
# SESSION STATE
# ─────────────────────────────────────────────
for k, v in {
    "dbx_token": None, "dbx_app_key": "", "dbx_app_secret": "",
    "dbx_refresh_token": "", "dbx_account": None,
}.items():
    if k not in st.session_state: st.session_state[k] = v


# ─────────────────────────────────────────────
# SIDEBAR — Dropbox + Settings
# ─────────────────────────────────────────────
with st.sidebar:
    st.markdown("""
    <p style="font-family:'Bebas Neue',sans-serif;font-size:1.6rem;
    letter-spacing:0.1em;background:linear-gradient(135deg,#e63946,#f4c542);
    -webkit-background-clip:text;-webkit-text-fill-color:transparent;
    margin:0 0 4px 0;">STREAM<br>ENCODER</p>
    <p style="font-family:'DM Mono',monospace;font-size:0.65rem;color:#555;
    letter-spacing:0.15em;text-transform:uppercase;margin-bottom:1.2rem;">
    YouTube Livestream Optimizer</p>
    """, unsafe_allow_html=True)

    st.markdown("---")
    st.markdown("### ☁️ Dropbox")
    st.markdown("""<div style="background:#111116;border:1px solid #2a2a35;border-radius:8px;
    padding:0.75rem;font-size:0.76rem;color:#666;margin-bottom:0.8rem;">
    <b style="color:#aaa">Lấy Refresh Token:</b><br>
    1. <a href="https://www.dropbox.com/developers/apps" target="_blank" style="color:#60a5fa;">dropbox.com/developers/apps</a><br>
    2. Create app → Full Dropbox → Tab Permissions: bật write<br>
    3. Tab Settings → Generate token + copy refresh_token
    </div>""", unsafe_allow_html=True)

    app_key    = st.text_input("App Key", value=st.session_state.dbx_app_key, placeholder="xxxx")
    app_secret = st.text_input("App Secret", value=st.session_state.dbx_app_secret,
                                placeholder="xxxx", type="password")
    refresh_tk = st.text_input("Refresh Token", value=st.session_state.dbx_refresh_token,
                                placeholder="xxxx...", type="password")

    if st.button("🔐 Connect Dropbox", use_container_width=True):
        if not (app_key.strip() and app_secret.strip() and refresh_tk.strip()):
            st.error("Nhập đủ 3 trường")
        else:
            with st.spinner("Xác thực..."):
                tok, err = dbx_get_access_token(app_key.strip(), app_secret.strip(), refresh_tk.strip())
            if tok:
                info = dbx_verify(tok)
                if info:
                    st.session_state.dbx_token         = tok
                    st.session_state.dbx_app_key       = app_key.strip()
                    st.session_state.dbx_app_secret    = app_secret.strip()
                    st.session_state.dbx_refresh_token = refresh_tk.strip()
                    st.session_state.dbx_account       = info
                    st.success(f"✅ {info.get('name',{}).get('display_name','')}  ({info.get('email','')})")
                else:
                    st.error("Token lỗi")
            else:
                st.error(f"Lỗi: {err}")

    if st.session_state.dbx_token:
        st.markdown('<p style="color:#4ade80;font-size:0.8rem;font-family:DM Mono,monospace;">● CONNECTED</p>',
                    unsafe_allow_html=True)

    st.markdown("---")
    st.markdown("### ⚙️ Encode Settings")

    resolution = st.selectbox("Resolution", ["1280x720","1920x1080"],
        format_func=lambda x: f"{'HD 720p' if x=='1280x720' else 'FHD 1080p'}  ({x})",
        key="enc_res")

    bitrate = st.slider("Video Bitrate (kbps)", 1500, 6000, 3500, 250, key="enc_br")
    st.caption(f"{'🟢 Optimal' if 2500<=bitrate<=4000 else '🟡 OK' if bitrate>=1500 else '🔴 Low'}  — YouTube khuyến nghị 2500–4000 kbps")

    fps = st.selectbox("FPS", [30, 60], key="enc_fps")
    audio_br = st.selectbox("Audio Bitrate", [128, 192, 256],
        format_func=lambda x: f"{x} kbps", key="enc_abr")

    dbx_folder = st.text_input("Dropbox Folder", value="/Encoded",
                                 key="enc_folder", help="Thư mục lưu video đã encode")

    st.markdown("---")
    # Target spec summary
    st.markdown(f"""
    <div style="background:#0d0d10;border:1px solid #2a2a35;border-radius:8px;
    padding:0.8rem;font-family:'DM Mono',monospace;font-size:0.72rem;color:#666;">
    <div style="color:#f4c542;margin-bottom:6px;font-size:0.7rem;
    letter-spacing:0.1em;">TARGET SPEC</div>
    Codec   <span style="color:#e8e6e0;float:right;">H.264 / AAC</span><br>
    Res     <span style="color:#e8e6e0;float:right;">{resolution}</span><br>
    Bitrate <span style="color:#e8e6e0;float:right;">{bitrate} kbps</span><br>
    FPS     <span style="color:#e8e6e0;float:right;">{fps}</span><br>
    Audio   <span style="color:#e8e6e0;float:right;">{audio_br}kbps / 44.1kHz</span>
    </div>
    """, unsafe_allow_html=True)


# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────
st.markdown('<h1 class="hero-title">STREAM ENCODER</h1>', unsafe_allow_html=True)
st.markdown('<p class="hero-sub">YouTube Livestream Video Optimizer • H.264 + AAC • Auto Upload Dropbox</p>',
            unsafe_allow_html=True)

# Target spec cards
st.markdown(f"""
<div class="spec-grid">
  <div class="spec-card"><div class="label">Codec</div><div class="value">H.264</div></div>
  <div class="spec-card"><div class="label">Resolution</div><div class="value">{resolution.replace("x","×")}</div></div>
  <div class="spec-card"><div class="label">Bitrate</div><div class="value">{bitrate}K</div></div>
  <div class="spec-card"><div class="label">FPS</div><div class="value">{fps}</div></div>
  <div class="spec-card"><div class="label">Audio</div><div class="value">AAC {audio_br}K</div></div>
</div>
""", unsafe_allow_html=True)

# FFmpeg check
with st.spinner("Checking FFmpeg..."):
    ffok = ensure_ffmpeg()
if not ffok:
    st.error("❌ FFmpeg chưa cài. Chạy: sudo apt-get install ffmpeg")
    st.stop()

st.markdown("---")

# ── Input mode ─────────────────────────────────────────────
input_mode = st.radio("Nguồn video", ["🔗 Dán URL (.mp4)", "📁 Upload file"],
                       horizontal=True, key="enc_input_mode")

urls_to_encode = []   # list of {"label": str, "path": str (local)}

# ── URL MODE ───────────────────────────────────────────────
if input_mode == "🔗 Dán URL (.mp4)":
    st.markdown("""<div class="info-box">
Dán một hoặc nhiều link <b>.mp4</b> (Cloudinary, CDN trực tiếp).<br>
Mỗi dòng = 1 video. Không hỗ trợ Dropbox/MediaFire link trực tiếp.
</div>""", unsafe_allow_html=True)

    url_text = st.text_area("URL video (.mp4)", height=150,
        placeholder="https://res.cloudinary.com/.../video1.mp4\nhttps://res.cloudinary.com/.../video2.mp4",
        key="enc_url_input")

    if url_text.strip():
        raw_urls = [u.strip() for u in url_text.splitlines() if u.strip()]
        st.markdown(f"**{len(raw_urls)} URL:**")
        for i, u in enumerate(raw_urls, 1):
            st.caption(f"{i}. {u.split('/')[-1].split('?')[0]}")

        if st.button("⬇️ Tải & Chuẩn bị encode", use_container_width=True, key="btn_dl_enc"):
            dl_tmp = tempfile.mkdtemp()
            downloaded = []
            prog = st.progress(0)
            for i, url in enumerate(raw_urls):
                ext  = Path(url.split("?")[0]).suffix.lower() or ".mp4"
                name = url.split("/")[-1].split("?")[0] or f"video_{i+1}.mp4"
                dest = os.path.join(dl_tmp, f"src_{i:03d}{ext}")
                st.caption(f"⬇️ Đang tải {name}...")
                ok, info = download_file(url, dest)
                if ok:
                    downloaded.append({"label": name, "path": dest})
                    st.caption(f"  ✅ {name} — {info}")
                else:
                    st.warning(f"  ❌ {name} — {info}")
                prog.progress((i+1)/len(raw_urls))

            st.session_state["enc_ready"] = downloaded
            if downloaded:
                st.success(f"✅ Tải xong {len(downloaded)}/{len(raw_urls)} file. Sẵn sàng encode!")

    if st.session_state.get("enc_ready"):
        urls_to_encode = [p for p in st.session_state["enc_ready"] if os.path.exists(p["path"])]

# ── UPLOAD MODE ────────────────────────────────────────────
else:
    st.markdown("""<div class="info-box">
Upload trực tiếp từ máy tính — <b>nhanh nhất, không bị lỗi download</b>.
</div>""", unsafe_allow_html=True)

    uploaded = st.file_uploader("Chọn file video",
        type=["mp4","mov","avi","mkv","webm","flv"],
        accept_multiple_files=True, key="enc_upload")

    if uploaded:
        st.markdown(f"**{len(uploaded)} file:**")
        for uf in uploaded:
            st.caption(f"• {uf.name}  ({uf.size//1024//1024:.1f} MB)")

        if st.button("💾 Lưu file", use_container_width=True, key="btn_save_enc"):
            save_tmp = tempfile.mkdtemp()
            saved = []
            for i, uf in enumerate(uploaded):
                ext  = Path(uf.name).suffix.lower() or ".mp4"
                dest = os.path.join(save_tmp, f"src_{i:03d}{ext}")
                with open(dest,"wb") as f: f.write(uf.read())
                saved.append({"label": uf.name, "path": dest})
            st.session_state["enc_ready"] = saved
            st.success(f"✅ Đã lưu {len(saved)} file!")

    if st.session_state.get("enc_ready"):
        urls_to_encode = [p for p in st.session_state["enc_ready"] if os.path.exists(p["path"])]

# ── ENCODE SECTION ─────────────────────────────────────────
if urls_to_encode:
    st.markdown("---")
    st.markdown(f'<div class="info-box">✅ <b>{len(urls_to_encode)} video</b> sẵn sàng encode</div>',
                unsafe_allow_html=True)

    if not st.session_state.dbx_token:
        st.markdown('<div class="warn-box">⚠️ Chưa kết nối Dropbox — video sẽ chỉ tải xuống thủ công.</div>',
                    unsafe_allow_html=True)

    if st.button(f"🚀 Encode {len(urls_to_encode)} video → YouTube", use_container_width=True,
                 type="primary", key="btn_encode"):

        enc_tmp = tempfile.mkdtemp()
        results = []
        overall = st.progress(0, text="Bắt đầu encode...")

        for i, item in enumerate(urls_to_encode):
            label    = item["label"]
            src_path = item["path"]
            stem     = Path(label).stem
            out_name = f"{stem}_youtube_{resolution.replace('x','p' if resolution=='1920x1080' else 'p')}.mp4"
            out_name = f"{stem}_{resolution}.mp4"
            out_path = os.path.join(enc_tmp, out_name)

            overall.progress(i/len(urls_to_encode),
                             text=f"Encoding {i+1}/{len(urls_to_encode)}: {label}")

            # Show source info
            info = get_video_info(src_path)
            if info:
                st.markdown(f"""
                <div class="stat-row">
                  <div class="stat-item">Source <span>{label[:40]}</span></div>
                  <div class="stat-item">Size <span>{info.get('size_mb',0)} MB</span></div>
                  <div class="stat-item">Res <span>{info.get('width',0)}×{info.get('height',0)}</span></div>
                  <div class="stat-item">FPS <span>{info.get('fps_num',0)}</span></div>
                  <div class="stat-item">Bitrate <span>{info.get('tbr',0)} kbps</span></div>
                  <div class="stat-item">Duration <span>{info.get('duration',0):.1f}s</span></div>
                </div>
                """, unsafe_allow_html=True)

            enc_status = st.empty()
            enc_status.markdown(f'<p class="encode-progress">⚙️ Encoding <b>{label}</b>...</p>',
                                 unsafe_allow_html=True)

            ok, msg, elapsed = encode_for_youtube(
                src_path, out_path,
                resolution=resolution,
                bitrate=bitrate,
                fps=fps,
                audio_bitrate=audio_br,
            )

            if not ok:
                enc_status.empty()
                results.append((label, out_name, None, False, msg, None))
                st.markdown(f'<div class="result-err">❌ <b>{label}</b><br>{msg[:300]}</div>',
                             unsafe_allow_html=True)
                continue

            enc_status.empty()

            # Output info
            out_info = get_video_info(out_path)
            out_size = os.path.getsize(out_path)//1024//1024

            st.markdown(f"""
            <div class="result-ok">
            ✅ <b>{out_name}</b> — encode xong trong {elapsed:.1f}s<br>
            &nbsp;&nbsp;{out_info.get('width',0)}×{out_info.get('height',0)} •
            {out_info.get('fps_num',0)} fps •
            {out_info.get('tbr',0)} kbps •
            {out_size} MB
            </div>
            """, unsafe_allow_html=True)

            # Upload Dropbox
            dbx_link = None
            if st.session_state.dbx_token:
                folder = dbx_folder.strip() or "/Encoded"
                if not folder.startswith("/"): folder = "/" + folder
                api_folder = "" if folder == "/" else folder

                # Refresh token
                if st.session_state.dbx_refresh_token:
                    new_tok, _ = dbx_get_access_token(
                        st.session_state.dbx_app_key,
                        st.session_state.dbx_app_secret,
                        st.session_state.dbx_refresh_token,
                    )
                    if new_tok: st.session_state.dbx_token = new_tok

                with st.spinner(f"☁️ Uploading {out_name}..."):
                    succ, fname, umsg, surl = dbx_upload(
                        st.session_state.dbx_token, out_path, api_folder, out_name)

                if succ:
                    renamed = f" (đổi tên → {fname})" if fname != out_name else ""
                    link_html = f'<br>&nbsp;&nbsp;🔗 <a href="{surl}" target="_blank" style="color:#60a5fa;">{surl[:70]}...</a>' if surl else ""
                    st.markdown(f'<div class="result-ok">☁️ <b>Dropbox OK</b>{renamed}{link_html}</div>',
                                 unsafe_allow_html=True)
                    dbx_link = surl
                else:
                    st.markdown(f'<div class="result-err">❌ Dropbox upload thất bại: {umsg}</div>',
                                 unsafe_allow_html=True)

            results.append((label, out_name, out_path, True, f"{elapsed:.1f}s", dbx_link))

        overall.progress(1.0, text=f"✅ Hoàn tất {len(urls_to_encode)} video!")

        # ── Final summary ───────────────────────────────────
        st.markdown("---")
        ok_list   = [(n,op,lnk) for _,n,op,ok,_,lnk in results if ok and op]
        fail_list = [l for l,_,_,ok,_,_ in results if not ok]

        st.markdown(f"""
        <div class="result-ok" style="font-size:1rem;">
        🎬 <b>Bulk encode xong!</b> &nbsp;
        ✅ {len(ok_list)} thành công
        {'&nbsp; ❌ ' + str(len(fail_list)) + ' thất bại' if fail_list else ''}
        </div>
        """, unsafe_allow_html=True)

        # Download buttons
        if ok_list:
            st.markdown("**⬇️ Tải xuống:**")
            cols = st.columns(min(3, len(ok_list)))
            for i, (name, path, link) in enumerate(ok_list):
                with cols[i % 3]:
                    with open(path,"rb") as f:
                        st.download_button(f"⬇️ {name}", data=f,
                            file_name=name, mime="video/mp4", key=f"dl_enc_{i}")
                    if link:
                        st.markdown(f'<a href="{link}" target="_blank" style="font-size:0.75rem;color:#60a5fa;">🔗 Dropbox link</a>',
                                     unsafe_allow_html=True)
