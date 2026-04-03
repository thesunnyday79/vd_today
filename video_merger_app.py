import streamlit as st
import requests
import os
import subprocess
import sys
import tempfile
import json
from pathlib import Path


# ─────────────────────────────────────────────
# AUTO-INSTALL FFMPEG (runs once at startup)
# ─────────────────────────────────────────────
@st.cache_resource(show_spinner=False)
def ensure_ffmpeg():
    """Install ffmpeg automatically if not present. Works on Streamlit Cloud (Debian/Ubuntu)."""
    # Check if already available
    result = subprocess.run(["which", "ffmpeg"], capture_output=True)
    if result.returncode == 0:
        return True, "FFmpeg already installed."

    # Try apt-get (Streamlit Cloud / Debian / Ubuntu)
    msgs = []
    try:
        r = subprocess.run(
            ["apt-get", "install", "-y", "ffmpeg"],
            capture_output=True, text=True
        )
        if r.returncode == 0:
            return True, "FFmpeg installed via apt-get."
        msgs.append(r.stderr[:300])
    except FileNotFoundError:
        msgs.append("apt-get not found")

    # Try apt (some systems)
    try:
        r = subprocess.run(
            ["apt", "install", "-y", "ffmpeg"],
            capture_output=True, text=True
        )
        if r.returncode == 0:
            return True, "FFmpeg installed via apt."
        msgs.append(r.stderr[:300])
    except FileNotFoundError:
        msgs.append("apt not found")

    return False, "Could not install FFmpeg automatically: " + " | ".join(msgs)


# ─────────────────────────────────────────────
# PAGE CONFIG
# ─────────────────────────────────────────────
st.set_page_config(
    page_title="🎬 Video Merger Pro",
    page_icon="🎬",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ─────────────────────────────────────────────
# CUSTOM CSS
# ─────────────────────────────────────────────
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Syne:wght@400;600;800&family=DM+Sans:wght@300;400;500&display=swap');

html, body, [class*="css"] {
    font-family: 'DM Sans', sans-serif;
    background-color: #0d0d0f;
    color: #e8e4dc;
}

h1, h2, h3 {
    font-family: 'Syne', sans-serif;
    letter-spacing: -0.02em;
}

.main-title {
    font-family: 'Syne', sans-serif;
    font-size: 2.8rem;
    font-weight: 800;
    background: linear-gradient(135deg, #f5c842 0%, #ff6b35 50%, #e84393 100%);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    background-clip: text;
    margin-bottom: 0.2rem;
}

.subtitle {
    color: #888;
    font-size: 1rem;
    margin-bottom: 2rem;
}

.card {
    background: #16161a;
    border: 1px solid #2a2a30;
    border-radius: 16px;
    padding: 1.5rem;
    margin-bottom: 1rem;
}

.badge {
    display: inline-block;
    background: #f5c84220;
    color: #f5c842;
    border: 1px solid #f5c84240;
    padding: 2px 10px;
    border-radius: 20px;
    font-size: 0.75rem;
    font-weight: 600;
    letter-spacing: 0.05em;
    text-transform: uppercase;
    margin-bottom: 0.5rem;
}

.step-number {
    font-family: 'Syne', sans-serif;
    font-size: 3rem;
    font-weight: 800;
    color: #2a2a30;
    line-height: 1;
}

div[data-testid="stExpander"] {
    background: #16161a;
    border: 1px solid #2a2a30;
    border-radius: 12px;
}

.stButton > button {
    background: linear-gradient(135deg, #f5c842, #ff6b35);
    color: #0d0d0f;
    border: none;
    border-radius: 10px;
    font-family: 'Syne', sans-serif;
    font-weight: 700;
    font-size: 1rem;
    padding: 0.6rem 1.5rem;
    transition: opacity 0.2s;
}
.stButton > button:hover { opacity: 0.85; }

.success-box {
    background: #0f2b1a;
    border: 1px solid #1a5c30;
    border-radius: 12px;
    padding: 1rem 1.5rem;
    color: #4ade80;
}

.error-box {
    background: #2b0f0f;
    border: 1px solid #5c1a1a;
    border-radius: 12px;
    padding: 1rem 1.5rem;
    color: #f87171;
}

.info-box {
    background: #0f1e2b;
    border: 1px solid #1a3a5c;
    border-radius: 12px;
    padding: 1rem 1.5rem;
    color: #60a5fa;
    font-size: 0.9rem;
}

[data-testid="stSidebar"] {
    background: #111113;
    border-right: 1px solid #2a2a30;
}
</style>
""", unsafe_allow_html=True)


# ─────────────────────────────────────────────
# PCLOUD HELPERS
# ─────────────────────────────────────────────

def pcloud_login_digest(username: str, password: str) -> dict | None:
    """Login via digest auth (more compatible with pCloud API)."""
    import hashlib
    try:
        # Step 1: get digest
        r = requests.get("https://api.pcloud.com/getdigest", timeout=15)
        digest_data = r.json()
        if digest_data.get("result") != 0:
            return None
        digest = digest_data["digest"]

        # Step 2: compute password digest
        # passworddigest = SHA1(password + SHA1(username.lower()) + digest)
        pw_sha1 = hashlib.sha1(password.encode("utf-8")).hexdigest()
        username_sha1 = hashlib.sha1(username.lower().encode("utf-8")).hexdigest()
        password_digest = hashlib.sha1(
            (password + username_sha1 + digest).encode("utf-8")
        ).hexdigest()

        params = {
            "getauth": 1,
            "logout": 1,
            "username": username,
            "digest": digest,
            "passworddigest": password_digest,
        }
        resp = requests.get("https://api.pcloud.com/userinfo", params=params, timeout=15)
        data = resp.json()
        if data.get("result") == 0:
            return data
        return None
    except Exception:
        return None


def pcloud_login(username: str, password: str) -> dict | None:
    """Login to pCloud — tries digest auth first, falls back to plain."""
    # Try digest auth first (recommended)
    result = pcloud_login_digest(username, password)
    if result:
        return result
    # Fallback: plain (may work on some regions)
    try:
        resp = requests.get(
            "https://api.pcloud.com/userinfo",
            params={"getauth": 1, "logout": 1, "username": username, "password": password},
            timeout=15,
        )
        data = resp.json()
        if data.get("result") == 0:
            return data
        return None
    except Exception:
        return None


def pcloud_verify_token(token: str) -> dict | None:
    """Verify a direct access token."""
    try:
        resp = requests.get(
            "https://api.pcloud.com/userinfo",
            params={"auth": token},
            timeout=15,
        )
        data = resp.json()
        if data.get("result") == 0:
            return data
        return None
    except Exception:
        return None


def pcloud_list_folder(auth_token: str, folder_id: int = 0) -> list[dict]:
    """List files in a pCloud folder."""
    try:
        resp = requests.get(
            "https://api.pcloud.com/listfolder",
            params={"auth": auth_token, "folderid": folder_id, "recursive": 0},
            timeout=15,
        )
        data = resp.json()
        if data.get("result") == 0:
            return data["metadata"]["contents"]
        return []
    except Exception:
        return []


def pcloud_get_download_link(auth_token: str, file_id: int) -> str | None:
    """Get a direct download link for a pCloud file."""
    try:
        resp = requests.get(
            "https://api.pcloud.com/getfilelink",
            params={"auth": auth_token, "fileid": file_id},
            timeout=15,
        )
        data = resp.json()
        if data.get("result") == 0:
            host = data["hosts"][0]
            path = data["path"]
            return f"https://{host}{path}"
        return None
    except Exception:
        return None


def download_file(url: str, dest_path: str) -> bool:
    """Download a file from URL to local path."""
    try:
        resp = requests.get(url, stream=True, timeout=60)
        resp.raise_for_status()
        with open(dest_path, "wb") as f:
            for chunk in resp.iter_content(chunk_size=1024 * 512):
                f.write(chunk)
        return True
    except Exception as e:
        st.error(f"Download failed: {e}")
        return False



def pcloud_list_filenames(auth_token: str, folder_id: int) -> set:
    """Return set of filenames already in a pCloud folder."""
    try:
        resp = requests.get(
            "https://api.pcloud.com/listfolder",
            params={"auth": auth_token, "folderid": folder_id, "recursive": 0},
            timeout=15,
        )
        data = resp.json()
        if data.get("result") == 0:
            return {f["name"] for f in data["metadata"]["contents"] if not f.get("isfolder")}
        return set()
    except Exception:
        return set()


def make_unique_filename(filename: str, existing_names: set) -> str:
    """Return filename that does not clash with existing_names.
    final_video.mp4 -> final_video_1.mp4 -> final_video_2.mp4 ...
    """
    if filename not in existing_names:
        return filename
    stem = Path(filename).stem
    ext = Path(filename).suffix
    counter = 1
    while True:
        candidate = f"{stem}_{counter}{ext}"
        if candidate not in existing_names:
            return candidate
        counter += 1


def pcloud_upload(auth_token: str, file_path: str, folder_id: int, filename: str) -> tuple:
    """Upload file to pCloud, auto-renaming if a file with same name exists.
    Returns (response_dict, final_filename_used).
    """
    # Check existing names and resolve conflict
    existing = pcloud_list_filenames(auth_token, folder_id)
    final_name = make_unique_filename(filename, existing)
    try:
        with open(file_path, "rb") as f:
            resp = requests.post(
                "https://api.pcloud.com/uploadfile",
                params={
                    "auth": auth_token,
                    "folderid": folder_id,
                    "filename": final_name,
                    "nopartial": 1,
                },
                files={"file": (final_name, f, "video/mp4")},
                timeout=300,
            )
        return resp.json(), final_name
    except Exception as e:
        return {"result": -1, "error": str(e)}, final_name


# ─────────────────────────────────────────────
# FFMPEG HELPERS
# ─────────────────────────────────────────────

def check_ffmpeg() -> bool:
    try:
        subprocess.run(["ffmpeg", "-version"], capture_output=True, check=True)
        return True
    except Exception:
        return False


def get_duration(filepath: str):
    """Return duration in seconds using ffprobe, or None on failure."""
    try:
        r = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", filepath],
            capture_output=True, text=True
        )
        return float(r.stdout.strip())
    except Exception:
        return None


def merge_videos_and_audio(
    video_paths,
    audio_paths,
    output_path,
    resolution="original",
    audio_mode="replace",
):
    """
    Merge multiple videos + audios.
    If audio is longer than video, video loops to fill audio duration.
    Returns (success, message).
    """
    tmp_dir = tempfile.mkdtemp()
    concat_list = os.path.join(tmp_dir, "concat.txt")
    merged_video = os.path.join(tmp_dir, "merged_video.mp4")
    merged_audio = os.path.join(tmp_dir, "merged_audio.aac")

    scale_filter = ""
    if resolution == "youtube":
        scale_filter = "scale=1280:720:force_original_aspect_ratio=decrease,pad=1280:720:(ow-iw)/2:(oh-ih)/2"
    elif resolution == "tiktok":
        scale_filter = "scale=576:1024:force_original_aspect_ratio=decrease,pad=576:1024:(ow-iw)/2:(oh-ih)/2"

    # Re-encode each video for compatibility
    reencoded = []
    progress = st.progress(0, text="Re-encoding videos...")
    for i, vp in enumerate(video_paths):
        out = os.path.join(tmp_dir, f"v{i}.mp4")
        vf_arg = ["-vf", scale_filter] if scale_filter else []
        cmd = ["ffmpeg", "-y", "-i", vp] + vf_arg + [
            "-c:v", "libx264", "-preset", "fast", "-crf", "23",
            "-c:a", "aac", "-b:a", "128k", "-ar", "44100",
            out
        ]
        r = subprocess.run(cmd, capture_output=True)
        if r.returncode != 0:
            return False, f"Re-encode failed for {os.path.basename(vp)}:\n{r.stderr.decode()}"
        reencoded.append(out)
        progress.progress((i + 1) / len(video_paths), text=f"Re-encoding {i+1}/{len(video_paths)}...")
    progress.empty()

    # Concatenate videos
    with open(concat_list, "w") as f:
        for vp in reencoded:
            f.write(f"file '{vp}'\n")

    st.info("Concatenating videos...")
    cmd = ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", concat_list, "-c", "copy", merged_video]
    r = subprocess.run(cmd, capture_output=True)
    if r.returncode != 0:
        return False, f"Concat failed:\n{r.stderr.decode()}"

    video_duration = get_duration(merged_video)

    if audio_paths:
        # Step 1: Re-encode every audio file to uniform .aac wav
        # This handles .mp4 containers with audio, .mp3, .wav, etc.
        reencoded_audios = []
        st.info("Re-encoding audio files...")
        for i, ap in enumerate(audio_paths):
            ra_out = os.path.join(tmp_dir, f"ra{i}.aac")
            ra_cmd = [
                "ffmpeg", "-y", "-i", ap,
                "-vn",                      # drop video stream if any
                "-c:a", "aac", "-b:a", "192k", "-ar", "44100", "-ac", "2",
                ra_out
            ]
            r = subprocess.run(ra_cmd, capture_output=True)
            if r.returncode != 0:
                return False, f"Audio re-encode failed for {os.path.basename(ap)}:\n{r.stderr.decode()}"
            reencoded_audios.append(ra_out)

        # Step 2: Concat all re-encoded audio files
        audio_concat_list = os.path.join(tmp_dir, "audio_concat.txt")
        with open(audio_concat_list, "w") as f:
            for ap in reencoded_audios:
                f.write(f"file '{ap}'\n")
        st.info("Merging audio tracks...")
        cmd = ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", audio_concat_list,
               "-c", "copy", merged_audio]
        r = subprocess.run(cmd, capture_output=True)
        if r.returncode != 0:
            return False, f"Audio merge failed:\n{r.stderr.decode()}"

        audio_duration = get_duration(merged_audio)

        # Final duration always = audio duration.
        # video < audio  -> loop video to fill
        # video > audio  -> trim video to match
        video_for_merge = merged_video
        if audio_duration:
            adjusted_video = os.path.join(tmp_dir, "adjusted_video.mp4")
            if video_duration and audio_duration > video_duration:
                st.info(f"Video {video_duration:.1f}s < Audio {audio_duration:.1f}s -- looping video to {audio_duration:.1f}s...")
                adj_cmd = [
                    "ffmpeg", "-y",
                    "-stream_loop", "-1",
                    "-i", merged_video,
                    "-t", str(audio_duration),
                    "-c:v", "libx264", "-preset", "fast", "-crf", "23",
                    "-an",
                    adjusted_video
                ]
            else:
                st.info(f"Video {video_duration:.1f}s > Audio {audio_duration:.1f}s -- trimming video to {audio_duration:.1f}s...")
                adj_cmd = [
                    "ffmpeg", "-y",
                    "-i", merged_video,
                    "-t", str(audio_duration),
                    "-c:v", "libx264", "-preset", "fast", "-crf", "23",
                    "-an",
                    adjusted_video
                ]
            r = subprocess.run(adj_cmd, capture_output=True)
            if r.returncode != 0:
                return False, f"Video adjust failed:\n{r.stderr.decode()}"
            video_for_merge = adjusted_video

        # Combine -- both tracks now exactly audio_duration long
        st.info("Combining video + audio...")
        if audio_mode == "replace":
            cmd = [
                "ffmpeg", "-y",
                "-i", video_for_merge,
                "-i", merged_audio,
                "-c:v", "copy",
                "-c:a", "aac", "-b:a", "192k",
                "-map", "0:v:0", "-map", "1:a:0",
                "-shortest",
                output_path
            ]
        else:
            cmd = [
                "ffmpeg", "-y",
                "-i", video_for_merge,
                "-i", merged_audio,
                "-filter_complex", "[0:a][1:a]amix=inputs=2:duration=shortest:dropout_transition=2[a]",
                "-map", "0:v", "-map", "[a]",
                "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
                "-shortest",
                output_path
            ]
    else:
        cmd = ["ffmpeg", "-y", "-i", merged_video, "-c", "copy", output_path]

    r = subprocess.run(cmd, capture_output=True)
    if r.returncode != 0:
        return False, f"Final merge failed:\n{r.stderr.decode()}"

    return True, "Video created successfully!"



# ─────────────────────────────────────────────
# SESSION STATE
# ─────────────────────────────────────────────
if "auth_token" not in st.session_state:
    st.session_state.auth_token = None
if "pcloud_files" not in st.session_state:
    st.session_state.pcloud_files = []
if "selected_videos" not in st.session_state:
    st.session_state.selected_videos = []
if "selected_audios" not in st.session_state:
    st.session_state.selected_audios = []


# ─────────────────────────────────────────────
# SIDEBAR
# ─────────────────────────────────────────────
with st.sidebar:
    st.markdown('<p class="main-title" style="font-size:1.6rem;">🎬 Video<br>Merger Pro</p>', unsafe_allow_html=True)
    st.markdown("---")

    st.markdown("### ☁️ pCloud Login")

    login_method = st.radio("Phương thức đăng nhập", ["🔑 Access Token", "📧 Email + Password"], horizontal=True)

    if login_method == "🔑 Access Token":
        st.markdown("""<small>Lấy token tại: <a href="https://docs.pcloud.com/my_apps/" target="_blank">pCloud My Apps</a> → tạo app → copy Access Token</small>""", unsafe_allow_html=True)
        direct_token = st.text_input("Access Token", type="password", placeholder="paste token here...")
        if st.button("🔐 Connect", use_container_width=True):
            with st.spinner("Verifying token..."):
                result = pcloud_verify_token(direct_token.strip())
                if result:
                    st.session_state.auth_token = direct_token.strip()
                    st.success(f"✅ Connected as **{result.get('email', 'user')}**")
                    st.session_state.pcloud_files = pcloud_list_folder(st.session_state.auth_token)
                else:
                    st.error("❌ Token không hợp lệ.")
                    st.session_state.auth_token = None
    else:
        username = st.text_input("Email", placeholder="your@email.com")
        password = st.text_input("Password", type="password", placeholder="••••••••")
        if st.button("🔐 Connect to pCloud", use_container_width=True):
            with st.spinner("Connecting..."):
                result = pcloud_login(username, password)
                if result:
                    st.session_state.auth_token = result.get("auth") or result.get("token")
                    st.success(f"✅ Connected as **{result.get('email', username)}**")
                    st.session_state.pcloud_files = pcloud_list_folder(st.session_state.auth_token)
                else:
                    st.error("❌ Đăng nhập thất bại. Thử dùng Access Token thay thế.")
                    st.session_state.auth_token = None

    st.markdown("---")
    st.markdown("### ⚙️ Output Settings")

    output_filename = st.text_input("Output filename", value="final_video.mp4")
    resolution = st.selectbox(
        "Resolution",
        ["original", "youtube", "tiktok"],
        format_func=lambda x: {
            "original": "📐 Original (keep source)",
            "youtube": "▶️ YouTube (1280×720)",
            "tiktok": "📱 TikTok (576×1024)",
        }[x],
    )
    audio_mode = st.selectbox(
        "Audio mode",
        ["replace", "mix"],
        format_func=lambda x: {
            "replace": "🔇 Replace original audio",
            "mix": "🎛️ Mix with original audio",
        }[x],
    )

    st.markdown("---")
    st.caption("Powered by FFmpeg + pCloud API")


# ─────────────────────────────────────────────
# MAIN AREA
# ─────────────────────────────────────────────
st.markdown('<h1 class="main-title">🎬 Video Merger Pro</h1>', unsafe_allow_html=True)
st.markdown('<p class="subtitle">Ghép nhiều video ngắn + audio từ pCloud thành 1 video hoàn chỉnh</p>', unsafe_allow_html=True)

# ── FFmpeg auto-install ────────────────────────────────────
with st.spinner("⚙️ Đang kiểm tra / cài đặt FFmpeg…"):
    ffmpeg_ok, ffmpeg_msg = ensure_ffmpeg()

if not ffmpeg_ok:
    st.markdown(f"""
    <div class="error-box">
    ⚠️ <b>Không thể cài FFmpeg tự động.</b><br>
    Chi tiết: <code>{ffmpeg_msg}</code><br><br>
    Nếu chạy local: <code>sudo apt-get install ffmpeg</code> hoặc <code>brew install ffmpeg</code>
    </div>
    """, unsafe_allow_html=True)
    st.stop()

# ── Tabs ───────────────────────────────────────────────────
tab1, tab2, tab3 = st.tabs(["📂 Chọn từ pCloud", "🔗 Nhập URL trực tiếp", "🎬 Xuất video"])

# ══════════════════════════════════════════════════════════
# TAB 1 – Browse pCloud
# ══════════════════════════════════════════════════════════
with tab1:
    if not st.session_state.auth_token:
        st.markdown("""
        <div class="info-box">
        🔑 Vui lòng đăng nhập pCloud ở thanh bên trái để duyệt file.
        </div>
        """, unsafe_allow_html=True)
    else:
        # ── Browse sub-folder ──────────────────────────────
        folder_items = [f for f in st.session_state.pcloud_files if f.get("isfolder")]
        all_files = [f for f in st.session_state.pcloud_files if not f.get("isfolder")]
        all_names = [f["name"] for f in all_files]

        col_nav, col_reload = st.columns([4, 1])
        with col_nav:
            st.markdown("#### 📁 Duyệt thư mục")
            folder_options = ["(thư mục gốc)"] + [f["name"] for f in folder_items]
            folder_choice = st.selectbox("Chọn thư mục", options=folder_options, key="folder_select")
        with col_reload:
            st.markdown("<br>", unsafe_allow_html=True)
            if st.button("🔄 Mở", use_container_width=True):
                if folder_choice == "(thư mục gốc)":
                    st.session_state.pcloud_files = pcloud_list_folder(st.session_state.auth_token, 0)
                else:
                    chosen = next(f for f in folder_items if f["name"] == folder_choice)
                    st.session_state.pcloud_files = pcloud_list_folder(
                        st.session_state.auth_token, chosen["folderid"]
                    )
                st.rerun()

        st.markdown("---")

        # ── All files listed — user picks which are video, which are audio ──
        st.markdown("""
        <div class="info-box">
        ⚠️ <b>Tất cả file đều hiển thị ở cả 2 cột.</b>
        Chọn đúng file vào đúng cột — kể cả file .mp4 chứa audio cũng chọn vào cột Audio.
        </div>
        """, unsafe_allow_html=True)

        col_left, col_right = st.columns([1, 1])

        with col_left:
            st.markdown("### 🎥 Video (theo thứ tự ghép)")
            if not all_files:
                st.caption("Thư mục trống.")
            else:
                selected_v_names = st.multiselect(
                    "Chọn file VIDEO",
                    options=all_names,
                    default=[],
                    key="ms_videos",
                    help="Chọn theo thứ tự muốn ghép. File .mp4 chứa hình ảnh/video."
                )
                st.session_state.selected_videos = [
                    f for name in selected_v_names for f in all_files if f["name"] == name
                ]
                if st.session_state.selected_videos:
                    st.success(f"✅ {len(st.session_state.selected_videos)} video đã chọn")
                    for i, v in enumerate(st.session_state.selected_videos, 1):
                        st.caption(f"  {i}. {v['name']}")

        with col_right:
            st.markdown("### 🎵 Audio (theo thứ tự ghép)")
            if not all_files:
                st.caption("Thư mục trống.")
            else:
                selected_a_names = st.multiselect(
                    "Chọn file AUDIO",
                    options=all_names,
                    default=[],
                    key="ms_audios",
                    help="Có thể chọn .mp3, .wav, hoặc .mp4 chứa audio."
                )
                st.session_state.selected_audios = [
                    f for name in selected_a_names for f in all_files if f["name"] == name
                ]
                if st.session_state.selected_audios:
                    st.success(f"✅ {len(st.session_state.selected_audios)} audio đã chọn")
                    for i, a in enumerate(st.session_state.selected_audios, 1):
                        st.caption(f"  {i}. {a['name']}")


# ══════════════════════════════════════════════════════════
# TAB 2 – Direct URL input (like the screenshot reference)
# ══════════════════════════════════════════════════════════
with tab2:
    st.markdown("### 🔗 Nhập URL trực tiếp")
    st.markdown("""
    <div class="info-box">
    Dán tất cả URL (video + audio) vào ô bên dưới, phân cách bởi dấu phẩy hoặc xuống dòng.<br>
    Tool sẽ <b>tự động phân loại</b> dựa vào đuôi file (.mp4/.mov = video, .mp3/.wav/.aac/.m4a = audio).<br>
    Thứ tự trong danh sách = thứ tự ghép.
    </div>
    """, unsafe_allow_html=True)

    url_input = st.text_area(
        "Dán tất cả URL vào đây",
        height=200,
        placeholder="https://.../video1.mp4,https://.../video2.mp4,https://.../audio1.mp3,...",
        key="url_input_area",
    )

    if url_input.strip():
        # Auto-detect by extension
        VIDEO_EXTS = {".mp4", ".mov", ".avi", ".mkv", ".webm"}
        AUDIO_EXTS = {".mp3", ".wav", ".aac", ".m4a", ".ogg", ".flac"}

        raw = [u.strip() for u in url_input.replace("\n", ",").split(",") if u.strip()]
        auto_videos = []
        auto_audios = []
        unknown = []

        for u in raw:
            # Get extension from URL path (ignore query params)
            path_part = u.split("?")[0]
            ext = Path(path_part).suffix.lower()
            if ext in VIDEO_EXTS:
                auto_videos.append(u)
            elif ext in AUDIO_EXTS:
                auto_audios.append(u)
            else:
                unknown.append(u)

        # Preview detected split
        col_prev1, col_prev2 = st.columns(2)
        with col_prev1:
            st.markdown(f"**🎥 Video phát hiện: {len(auto_videos)}**")
            for i, u in enumerate(auto_videos, 1):
                st.caption(f"{i}. {u.split('/')[-1].split('?')[0]}")
        with col_prev2:
            st.markdown(f"**🎵 Audio phát hiện: {len(auto_audios)}**")
            for i, u in enumerate(auto_audios, 1):
                st.caption(f"{i}. {u.split('/')[-1].split('?')[0]}")

        if unknown:
            st.warning(f"⚠️ {len(unknown)} URL không xác định được loại (đuôi lạ): {', '.join(u.split('/')[-1] for u in unknown)}")

        if st.button("✅ Xác nhận URL", use_container_width=True):
            st.session_state.selected_videos = [
                {"name": u.split("/")[-1].split("?")[0], "direct_url": u} for u in auto_videos
            ]
            st.session_state.selected_audios = [
                {"name": u.split("/")[-1].split("?")[0], "direct_url": u} for u in auto_audios
            ]
            st.success(f"✅ {len(auto_videos)} video, {len(auto_audios)} audio đã xác nhận. Chuyển sang tab Xuất video.")


# ══════════════════════════════════════════════════════════
# TAB 3 – Export
# ══════════════════════════════════════════════════════════
with tab3:
    st.markdown("### 📋 Tóm tắt")

    col1, col2 = st.columns(2)
    with col1:
        st.markdown("**🎥 Videos sẽ ghép:**")
        if st.session_state.selected_videos:
            for i, v in enumerate(st.session_state.selected_videos, 1):
                st.markdown(f"`{i}.` {v['name']}")
        else:
            st.caption("Chưa chọn video nào.")

    with col2:
        st.markdown("**🎵 Audios sẽ ghép:**")
        if st.session_state.selected_audios:
            for i, a in enumerate(st.session_state.selected_audios, 1):
                st.markdown(f"`{i}.` {a['name']}")
        else:
            st.caption("(Không có – sẽ giữ audio gốc của video)")

    st.markdown("---")
    ready = bool(st.session_state.selected_videos)
    if not ready:
        st.warning("⚠️ Vui lòng chọn ít nhất 1 video trước khi xuất.")

    if ready and st.button("🚀 Bắt đầu ghép video", use_container_width=True, type="primary"):
        tmp_dir = tempfile.mkdtemp()
        local_videos = []
        local_audios = []

        # ── Download videos ───────────────────────────────
        st.markdown("#### ⬇️ Đang tải video…")
        prog_v = st.progress(0)
        for i, vf in enumerate(st.session_state.selected_videos):
            dest = os.path.join(tmp_dir, f"video_{i}{Path(vf['name']).suffix or '.mp4'}")
            url = vf.get("direct_url")
            if not url and st.session_state.auth_token:
                url = pcloud_get_download_link(st.session_state.auth_token, vf["fileid"])
            if url:
                st.caption(f"Downloading {vf['name']}…")
                ok = download_file(url, dest)
                if ok:
                    local_videos.append(dest)
            prog_v.progress((i + 1) / len(st.session_state.selected_videos))

        # ── Download audios ───────────────────────────────
        if st.session_state.selected_audios:
            st.markdown("#### ⬇️ Đang tải audio…")
            prog_a = st.progress(0)
            for i, af in enumerate(st.session_state.selected_audios):
                dest = os.path.join(tmp_dir, f"audio_{i}{Path(af['name']).suffix or '.mp3'}")
                url = af.get("direct_url")
                if not url and st.session_state.auth_token:
                    url = pcloud_get_download_link(st.session_state.auth_token, af["fileid"])
                if url:
                    st.caption(f"Downloading {af['name']}…")
                    ok = download_file(url, dest)
                    if ok:
                        local_audios.append(dest)
                prog_a.progress((i + 1) / len(st.session_state.selected_audios))

        if not local_videos:
            st.error("❌ Không tải được video nào. Kiểm tra lại URL/kết nối.")
        else:
            output_path = os.path.join(tmp_dir, output_filename)
            success, msg = merge_videos_and_audio(
                local_videos, local_audios, output_path,
                resolution=resolution, audio_mode=audio_mode,
            )
            if success:
                st.markdown(f'<div class="success-box">🎉 {msg}</div>', unsafe_allow_html=True)

                # Upload to pCloud folder 28528777183
                PCLOUD_FOLDER_ID = 28528777183
                if st.session_state.auth_token:
                    with st.spinner("☁️ Đang kiểm tra tên file & upload lên pCloud..."):
                        upload_result, final_name = pcloud_upload(
                            st.session_state.auth_token,
                            output_path,
                            PCLOUD_FOLDER_ID,
                            output_filename,
                        )
                    if upload_result.get("result") == 0:
                        meta = upload_result.get("metadata", [{}])
                        file_id = meta[0].get("fileid", "") if meta else ""
                        renamed_note = f"<br>⚠️ Đã đổi tên: <code>{output_filename}</code> → <code>{final_name}</code> (tránh trùng)" if final_name != output_filename else ""
                        st.markdown(f"""
                        <div class="success-box">
                        ☁️ <b>Upload pCloud thành công!</b><br>
                        File: <code>{final_name}</code><br>
                        Folder ID: <code>{PCLOUD_FOLDER_ID}</code><br>
                        File ID: <code>{file_id}</code>{renamed_note}
                        </div>
                        """, unsafe_allow_html=True)
                    else:
                        err = upload_result.get("error", "Unknown error")
                        st.markdown(f'<div class="error-box">❌ Upload pCloud thất bại: {err}<br>Bạn vẫn có thể tải xuống bên dưới.</div>', unsafe_allow_html=True)
                else:
                    st.warning("Chưa đăng nhập pCloud — bỏ qua upload. Tải xuống thủ công bên dưới.")

                # Local download fallback
                with open(output_path, "rb") as f:
                    st.download_button(
                        label="⬇️ Tải xuống video hoàn chỉnh",
                        data=f,
                        file_name=output_filename,
                        mime="video/mp4",
                        use_container_width=True,
                    )
                # Preview
                st.markdown("#### 👀 Xem trước")
                st.video(output_path)
            else:
                st.markdown(f'<div class="error-box">❌ {msg}</div>', unsafe_allow_html=True)
