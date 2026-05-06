import streamlit as st
import requests
import os
import subprocess
import tempfile
from pathlib import Path


st.set_page_config(page_title="🎬 Video Merger Pro", page_icon="🎬", layout="wide", initial_sidebar_state="expanded")


st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Syne:wght@400;600;800&family=DM+Sans:wght@300;400;500&display=swap');
html,body,[class*="css"]{font-family:'DM Sans',sans-serif;background:#0d0d0f;color:#e8e4dc;}
h1,h2,h3{font-family:'Syne',sans-serif;letter-spacing:-0.02em;}
.main-title{font-family:'Syne',sans-serif;font-size:2.4rem;font-weight:800;background:linear-gradient(135deg,#f5c842 0%,#ff6b35 50%,#e84393 100%);-webkit-background-clip:text;-webkit-text-fill-color:transparent;background-clip:text;}
.subtitle{color:#888;font-size:1rem;margin-bottom:1.5rem;}
.success-box{background:#0f2b1a;border:1px solid #1a5c30;border-radius:12px;padding:1rem 1.5rem;color:#4ade80;}
.error-box{background:#2b0f0f;border:1px solid #5c1a1a;border-radius:12px;padding:1rem 1.5rem;color:#f87171;}
.info-box{background:#0f1e2b;border:1px solid #1a3a5c;border-radius:12px;padding:1rem 1.5rem;color:#60a5fa;font-size:0.9rem;}
.warn-box{background:#2b220f;border:1px solid #5c440a;border-radius:12px;padding:1rem 1.5rem;color:#fbbf24;font-size:0.9rem;}
.stButton>button{background:linear-gradient(135deg,#f5c842,#ff6b35);color:#0d0d0f;border:none;border-radius:10px;font-family:'Syne',sans-serif;font-weight:700;font-size:1rem;}
[data-testid="stSidebar"]{background:#111113;border-right:1px solid #2a2a30;}
</style>
""", unsafe_allow_html=True)


# ── Auto-install FFmpeg ───────────────────────────────────
@st.cache_resource(show_spinner=False)
def ensure_ffmpeg():
    if subprocess.run(["which","ffmpeg"],capture_output=True).returncode==0:
        return True,"ok"
    for cmd in [["apt-get","install","-y","ffmpeg"],["apt","install","-y","ffmpeg"]]:
        try:
            r=subprocess.run(cmd,capture_output=True,text=True)
            if r.returncode==0: return True,"installed"
        except FileNotFoundError: pass
    return False,"FFmpeg not found"


# ── Dropbox helpers ───────────────────────────────────────
DBX_API     = "https://api.dropboxapi.com/2"
DBX_CONTENT = "https://content.dropboxapi.com/2"

def dbx_get_access_token(app_key, app_secret, refresh_token):
    """Exchange refresh_token for a fresh short-lived access token."""
    try:
        r = requests.post(
            "https://api.dropbox.com/oauth2/token",
            data={
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
                "client_id": app_key,
                "client_secret": app_secret,
            },
            timeout=15,
        )
        data = r.json()
        return data.get("access_token"), data.get("error_description", data.get("error"))
    except Exception as e:
        return None, str(e)


def dbx_verify(token):
    try:
        r=requests.post(f"{DBX_API}/users/get_current_account",
            headers={"Authorization":f"Bearer {token}"},timeout=10)
        return r.json() if r.status_code==200 else None
    except: return None

def dbx_list_names(token, folder):
    try:
        r=requests.post(f"{DBX_API}/files/list_folder",
            headers={"Authorization":f"Bearer {token}","Content-Type":"application/json"},
            json={"path":folder,"recursive":False},timeout=15)
        return {e["name"] for e in r.json().get("entries",[])} if r.status_code==200 else set()
    except: return set()

def unique_name(filename, existing):
    if filename not in existing: return filename
    stem,ext=Path(filename).stem,Path(filename).suffix
    i=1
    while f"{stem}_{i}{ext}" in existing: i+=1
    return f"{stem}_{i}{ext}"

def dbx_upload(token, file_path, folder, filename):
    import json as _json
    existing   = dbx_list_names(token, folder)
    final_name = unique_name(filename, existing)
    dest       = (folder+"/"+final_name).replace("//","/")
    size       = os.path.getsize(file_path)
    CHUNK      = 148*1024*1024  # 148 MB

    try:
        if size <= CHUNK:
            with open(file_path,"rb") as f:
                r=requests.post(f"{DBX_CONTENT}/files/upload",
                    headers={"Authorization":f"Bearer {token}",
                             "Dropbox-API-Arg":_json.dumps({"path":dest,"mode":"add","autorename":False}),
                             "Content-Type":"application/octet-stream"},
                    data=f, timeout=600)
            if r.status_code!=200:
                return False,final_name,f"Upload error {r.status_code}: {r.text[:300]}",None
        else:
            # Chunked session
            with open(file_path,"rb") as f:
                chunk=f.read(CHUNK)
                r=requests.post(f"{DBX_CONTENT}/files/upload_session/start",
                    headers={"Authorization":f"Bearer {token}",
                             "Dropbox-API-Arg":'{"close":false}',
                             "Content-Type":"application/octet-stream"},
                    data=chunk,timeout=600)
                if r.status_code!=200:
                    return False,final_name,f"Session start error: {r.text[:300]}",None
                sid=r.json()["session_id"]; offset=len(chunk)
                while True:
                    chunk=f.read(CHUNK)
                    if not chunk: break
                    requests.post(f"{DBX_CONTENT}/files/upload_session/append_v2",
                        headers={"Authorization":f"Bearer {token}",
                                 "Dropbox-API-Arg":_json.dumps({"cursor":{"session_id":sid,"offset":offset},"close":False}),
                                 "Content-Type":"application/octet-stream"},
                        data=chunk,timeout=600)
                    offset+=len(chunk)
                r=requests.post(f"{DBX_CONTENT}/files/upload_session/finish",
                    headers={"Authorization":f"Bearer {token}",
                             "Dropbox-API-Arg":_json.dumps({"cursor":{"session_id":sid,"offset":offset},"commit":{"path":dest,"mode":"add"}}),
                             "Content-Type":"application/octet-stream"},
                    data=b"",timeout=600)
                if r.status_code!=200:
                    return False,final_name,f"Session finish error: {r.text[:300]}",None

        # Shared link
        r2=requests.post(f"{DBX_API}/sharing/create_shared_link_with_settings",
            headers={"Authorization":f"Bearer {token}","Content-Type":"application/json"},
            json={"path":dest,"settings":{"requested_visibility":"public"}},timeout=15)
        url=None
        if r2.status_code==200:
            url=r2.json().get("url","").replace("www.dropbox.com","dl.dropboxusercontent.com").replace("?dl=0","?dl=1")
        elif r2.status_code==409:
            raw=r2.json().get("error",{}).get("shared_link_already_exists",{}).get("metadata",{}).get("url","")
            if raw: url=raw.replace("www.dropbox.com","dl.dropboxusercontent.com").replace("?dl=0","?dl=1")
        return True,final_name,"OK",url
    except Exception as e:
        return False,final_name,str(e),None


# ── Download helper ───────────────────────────────────────
def _resolve_mediafire_url(url):
    """Parse MediaFire page HTML to extract the real direct download URL."""
    import re
    try:
        hdrs = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,*/*;q=0.9",
            "Accept-Language": "en-US,en;q=0.5",
        }
        r = requests.get(url, headers=hdrs, timeout=20, allow_redirects=True)
        html = r.text
        # Try multiple patterns MediaFire uses
        patterns = [
            r'href=["\']([^"\']+)["\'][^>]*aria-label=["\']Download file',
            r'aria-label=["\']Download file["\'][^>]*href=["\']([^"\']+)',
            r'id=["\']downloadButton["\'][^>]*href=["\']([^"\']+)',
            r'href=["\']([^"\']+)["\'][^>]*id=["\']downloadButton',
            r'"downloadUrl"\s*:\s*"([^"]+)"',
            r"'downloadUrl'\s*:\s*'([^']+)'",
            r'https?://download\d+\.mediafire\.com/[A-Za-z0-9/_\-\.%]+',
        ]
        for pat in patterns:
            m = re.search(pat, html)
            if m:
                found = m.group(1) if '(' in pat and 'http' not in pat.split('(')[0] else m.group(0)
                found = found.replace('\/', '/').rstrip('.,)"\'')
                if found.startswith('http'):
                    return found
        return None
    except Exception:
        return None


def _normalize_download_url(url):
    """Convert any share/view link to a direct download URL."""
    import re

    # ── Dropbox: ensure dl=1 and use direct host ─────────
    if "dropbox.com" in url or "dropboxusercontent.com" in url:
        # Convert www.dropbox.com → dl.dropboxusercontent.com
        url = url.replace("www.dropbox.com", "dl.dropboxusercontent.com")
        url = url.replace("dl.dropbox.com", "dl.dropboxusercontent.com")
        # Replace dl=0 with dl=1, or append dl=1
        if "dl=0" in url:
            url = url.replace("dl=0", "dl=1")
        elif "dl=1" not in url:
            url += "&dl=1" if "?" in url else "?dl=1"
        return url

    # ── Google Drive ──────────────────────────────────────
    m = re.search(r"drive\.google\.com/file/d/([^/\?]+)", url)
    if m:
        return f"https://drive.google.com/uc?export=download&confirm=t&id={m.group(1)}"

    return url


def _download_with_requests(url, dest):
    """Download using requests library with browser headers."""
    HEADERS = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                      "AppleWebKit/537.36 (KHTML, like Gecko) "
                      "Chrome/124.0.0.0 Safari/537.36",
        "Accept": "*/*",
        "Accept-Encoding": "identity",
        "Connection": "keep-alive",
        "Referer": "https://www.dropbox.com/",
    }
    r = requests.get(url, stream=True, timeout=300,
                     headers=HEADERS, allow_redirects=True)
    r.raise_for_status()
    ct = r.headers.get("Content-Type", "")
    if "text/html" in ct and r.headers.get("Content-Length","0") == "21":
        # Tiny HTML = error page, not real content
        raise ValueError(f"Server returned HTML error page")
    size = 0
    with open(dest, "wb") as f:
        for chunk in r.iter_content(512*1024):
            f.write(chunk); size += len(chunk)
    if size < 1024:
        raise ValueError(f"File too small ({size} bytes)")
    return size


def _download_with_ytdlp(url, dest):
    """Download using yt-dlp as fallback — handles many video sources."""
    try:
        subprocess.run(["pip","install","yt-dlp","-q","--break-system-packages"],
                       capture_output=True)
    except Exception:
        pass
    r = subprocess.run([
        "yt-dlp",
        "--no-check-certificates",
        "--no-warnings",
        "--no-playlist",
        "-f", "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
        "-o", dest,
        url
    ], capture_output=True, text=True, timeout=600)
    if r.returncode != 0:
        raise ValueError(f"yt-dlp failed: {r.stderr[-300:]}")
    if not os.path.exists(dest) or os.path.getsize(dest) < 1024:
        raise ValueError("yt-dlp produced no output file")
    return os.path.getsize(dest)


def _download_with_ffmpeg(url, dest):
    """Download using ffmpeg input → copy — handles streams and direct links."""
    r = subprocess.run([
        "ffmpeg", "-y",
        "-user_agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "-headers", "Referer: https://www.dropbox.com/\r\nAccept: */*\r\n",
        "-i", url,
        "-c", "copy",
        "-movflags", "+faststart",
        dest
    ], capture_output=True, text=True, timeout=600)
    if r.returncode != 0:
        raise ValueError(f"ffmpeg failed: {r.stderr[-300:]}")
    if not os.path.exists(dest) or os.path.getsize(dest) < 1024:
        raise ValueError("ffmpeg produced no output")
    return os.path.getsize(dest)


def download_file(url, dest, dbx_token=None):
    """
    Universal downloader — tries multiple strategies:
    1. requests (direct)
    2. ffmpeg -i URL -c copy
    3. yt-dlp (YouTube, Vimeo, many others)
    Falls back gracefully with clear error messages.
    """
    url = url.strip()

    # MediaFire: resolve HTML page first
    if "mediafire.com" in url:
        direct = _resolve_mediafire_url(url)
        if direct:
            url = direct
        else:
            st.warning(f"⚠️ Không resolve được MediaFire URL: {url[:80]}")
            return False

    # Normalize URL (Dropbox dl=1, GDrive direct, etc.)
    normalized = _normalize_download_url(url)

    errors = []

    # ── Strategy 1: requests ──────────────────────────────
    try:
        size = _download_with_requests(normalized, dest)
        return True
    except Exception as e:
        errors.append(f"requests: {str(e)[:80]}")
        if os.path.exists(dest): os.remove(dest)

    # ── Strategy 2: ffmpeg ────────────────────────────────
    try:
        size = _download_with_ffmpeg(normalized, dest)
        return True
    except Exception as e:
        errors.append(f"ffmpeg: {str(e)[:80]}")
        if os.path.exists(dest): os.remove(dest)

    # ── Strategy 3: yt-dlp ───────────────────────────────
    try:
        size = _download_with_ytdlp(url, dest)  # use original URL for yt-dlp
        return True
    except Exception as e:
        errors.append(f"yt-dlp: {str(e)[:80]}")
        if os.path.exists(dest): os.remove(dest)

    # All failed
    st.warning(
        f"⚠️ Không tải được file sau 3 phương pháp:\n"
        + "\n".join(f"  • {e}" for e in errors)
        + f"\n\n📎 URL: `{url[:100]}`"
        + f"\n\n✅ **Giải pháp:** Upload file trực tiếp từ máy tính thay vì dùng URL."
    )
    return False

# ── FFmpeg helpers ────────────────────────────────────────
def get_duration(path):
    try:
        r=subprocess.run(["ffprobe","-v","error","-show_entries","format=duration",
                          "-of","default=noprint_wrappers=1:nokey=1",path],
                         capture_output=True,text=True)
        return float(r.stdout.strip())
    except: return None

def merge_videos_and_audio(video_paths,audio_paths,output_path,resolution="original",audio_mode="replace"):
    tmp=tempfile.mkdtemp()
    merged_video=os.path.join(tmp,"merged_video.mp4")
    merged_audio=os.path.join(tmp,"merged_audio.aac")
    scale=""
    if resolution=="youtube": scale="scale=1280:720:force_original_aspect_ratio=decrease,pad=1280:720:(ow-iw)/2:(oh-ih)/2"
    elif resolution=="tiktok": scale="scale=576:1024:force_original_aspect_ratio=decrease,pad=576:1024:(ow-iw)/2:(oh-ih)/2"

    # Re-encode videos
    reencoded=[]
    prog=st.progress(0,text="Re-encoding videos...")
    for i,vp in enumerate(video_paths):
        out=os.path.join(tmp,f"v{i}.mp4")
        cmd=["ffmpeg","-y","-i",vp]+(["-vf",scale] if scale else [])+["-c:v","libx264","-preset","fast","-crf","23","-c:a","aac","-b:a","128k","-ar","44100",out]
        r=subprocess.run(cmd,capture_output=True)
        if r.returncode!=0: return False,f"Re-encode failed [{os.path.basename(vp)}]:\n{r.stderr.decode()}"
        reencoded.append(out)
        prog.progress((i+1)/len(video_paths),text=f"Re-encoding video {i+1}/{len(video_paths)}...")
    prog.empty()

    # Concat videos
    txt=os.path.join(tmp,"concat.txt")
    open(txt,"w").write("\n".join(f"file '{p}'" for p in reencoded))
    st.info("Concatenating videos...")
    r=subprocess.run(["ffmpeg","-y","-f","concat","-safe","0","-i",txt,"-c","copy",merged_video],capture_output=True)
    if r.returncode!=0: return False,f"Concat failed:\n{r.stderr.decode()}"
    video_dur=get_duration(merged_video)

    if audio_paths:
        # Re-encode each audio to AAC
        ra_list=[]
        st.info("Re-encoding audio files...")
        for i,ap in enumerate(audio_paths):
            out=os.path.join(tmp,f"ra{i}.aac")
            r=subprocess.run(["ffmpeg","-y","-i",ap,"-vn","-c:a","aac","-b:a","192k","-ar","44100","-ac","2",out],capture_output=True)
            if r.returncode!=0: return False,f"Audio re-encode failed [{os.path.basename(ap)}]:\n{r.stderr.decode()}"
            ra_list.append(out)

        # Concat audios
        atxt=os.path.join(tmp,"audio_concat.txt")
        open(atxt,"w").write("\n".join(f"file '{p}'" for p in ra_list))
        st.info("Merging audio tracks...")
        r=subprocess.run(["ffmpeg","-y","-f","concat","-safe","0","-i",atxt,"-c","copy",merged_audio],capture_output=True)
        if r.returncode!=0: return False,f"Audio merge failed:\n{r.stderr.decode()}"
        audio_dur=get_duration(merged_audio)

        # Adjust video to match audio duration
        video_for_merge=merged_video
        if audio_dur:
            adj=os.path.join(tmp,"adjusted.mp4")
            if video_dur and audio_dur>video_dur:
                st.info(f"Video {video_dur:.1f}s < Audio {audio_dur:.1f}s — looping video...")
                ac=["ffmpeg","-y","-stream_loop","-1","-i",merged_video,"-t",str(audio_dur),"-c:v","libx264","-preset","fast","-crf","23","-an",adj]
            else:
                st.info(f"Video {video_dur:.1f}s > Audio {audio_dur:.1f}s — trimming video...")
                ac=["ffmpeg","-y","-i",merged_video,"-t",str(audio_dur),"-c:v","libx264","-preset","fast","-crf","23","-an",adj]
            r=subprocess.run(ac,capture_output=True)
            if r.returncode!=0: return False,f"Video adjust failed:\n{r.stderr.decode()}"
            video_for_merge=adj

        st.info("Combining video + audio...")
        if audio_mode=="replace":
            cmd=["ffmpeg","-y","-i",video_for_merge,"-i",merged_audio,"-c:v","copy","-c:a","aac","-b:a","192k","-map","0:v:0","-map","1:a:0","-shortest",output_path]
        else:
            cmd=["ffmpeg","-y","-i",video_for_merge,"-i",merged_audio,"-filter_complex","[0:a][1:a]amix=inputs=2:duration=shortest:dropout_transition=2[a]","-map","0:v","-map","[a]","-c:v","copy","-c:a","aac","-b:a","192k","-shortest",output_path]
    else:
        cmd=["ffmpeg","-y","-i",merged_video,"-c","copy",output_path]

    r=subprocess.run(cmd,capture_output=True)
    if r.returncode!=0: return False,f"Final merge failed:\n{r.stderr.decode()}"
    return True,"Video created successfully!"




# ─────────────────────────────────────────────
# EDIT VIDEO: Snow + Zoom In/Out effect
# Strategy: PIL draws snow frames → pipe to ffmpeg as image sequence overlay
# ─────────────────────────────────────────────
IMAGE_EXTS_EDIT = {".jpg",".jpeg",".png",".webp",".bmp",".gif",".tiff"}

def _install_pillow():
    try:
        from PIL import Image, ImageDraw
        return True
    except ImportError:
        subprocess.run(["pip","install","Pillow","--break-system-packages","-q"], capture_output=True)
        try:
            from PIL import Image, ImageDraw
            return True
        except ImportError:
            return False

def _make_snow_video(w, h, fps, total_frames, snow_count, snow_seed, tmp):
    """Generate a transparent snow overlay video using PIL frame-by-frame."""
    import random
    from PIL import Image, ImageDraw
    rng = random.Random(snow_seed)
    flakes = [{
        "x":    rng.uniform(0, w),
        "y":    rng.uniform(0, h),
        "vy":   rng.uniform(40, 160),   # pixels/sec falling speed
        "vx":   rng.uniform(-15, 15),   # pixels/sec horizontal drift
        "r":    rng.randint(2, 5),       # radius
        "alpha":rng.randint(140, 255),   # opacity
    } for _ in range(snow_count)]

    frames_dir = os.path.join(tmp, "snow_frames")
    os.makedirs(frames_dir, exist_ok=True)

    for fi in range(total_frames):
        t = fi / fps
        img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        for flk in flakes:
            fx = (flk["x"] + flk["vx"] * t) % w
            fy = (flk["y"] + flk["vy"] * t) % h
            r  = flk["r"]
            a  = flk["alpha"]
            draw.ellipse([fx-r, fy-r, fx+r, fy+r], fill=(255, 255, 255, a))
        frame_path = os.path.join(frames_dir, f"f{fi:05d}.png")
        img.save(frame_path)

    # Encode frames → snow video (RGBA via png pipe)
    snow_vid = os.path.join(tmp, "snow_overlay.mov")
    r = subprocess.run([
        "ffmpeg", "-y",
        "-framerate", str(fps),
        "-i", os.path.join(frames_dir, "f%05d.png"),
        "-c:v", "qtrle",   # lossless with alpha
        "-pix_fmt", "argb",
        snow_vid
    ], capture_output=True)
    if r.returncode != 0:
        # fallback: use prores_ks with alpha
        snow_vid = os.path.join(tmp, "snow_overlay.mov")
        r2 = subprocess.run([
            "ffmpeg", "-y",
            "-framerate", str(fps),
            "-i", os.path.join(frames_dir, "f%05d.png"),
            "-c:v", "prores_ks", "-profile:v", "4444",
            "-pix_fmt", "yuva444p10le",
            snow_vid
        ], capture_output=True)
        if r2.returncode != 0:
            return None, r2.stderr.decode()[-400:]
    return snow_vid, None


def make_snow_zoom_video(media_paths, output_path, fps=30,
                          duration_per_image=5.0, zoom_max=1.15,
                          snow_count=60, audio_path=None):
    """
    For each image/video:
      1. PIL renders every zoom frame to JPEG files (no ffmpeg filter needed)
      2. ffmpeg encodes JPEG sequence -> zoomed.mp4
      3. PIL draws snow frames -> snow_overlay.mov (RGBA)
      4. ffmpeg overlays snow on zoomed video -> clip.mp4
    Concat all clips, optionally add audio.
    """
    import random, shutil, math
    from PIL import Image as PILImg, ImageDraw as PILDraw, ImageOps as PILOps

    tmp = tempfile.mkdtemp()
    clips = []
    prog = st.progress(0, text="Dang xu ly...")
    total = len(media_paths)

    # Snow flake definitions (fixed seed)
    rng = random.Random(42)
    base_flakes = [{
        "x":     rng.uniform(0, 1),      # fractional start x
        "y":     rng.uniform(0, 1),      # fractional start y
        "vy":    rng.uniform(0.04, 0.16), # fractional/sec falling
        "vx":    rng.uniform(-0.01, 0.01),
        "r":     rng.randint(2, 5),
        "alpha": rng.randint(130, 240),
    } for _ in range(snow_count)]

    for idx, mpath in enumerate(media_paths):
        ext = Path(mpath).suffix.lower()
        out_clip = os.path.join(tmp, f"clip_{idx}.mp4")

        # ── 1. Get dimensions via PIL (images) or ffprobe (video) ──
        w, h = 0, 0
        if ext in IMAGE_EXTS_EDIT:
            try:
                with PILImg.open(mpath) as im:
                    im = PILOps.exif_transpose(im)
                    w, h = im.size
            except Exception:
                pass
        if w == 0 or h == 0:
            probe = subprocess.run(
                ["ffprobe","-v","error","-select_streams","v:0",
                 "-show_entries","stream=width,height","-of","csv=p=0", mpath],
                capture_output=True, text=True)
            try:
                w, h = map(int, probe.stdout.strip().split(","))
            except Exception:
                w, h = 1280, 720
        # Even dims, cap at 1920
        MAX_DIM = 1920
        if max(w, h) > MAX_DIM:
            scale = MAX_DIM / max(w, h)
            w, h = int(w * scale), int(h * scale)
        w = w if w % 2 == 0 else w - 1
        h = h if h % 2 == 0 else h - 1
        w = max(w, 2); h = max(h, 2)

        # ── 2. Clip duration ────────────────────────────────
        if ext in IMAGE_EXTS_EDIT:
            clip_dur = duration_per_image
        else:
            dur_p = subprocess.run(
                ["ffprobe","-v","error","-show_entries","format=duration",
                 "-of","default=noprint_wrappers=1:nokey=1", mpath],
                capture_output=True, text=True)
            try: clip_dur = float(dur_p.stdout.strip())
            except: clip_dur = duration_per_image

        n_frames = max(1, int(fps * clip_dur))
        half = n_frames // 2

        # ── 3. Render zoom frames with PIL ─────────────────
        frames_dir = os.path.join(tmp, f"zf_{idx}")
        os.makedirs(frames_dir, exist_ok=True)

        if ext in IMAGE_EXTS_EDIT:
            # Validate & convert file first — PIL may fail on corrupt/non-image files
            converted = os.path.join(tmp, f"converted_{idx}.jpg")
            try:
                with PILImg.open(mpath) as _raw:
                    _raw = PILOps.exif_transpose(_raw).convert("RGB")
                    if w == 0 or h == 0:
                        w, h = _raw.size
                        w = (w if w%2==0 else w-1)
                        h = (h if h%2==0 else h-1)
                    _raw.resize((w, h), PILImg.LANCZOS).save(converted, "JPEG", quality=95)
            except Exception as _pe:
                # Try ffmpeg to decode as last resort
                _r = subprocess.run([
                    "ffmpeg","-y","-i",mpath,
                    "-frames:v","1","-q:v","2",converted
                ], capture_output=True)
                if _r.returncode != 0 or not os.path.exists(converted):
                    return False, f"Khong mo duoc anh [{os.path.basename(mpath)}]: {_pe}"
                # Re-read converted to get proper size
                with PILImg.open(converted) as _c:
                    w, h = _c.size
                    w = (w if w%2==0 else w-1)
                    h = (h if h%2==0 else h-1)

            with PILImg.open(converted) as im:
                im = im.convert("RGB").resize((w, h), PILImg.LANCZOS)
                for fi in range(n_frames):
                    if fi < half:
                        zf = 1.0 + (zoom_max - 1.0) * (fi / max(half, 1))
                    else:
                        zf = 1.0 + (zoom_max - 1.0) * (1.0 - (fi - half) / max(n_frames - half - 1, 1))
                    cw = max(1, int(w / zf))
                    ch = max(1, int(h / zf))
                    x0 = (w - cw) // 2
                    y0 = (h - ch) // 2
                    frame = im.crop((x0, y0, x0+cw, y0+ch)).resize((w, h), PILImg.LANCZOS)
                    frame.save(os.path.join(frames_dir, f"f{fi:06d}.jpg"), "JPEG", quality=90)
        else:
            # Extract video frames then apply zoom
            extract_dir = os.path.join(tmp, f"vf_{idx}")
            os.makedirs(extract_dir, exist_ok=True)
            subprocess.run([
                "ffmpeg", "-y", "-i", mpath,
                "-vf", f"scale={w}:{h}",
                "-q:v", "2",
                os.path.join(extract_dir, "f%06d.jpg")
            ], capture_output=True)
            src_frames = sorted(os.listdir(extract_dir))
            total_src = len(src_frames)
            for fi in range(n_frames):
                # map fi to source frame (loop if needed)
                si = min(fi, total_src - 1) if total_src > 0 else 0
                src_path = os.path.join(extract_dir, src_frames[si]) if total_src > 0 else None
                if src_path and os.path.exists(src_path):
                    with PILImg.open(src_path) as im:
                        im = im.convert("RGB").resize((w, h), PILImg.LANCZOS)
                        if fi < half:
                            zf = 1.0 + (zoom_max - 1.0) * (fi / max(half, 1))
                        else:
                            zf = 1.0 + (zoom_max - 1.0) * (1.0 - (fi - half) / max(n_frames - half - 1, 1))
                        cw = max(1, int(w / zf))
                        ch = max(1, int(h / zf))
                        x0 = (w - cw) // 2
                        y0 = (h - ch) // 2
                        frame = im.crop((x0, y0, x0 + cw, y0 + ch)).resize((w, h), PILImg.LANCZOS)
                        frame.save(os.path.join(frames_dir, f"f{fi:06d}.jpg"), "JPEG", quality=90)

        # Check frames exist
        frame_files = sorted(os.listdir(frames_dir))
        if not frame_files:
            return False, f"Khong tao duoc frame zoom cho [{os.path.basename(mpath)}]"

        # ── 4. Encode zoom frames → zoomed.mp4 ─────────────
        zoomed = os.path.join(tmp, f"zoomed_{idx}.mp4")
        r = subprocess.run([
            "ffmpeg", "-y",
            "-framerate", str(fps),
            "-i", os.path.join(frames_dir, "f%06d.jpg"),
            "-c:v", "libx264", "-preset", "fast", "-crf", "23",
            "-pix_fmt", "yuv420p", "-an",
            zoomed
        ], capture_output=True)
        if r.returncode != 0:
            return False, f"Encode zoom that bai [{os.path.basename(mpath)}]:\n{r.stderr.decode()[-400:]}"

        # ── 5. Render snow frames with PIL ─────────────────
        st.caption(f"Ve tuyet cho clip {idx+1}/{total}...")
        snow_dir = os.path.join(tmp, f"sf_{idx}")
        os.makedirs(snow_dir, exist_ok=True)
        for fi in range(n_frames):
            t = fi / fps
            snow_img = PILImg.new("RGBA", (w, h), (0, 0, 0, 0))
            draw = PILDraw.Draw(snow_img)
            for flk in base_flakes:
                fx = ((flk["x"] + flk["vx"] * t) % 1.0) * w
                fy = ((flk["y"] + flk["vy"] * t) % 1.0) * h
                rv = flk["r"]
                draw.ellipse([fx-rv, fy-rv, fx+rv, fy+rv],
                             fill=(255, 255, 255, flk["alpha"]))
            snow_img.save(os.path.join(snow_dir, f"s{fi:06d}.png"))

        # ── 6. Encode snow frames → snow.mp4 (white on black for overlay) ─
        snow_mp4 = os.path.join(tmp, f"snow_{idx}.mp4")
        r = subprocess.run([
            "ffmpeg", "-y",
            "-framerate", str(fps),
            "-i", os.path.join(snow_dir, "s%06d.png"),
            "-vf", "colorchannelmixer=aa=1",
            "-c:v", "libx264", "-preset", "fast", "-crf", "18",
            "-pix_fmt", "yuv420p", "-an",
            snow_mp4
        ], capture_output=True)
        if r.returncode != 0:
            return False, f"Encode snow that bai: {r.stderr.decode()[-300:]}"

        # ── 7. Overlay snow (lighten blend) on zoomed video ─
        # Use blend filter: lighten mode keeps the brighter pixel → snow shows as white
        r = subprocess.run([
            "ffmpeg", "-y",
            "-i", zoomed,
            "-i", snow_mp4,
            "-filter_complex",
            "[0:v][1:v]blend=all_mode=lighten:all_opacity=0.85",
            "-c:v", "libx264", "-preset", "fast", "-crf", "23",
            "-pix_fmt", "yuv420p", "-an",
            out_clip
        ], capture_output=True)
        if r.returncode != 0:
            return False, f"Overlay that bai [{os.path.basename(mpath)}]:\n{r.stderr.decode()[-400:]}"

        clips.append(out_clip)
        prog.progress((idx+1)/total, text=f"Xong {idx+1}/{total}: {os.path.basename(mpath)}")

    prog.empty()

    # ── Concat all clips ──────────────────────────────────
    st.info("Ghep tat ca clip...")
    ctxt = os.path.join(tmp, "edit_concat.txt")
    with open(ctxt, "w") as f:
        f.write("\n".join(f"file '{c}'" for c in clips))
    cout = os.path.join(tmp, "edit_concat.mp4")
    r = subprocess.run(
        ["ffmpeg","-y","-f","concat","-safe","0","-i",ctxt,"-c","copy",cout],
        capture_output=True)
    if r.returncode != 0:
        return False, f"Concat that bai:\n{r.stderr.decode()[-400:]}"

    # ── Add audio ─────────────────────────────────────────
    if audio_path and os.path.exists(audio_path):
        st.info("Ghep audio...")
        vid_dur = get_duration(cout)
        aud_dur = get_duration(audio_path)
        aac = os.path.join(tmp, "edit_audio.aac")
        subprocess.run(["ffmpeg","-y","-i",audio_path,"-vn",
                        "-c:a","aac","-b:a","192k","-ar","44100","-ac","2",aac],
                       capture_output=True)
        adj = os.path.join(tmp, "edit_adj.mp4")
        if aud_dur and vid_dur and aud_dur > vid_dur:
            subprocess.run(["ffmpeg","-y","-stream_loop","-1","-i",cout,
                            "-t",str(aud_dur),"-c:v","libx264","-preset","fast",
                            "-crf","23","-an",adj], capture_output=True)
        else:
            subprocess.run(["ffmpeg","-y","-i",cout,
                            "-t",str(aud_dur or vid_dur),"-c:v","libx264",
                            "-preset","fast","-crf","23","-an",adj], capture_output=True)
        r = subprocess.run([
            "ffmpeg","-y","-i",adj,"-i",aac,
            "-c:v","copy","-c:a","aac","-b:a","192k",
            "-map","0:v:0","-map","1:a:0","-shortest",output_path
        ], capture_output=True)
    else:
        shutil.copy(cout, output_path)
        r = type("R", (), {"returncode": 0})()

    if r.returncode != 0:
        return False, f"Loi ghep audio:\n{r.stderr.decode()[-400:]}"
    return True, "Edit video hoan tat!"



# ─────────────────────────────────────────────
# FIRE PARTICLES effect (embers floating up)
# ─────────────────────────────────────────────
def make_fire_particles_video(media_paths, output_path, fps=30,
                               duration_per_image=5.0,
                               particle_count=60,
                               zoom_max=1.08,
                               effect_type="fire",
                               audio_path=None):
    """
    Apply animated particle effect on each image/video.
    effect_type: "fire" | "golden" | "heaven" | "holy_dust" | "fireflies"
    """
    import random, math, shutil
    from PIL import Image as PILImg, ImageDraw as PILDraw, ImageOps as PILOps

    if not _install_pillow():
        return False, "Khong cai duoc Pillow."

    tmp = tempfile.mkdtemp()
    clips = []
    prog = st.progress(0, text="Dang xu ly...")
    total = len(media_paths)
    rng = random.Random(99)

    # ── Particle presets ─────────────────────────────────
    def _make_particles(count, effect):
        pts = []
        for _ in range(count):
            if effect == "fire":
                pts.append({
                    "x": rng.uniform(0.05, 0.95),
                    "y": rng.uniform(0.75, 1.1),
                    "vy": rng.uniform(0.07, 0.22),
                    "vx": rng.uniform(-0.01, 0.01),
                    "wobble": rng.uniform(0.005, 0.02),
                    "wfreq": rng.uniform(1.5, 4.0),
                    "r": rng.uniform(2.5, 6.0),
                    "colors": [(255,240,80),(255,200,30),(255,140,10),(255,80,10)],
                    "phase": rng.uniform(0, 1.0),
                    "life": rng.uniform(0.6, 1.4),
                    "glow_mult": 3,
                    "alpha_base": 230,
                })
            elif effect == "golden":
                pts.append({
                    "x": rng.uniform(0.0, 1.0),
                    "y": rng.uniform(0.0, 1.2),
                    "vy": rng.uniform(-0.04, -0.01),   # float upward slowly
                    "vx": rng.uniform(-0.008, 0.008),
                    "wobble": rng.uniform(0.008, 0.025),
                    "wfreq": rng.uniform(0.5, 1.5),
                    "r": rng.uniform(1.5, 4.5),
                    "colors": [(255,230,80),(255,215,50),(255,200,100),(240,190,40),(255,245,120)],
                    "phase": rng.uniform(0, 1.0),
                    "life": rng.uniform(2.0, 4.0),
                    "glow_mult": 5,
                    "alpha_base": 200,
                })
            elif effect == "heaven":
                pts.append({
                    "x": rng.uniform(0.0, 1.0),
                    "y": rng.uniform(-0.2, 1.0),
                    "vy": rng.uniform(0.02, 0.07),     # fall gently from top
                    "vx": rng.uniform(-0.005, 0.005),
                    "wobble": rng.uniform(0.01, 0.03),
                    "wfreq": rng.uniform(0.3, 0.8),
                    "r": rng.uniform(2.0, 7.0),
                    "colors": [(255,255,255),(230,240,255),(210,225,255),(255,250,240)],
                    "phase": rng.uniform(0, 1.0),
                    "life": rng.uniform(3.0, 6.0),
                    "glow_mult": 6,
                    "alpha_base": 180,
                })
            elif effect == "holy_dust":
                pts.append({
                    "x": rng.uniform(0.0, 1.0),
                    "y": rng.uniform(0.0, 1.0),
                    "vy": rng.uniform(-0.015, 0.015),
                    "vx": rng.uniform(-0.008, 0.008),
                    "wobble": rng.uniform(0.003, 0.012),
                    "wfreq": rng.uniform(0.4, 1.2),
                    "r": rng.uniform(0.8, 3.0),
                    "colors": [(255,255,220),(255,250,200),(230,220,255),(255,240,180),(200,220,255)],
                    "phase": rng.uniform(0, 1.0),
                    "life": rng.uniform(2.5, 5.0),
                    "glow_mult": 7,
                    "alpha_base": 160,
                })
            elif effect == "fireflies":
                pts.append({
                    "x": rng.uniform(0.05, 0.95),
                    "y": rng.uniform(0.1, 0.9),
                    "vy": rng.uniform(-0.025, 0.025),
                    "vx": rng.uniform(-0.02, 0.02),
                    "wobble": rng.uniform(0.02, 0.06),
                    "wfreq": rng.uniform(0.3, 1.0),
                    "r": rng.uniform(2.0, 5.0),
                    "colors": [(180,255,100),(150,255,80),(200,255,120),(160,240,90),(140,230,100)],
                    "phase": rng.uniform(0, 1.0),
                    "life": rng.uniform(1.5, 3.5),
                    "glow_mult": 8,
                    "alpha_base": 200,
                    "blink_freq": rng.uniform(0.5, 1.5),  # blink speed
                })
        return pts

    def _draw_particles(draw, particles, t, w, h, effect):
        for p in particles:
            life = p["life"]
            cycle_t = (t + p["phase"] * life) % life
            age = cycle_t / life

            # Position
            px = (p["x"] + p["vx"]*cycle_t +
                  p["wobble"] * math.sin(2*math.pi*p["wfreq"]*cycle_t)) * w
            py = (p["y"] + p["vy"]*cycle_t) * h

            if py < -30 or py > h+30 or px < -30 or px > w+30:
                continue

            # Fade
            if effect in ("fire",):
                # Fire: bright young, fade on rise
                fade = max(0.0, 1.0 - age)
                alpha = int(p["alpha_base"] * fade * fade)
            elif effect == "golden":
                # Golden: sine pulse — twinkle
                fade = 0.5 + 0.5 * math.sin(2*math.pi * age + p["phase"]*6)
                alpha = int(p["alpha_base"] * fade)
            elif effect == "heaven":
                # Heaven: fade in then fade out gently
                fade = math.sin(math.pi * age)
                alpha = int(p["alpha_base"] * fade)
            elif effect == "holy_dust":
                # Holy dust: slow pulse shimmer
                fade = 0.4 + 0.6 * abs(math.sin(2*math.pi * age * 1.5))
                alpha = int(p["alpha_base"] * fade)
            elif effect == "fireflies":
                # Fireflies: blink on/off slowly
                blink = 0.5 + 0.5 * math.sin(2*math.pi * p.get("blink_freq",1.0) * cycle_t)
                fade = math.sin(math.pi * age)
                alpha = int(p["alpha_base"] * fade * blink)

            if alpha < 8:
                continue

            r_draw = max(0.5, p["r"] * (0.6 + 0.4*(1.0-age)))
            col = rng.choice(p["colors"])
            gm = p.get("glow_mult", 4)

            # Outer glow (large, very transparent)
            gr = r_draw * gm
            draw.ellipse([px-gr, py-gr, px+gr, py+gr],
                         fill=col+(max(0,alpha//8),))
            # Mid glow
            mr = r_draw * (gm//2)
            draw.ellipse([px-mr, py-mr, px+mr, py+mr],
                         fill=col+(max(0,alpha//3),))
            # Core
            ri = max(1, int(r_draw))
            draw.ellipse([px-ri, py-ri, px+ri, py+ri],
                         fill=col+(min(255,alpha),))
            # Bright center
            if ri >= 2:
                draw.ellipse([px-1, py-1, px+1, py+1],
                             fill=(255,255,255,min(255,alpha+50)))

    particles = _make_particles(particle_count, effect_type)

    for idx, mpath in enumerate(media_paths):
        ext = Path(mpath).suffix.lower()
        out_clip = os.path.join(tmp, f"clip_{idx}.mp4")

        # ── Dimensions ───────────────────────────────────
        w, h = 0, 0
        if ext in IMAGE_EXTS_EDIT:
            try:
                with PILImg.open(mpath) as im:
                    im = PILOps.exif_transpose(im)
                    w, h = im.size
            except Exception:
                pass
        if w == 0 or h == 0:
            probe = subprocess.run(
                ["ffprobe","-v","error","-select_streams","v:0",
                 "-show_entries","stream=width,height","-of","csv=p=0", mpath],
                capture_output=True, text=True)
            try: w, h = map(int, probe.stdout.strip().split(","))
            except: w, h = 1280, 720
        MAX_DIM = 1920
        if max(w,h) > MAX_DIM:
            scale = MAX_DIM / max(w,h)
            w, h = int(w*scale), int(h*scale)
        w = max(2, w if w%2==0 else w-1)
        h = max(2, h if h%2==0 else h-1)

        # ── Duration ──────────────────────────────────────
        if ext in IMAGE_EXTS_EDIT:
            clip_dur = duration_per_image
        else:
            dur_p = subprocess.run(
                ["ffprobe","-v","error","-show_entries","format=duration",
                 "-of","default=noprint_wrappers=1:nokey=1", mpath],
                capture_output=True, text=True)
            try: clip_dur = float(dur_p.stdout.strip())
            except: clip_dur = duration_per_image

        n_frames = max(1, int(fps * clip_dur))
        half = n_frames // 2

        # ── Render frames ─────────────────────────────────
        frames_dir = os.path.join(tmp, f"ff_{idx}")
        os.makedirs(frames_dir, exist_ok=True)

        if ext in IMAGE_EXTS_EDIT:
            try:
                with PILImg.open(mpath) as im:
                    src = PILOps.exif_transpose(im).convert("RGB").resize((w,h), PILImg.LANCZOS)
            except Exception as e:
                return False, f"Khong mo anh [{os.path.basename(mpath)}]: {e}"

            for fi in range(n_frames):
                t = fi / fps
                if fi < half:
                    zf = 1.0 + (zoom_max-1.0)*(fi/max(half,1))
                else:
                    zf = 1.0 + (zoom_max-1.0)*(1.0-(fi-half)/max(n_frames-half-1,1))
                cw = max(1,int(w/zf)); ch = max(1,int(h/zf))
                x0=(w-cw)//2; y0=(h-ch)//2
                frame = src.crop((x0,y0,x0+cw,y0+ch)).resize((w,h), PILImg.LANCZOS).copy()
                draw = PILDraw.Draw(frame, "RGBA")
                _draw_particles(draw, particles, t, w, h, effect_type)
                frame.save(os.path.join(frames_dir, f"f{fi:06d}.jpg"), "JPEG", quality=88)
        else:
            extract_dir = os.path.join(tmp, f"vfe_{idx}")
            os.makedirs(extract_dir, exist_ok=True)
            subprocess.run([
                "ffmpeg","-y","-i",mpath,"-vf",f"scale={w}:{h}",
                "-q:v","2", os.path.join(extract_dir,"f%06d.jpg")
            ], capture_output=True)
            src_frames = sorted(os.listdir(extract_dir))
            total_src = len(src_frames)
            for fi in range(n_frames):
                si = min(fi, total_src-1) if total_src > 0 else 0
                spath = os.path.join(extract_dir, src_frames[si]) if total_src > 0 else None
                if not spath or not os.path.exists(spath): continue
                t = fi / fps
                with PILImg.open(spath) as im:
                    frame = im.convert("RGB").resize((w,h), PILImg.LANCZOS).copy()
                if fi < half:
                    zf = 1.0+(zoom_max-1.0)*(fi/max(half,1))
                else:
                    zf = 1.0+(zoom_max-1.0)*(1.0-(fi-half)/max(n_frames-half-1,1))
                cw=max(1,int(w/zf)); ch=max(1,int(h/zf))
                x0=(w-cw)//2; y0=(h-ch)//2
                frame=frame.crop((x0,y0,x0+cw,y0+ch)).resize((w,h),PILImg.LANCZOS).copy()
                draw=PILDraw.Draw(frame,"RGBA")
                _draw_particles(draw, particles, t, w, h, effect_type)
                frame.save(os.path.join(frames_dir, f"f{fi:06d}.jpg"), "JPEG", quality=88)

        if not os.listdir(frames_dir):
            return False, f"Khong tao duoc frame [{os.path.basename(mpath)}]"

        r = subprocess.run([
            "ffmpeg","-y","-framerate",str(fps),
            "-i", os.path.join(frames_dir,"f%06d.jpg"),
            "-c:v","libx264","-preset","fast","-crf","22",
            "-pix_fmt","yuv420p","-an", out_clip
        ], capture_output=True)
        if r.returncode != 0:
            return False, f"Encode that bai [{os.path.basename(mpath)}]:\n{r.stderr.decode()[-400:]}"

        clips.append(out_clip)
        prog.progress((idx+1)/total, text=f"Xong {idx+1}/{total}: {os.path.basename(mpath)}")

    prog.empty()

    # Concat
    st.info("Ghep clip...")
    ctxt = os.path.join(tmp,"concat.txt")
    with open(ctxt,"w") as f:
        f.write("\n".join(f"file '{c}'" for c in clips))
    cout = os.path.join(tmp,"concat.mp4")
    r = subprocess.run(
        ["ffmpeg","-y","-f","concat","-safe","0","-i",ctxt,"-c","copy",cout],
        capture_output=True)
    if r.returncode != 0:
        return False, f"Concat that bai:\n{r.stderr.decode()[-400:]}"

    # Audio
    if audio_path and os.path.exists(audio_path):
        st.info("Ghep audio...")
        vid_dur=get_duration(cout); aud_dur=get_duration(audio_path)
        aac=os.path.join(tmp,"aud.aac")
        subprocess.run(["ffmpeg","-y","-i",audio_path,"-vn","-c:a","aac",
                        "-b:a","192k","-ar","44100","-ac","2",aac], capture_output=True)
        adj=os.path.join(tmp,"adj.mp4")
        if aud_dur and vid_dur and aud_dur>vid_dur:
            subprocess.run(["ffmpeg","-y","-stream_loop","-1","-i",cout,"-t",str(aud_dur),
                            "-c:v","libx264","-preset","fast","-crf","22","-an",adj], capture_output=True)
        else:
            subprocess.run(["ffmpeg","-y","-i",cout,"-t",str(aud_dur or vid_dur),
                            "-c:v","libx264","-preset","fast","-crf","22","-an",adj], capture_output=True)
        r=subprocess.run(["ffmpeg","-y","-i",adj,"-i",aac,"-c:v","copy","-c:a","aac",
                          "-b:a","192k","-map","0:v:0","-map","1:a:0","-shortest",output_path],
                         capture_output=True)
    else:
        shutil.copy(cout, output_path)
        r=type("R",(),{"returncode":0})()

    if r.returncode != 0:
        return False, f"Loi ghep audio:\n{r.stderr.decode()[-400:]}"
    return True, f"Video hieu ung '{effect_type}' hoan tat!"






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
# BULK VIDEO: nhiều cặp video+audio → nhiều video riêng
# ─────────────────────────────────────────────
def bulk_merge_one(video_path, audio_path, output_path, resolution="original", audio_mode="replace"):
    """Merge 1 video + 1 audio → 1 output. Returns (success, msg)."""
    tmp = tempfile.mkdtemp()
    merged_audio = os.path.join(tmp, "audio.aac")

    # Get durations
    video_dur = get_duration(video_path)
    audio_dur = get_duration(audio_path) if audio_path else None

    # Scale filter
    scale = ""
    if resolution == "youtube":
        scale = "scale=1280:720:force_original_aspect_ratio=decrease,pad=1280:720:(ow-iw)/2:(oh-ih)/2"
    elif resolution == "tiktok":
        scale = "scale=576:1024:force_original_aspect_ratio=decrease,pad=576:1024:(ow-iw)/2:(oh-ih)/2"

    # Re-encode video
    reenc = os.path.join(tmp, "v.mp4")
    cmd = ["ffmpeg","-y","-i",video_path] + (["-vf",scale] if scale else []) + [
        "-c:v","libx264","-preset","fast","-crf","23",
        "-c:a","aac","-b:a","128k","-ar","44100", reenc]
    r = subprocess.run(cmd, capture_output=True)
    if r.returncode != 0:
        return False, f"Re-encode failed: {r.stderr.decode()[-300:]}"

    if audio_path:
        # Re-encode audio
        r = subprocess.run(["ffmpeg","-y","-i",audio_path,"-vn",
                            "-c:a","aac","-b:a","192k","-ar","44100","-ac","2",merged_audio],
                           capture_output=True)
        if r.returncode != 0:
            return False, f"Audio encode failed: {r.stderr.decode()[-300:]}"

        audio_dur = get_duration(merged_audio)
        video_dur = get_duration(reenc)

        # Adjust video length to match audio duration
        adj = os.path.join(tmp, "adj.mp4")
        if audio_dur and video_dur:
            if audio_dur > video_dur:
                subprocess.run(["ffmpeg","-y","-stream_loop","-1","-i",reenc,
                                "-t",str(audio_dur),"-c:v","libx264","-preset","fast","-crf","23","-an",adj],
                               capture_output=True)
            else:
                subprocess.run(["ffmpeg","-y","-i",reenc,
                                "-t",str(audio_dur),"-c:v","libx264","-preset","fast","-crf","23","-an",adj],
                               capture_output=True)
            use_video = adj if os.path.exists(adj) else reenc
        else:
            use_video = reenc

        # Combine
        if audio_mode == "replace":
            cmd = ["ffmpeg","-y","-i",use_video,"-i",merged_audio,
                   "-c:v","copy","-c:a","aac","-b:a","192k",
                   "-map","0:v:0","-map","1:a:0","-shortest",output_path]
        else:
            cmd = ["ffmpeg","-y","-i",use_video,"-i",merged_audio,
                   "-filter_complex","[0:a][1:a]amix=inputs=2:duration=shortest[a]",
                   "-map","0:v","-map","[a]","-c:v","copy","-c:a","aac","-b:a","192k",
                   "-shortest",output_path]
        r = subprocess.run(cmd, capture_output=True)
        if r.returncode != 0:
            return False, f"Merge failed: {r.stderr.decode()[-300:]}"
    else:
        import shutil
        shutil.copy(reenc, output_path)

    return True, "OK"

# ── Session state ─────────────────────────────────────────
for k,v in {
    "dbx_token": None,
    "dbx_account": None,
    "dbx_app_key": "",
    "dbx_app_secret": "",
    "dbx_refresh_token": "",
    "selected_videos": [],
    "selected_audios": [],
}.items():
    if k not in st.session_state: st.session_state[k]=v


# ── Sidebar ───────────────────────────────────────────────
with st.sidebar:
    st.markdown('<p style="font-family:Syne;font-size:1.4rem;font-weight:800;background:linear-gradient(135deg,#f5c842,#ff6b35);-webkit-background-clip:text;-webkit-text-fill-color:transparent;">🎬 Video Merger Pro</p>', unsafe_allow_html=True)
    st.markdown("---")
    st.markdown("### ☁️ Dropbox")
    st.markdown("""<div style="background:#1a1a20;border:1px solid #2a2a35;border-radius:8px;padding:0.75rem;font-size:0.78rem;color:#aaa;margin-bottom:0.8rem;">
Dùng <b>Refresh Token</b> — không bao giờ hết hạn.<br>
Lấy tại: <a href="https://www.dropbox.com/developers/apps" target="_blank" style="color:#60a5fa;">dropbox.com/developers/apps</a>
</div>""", unsafe_allow_html=True)

    app_key    = st.text_input("App Key",    placeholder="xxxxxxxxxxxxxxxxxxxx")
    app_secret = st.text_input("App Secret", placeholder="xxxxxxxxxxxxxxxxxxxx", type="password")
    refresh_tk = st.text_input("Refresh Token", placeholder="xxxxxxxxxxxxxxxxxxx...", type="password")

    if st.button("🔐 Connect Dropbox", use_container_width=True):
        if not (app_key.strip() and app_secret.strip() and refresh_tk.strip()):
            st.error("❌ Nhập đủ App Key, App Secret và Refresh Token.")
        else:
            with st.spinner("Đang xác thực..."):
                access_token, err = dbx_get_access_token(app_key.strip(), app_secret.strip(), refresh_tk.strip())
            if access_token:
                info = dbx_verify(access_token)
                if info:
                    st.session_state.dbx_token         = access_token
                    st.session_state.dbx_app_key       = app_key.strip()
                    st.session_state.dbx_app_secret    = app_secret.strip()
                    st.session_state.dbx_refresh_token = refresh_tk.strip()
                    st.session_state.dbx_account       = info
                    name  = info.get("name", {}).get("display_name", "")
                    email = info.get("email", "")
                    st.success(f"✅ {name}  ({email})")
                else:
                    st.error("❌ Không xác minh được tài khoản.")
            else:
                st.error(f"❌ Lỗi: {err}")
                st.session_state.dbx_token = None

    if st.session_state.dbx_token:
        st.markdown('<p style="color:#4ade80;font-size:0.85rem;">🟢 Đã kết nối Dropbox</p>', unsafe_allow_html=True)

    st.markdown("---")
    st.markdown("### ⚙️ Output Settings")
    output_filename=st.text_input("Tên file output",value="final_video.mp4")
    dropbox_folder=st.text_input("Thư mục Dropbox",value="/",help="VD: / hoặc /Videos hoặc /Projects/2024")
    resolution=st.selectbox("Resolution",["original","youtube","tiktok"],
        format_func=lambda x:{"original":"📐 Giữ nguyên","youtube":"▶️ YouTube 1280×720","tiktok":"📱 TikTok 576×1024"}[x])
    audio_mode=st.selectbox("Audio mode",["replace","mix"],
        format_func=lambda x:{"replace":"🔇 Thay audio gốc","mix":"🎛️ Hoà trộn audio"}[x])
    st.markdown("---")
    st.caption("FFmpeg + Dropbox API")


# ── Main ──────────────────────────────────────────────────
st.markdown('<h1 class="main-title">🎬 Video Merger Pro</h1>',unsafe_allow_html=True)
st.markdown('<p class="subtitle">Ghép nhiều video + audio → 1 video hoàn chỉnh → tự động upload Dropbox</p>',unsafe_allow_html=True)

with st.spinner("Kiểm tra FFmpeg..."):
    ffok,_=ensure_ffmpeg()
if not ffok:
    st.markdown('<div class="error-box">⚠️ FFmpeg chưa cài. Chạy: sudo apt-get install ffmpeg</div>',unsafe_allow_html=True)
    st.stop()

tab1,tab2,tab3,tab4,tab5,tab6,tab7=st.tabs(["🔗 Nhập URL","📋 Danh sách","🚀 Xuất video","✨ Edit video","🔥 Hiệu ứng lửa","📦 Bulk Video","🎚️ Encode"])

# ── Tab 1: URL input ──────────────────────────────────────
with tab1:
    st.markdown("### 🔗 Nhập URL video & audio")
    st.markdown("""<div class="info-box">
Dán tất cả URL vào ô bên dưới, phân cách bằng <b>dấu phẩy</b> hoặc <b>xuống dòng</b>.<br>
Tool tự động phân loại theo đuôi file:<br>
<code>.mp4 .mov .avi .mkv .webm</code> → 🎥 <b>Video</b> &nbsp;|&nbsp;
<code>.mp3 .wav .aac .m4a .ogg .flac</code> → 🎵 <b>Audio</b>
</div>""",unsafe_allow_html=True)

    url_input=st.text_area("Dán URL vào đây",height=220,
        placeholder="https://.../video1.mp4\nhttps://.../video2.mp4\nhttps://.../audio1.mp3\n...",
        key="url_input_area")

    VIDEO_EXTS={".mp4",".mov",".avi",".mkv",".webm"}
    AUDIO_EXTS={".mp3",".wav",".aac",".m4a",".ogg",".flac"}

    if url_input.strip():
        raw=[u.strip() for u in url_input.replace("\n",",").split(",") if u.strip()]
        auto_videos,auto_audios,unknown=[],[],[]
        for u in raw:
            ext=Path(u.split("?")[0]).suffix.lower()
            if ext in VIDEO_EXTS: auto_videos.append(u)
            elif ext in AUDIO_EXTS: auto_audios.append(u)
            else: unknown.append(u)

        c1,c2=st.columns(2)
        with c1:
            st.markdown(f"**🎥 Video phát hiện: {len(auto_videos)}**")
            for i,u in enumerate(auto_videos,1): st.caption(f"{i}. {u.split('/')[-1].split('?')[0]}")
        with c2:
            st.markdown(f"**🎵 Audio phát hiện: {len(auto_audios)}**")
            for i,u in enumerate(auto_audios,1): st.caption(f"{i}. {u.split('/')[-1].split('?')[0]}")
        if unknown:
            st.markdown(f'<div class="warn-box">⚠️ Không nhận dạng được {len(unknown)} URL: {", ".join(u.split("/")[-1] for u in unknown)}</div>',unsafe_allow_html=True)

        if st.button("✅ Xác nhận danh sách",use_container_width=True):
            st.session_state.selected_videos=[{"name":u.split("/")[-1].split("?")[0],"direct_url":u} for u in auto_videos]
            st.session_state.selected_audios=[{"name":u.split("/")[-1].split("?")[0],"direct_url":u} for u in auto_audios]
            st.success(f"✅ Đã xác nhận {len(auto_videos)} video, {len(auto_audios)} audio → chuyển sang tab Xuất video.")

# ── Tab 2: Preview ────────────────────────────────────────
with tab2:
    st.markdown("### 📋 Danh sách đã chọn")
    c1,c2=st.columns(2)
    with c1:
        st.markdown("**🎥 Videos (theo thứ tự ghép):**")
        if st.session_state.selected_videos:
            for i,v in enumerate(st.session_state.selected_videos,1): st.markdown(f"`{i}.` {v['name']}")
        else: st.caption("Chưa có — nhập URL ở tab đầu.")
    with c2:
        st.markdown("**🎵 Audios (theo thứ tự ghép):**")
        if st.session_state.selected_audios:
            for i,a in enumerate(st.session_state.selected_audios,1): st.markdown(f"`{i}.` {a['name']}")
        else: st.caption("(Không có — giữ audio gốc của video)")

# ── Tab 3: Export + Upload ────────────────────────────────
with tab3:
    st.markdown("### 🚀 Xuất & Upload Dropbox")
    if not st.session_state.selected_videos:
        st.markdown('<div class="warn-box">⚠️ Chưa có video. Nhập URL ở tab đầu tiên.</div>',unsafe_allow_html=True)
    else:
        st.markdown(f"**{len(st.session_state.selected_videos)} video** + **{len(st.session_state.selected_audios)} audio** → `{output_filename}`")
        if not st.session_state.dbx_token:
            st.markdown('<div class="warn-box">⚠️ Chưa kết nối Dropbox — video vẫn tạo được nhưng chỉ tải xuống thủ công.</div>',unsafe_allow_html=True)

        if st.button("🚀 Bắt đầu ghép video",use_container_width=True,type="primary"):
            tmp_dir=tempfile.mkdtemp()
            local_videos,local_audios=[],[]

            st.markdown("#### ⬇️ Tải video...")
            pv=st.progress(0)
            for i,vf in enumerate(st.session_state.selected_videos):
                dest=os.path.join(tmp_dir,f"video_{i}{Path(vf['name']).suffix or '.mp4'}")
                if download_file(vf["direct_url"],dest): local_videos.append(dest)
                pv.progress((i+1)/len(st.session_state.selected_videos))

            if st.session_state.selected_audios:
                st.markdown("#### ⬇️ Tải audio...")
                pa=st.progress(0)
                for i,af in enumerate(st.session_state.selected_audios):
                    dest=os.path.join(tmp_dir,f"audio_{i}{Path(af['name']).suffix or '.mp3'}")
                    if download_file(af["direct_url"],dest): local_audios.append(dest)
                    pa.progress((i+1)/len(st.session_state.selected_audios))

            if not local_videos:
                st.markdown('<div class="error-box">❌ Không tải được video nào. Kiểm tra URL.</div>',unsafe_allow_html=True)
            else:
                output_path=os.path.join(tmp_dir,output_filename)
                ok,msg=merge_videos_and_audio(local_videos,local_audios,output_path,resolution=resolution,audio_mode=audio_mode)

                if ok:
                    st.markdown('<div class="success-box">🎉 Ghép video hoàn tất!</div>',unsafe_allow_html=True)

                    if st.session_state.dbx_token:
                        folder=dropbox_folder.strip() or "/"
                        if not folder.startswith("/"): folder="/"+folder
                        api_folder="" if folder=="/" else folder
                        # Auto-refresh access token before upload
                        if st.session_state.dbx_refresh_token:
                            new_tok,_=dbx_get_access_token(
                                st.session_state.dbx_app_key,
                                st.session_state.dbx_app_secret,
                                st.session_state.dbx_refresh_token,
                            )
                            if new_tok:
                                st.session_state.dbx_token=new_tok
                        with st.spinner("☁️ Đang upload lên Dropbox..."):
                            succ,final_name,umsg,shared_url=dbx_upload(st.session_state.dbx_token,output_path,api_folder,output_filename)
                        if succ:
                            renamed=""
                            if final_name!=output_filename:
                                renamed=f"<br>⚠️ Đã đổi tên: <code>{output_filename}</code> → <code>{final_name}</code> (tránh trùng)"
                            link_html=f'<br>🔗 <a href="{shared_url}" target="_blank" style="color:#60a5fa;">Link tải trực tiếp</a>' if shared_url else ""
                            st.markdown(f'<div class="success-box">☁️ <b>Upload Dropbox thành công!</b><br>File: <code>{final_name}</code><br>Thư mục: <code>{folder}</code>{renamed}{link_html}</div>',unsafe_allow_html=True)
                        else:
                            st.markdown(f'<div class="error-box">❌ Upload thất bại: {umsg}</div>',unsafe_allow_html=True)
                    else:
                        st.info("Dropbox chưa kết nối — tải xuống thủ công bên dưới.")

                    with open(output_path,"rb") as f:
                        st.download_button("⬇️ Tải xuống video hoàn chỉnh",data=f,file_name=output_filename,mime="video/mp4",use_container_width=True)
                    st.markdown("#### 👀 Xem trước")
                    st.video(output_path)
                else:
                    st.markdown(f'<div class="error-box">❌ {msg}</div>',unsafe_allow_html=True)



# ── Tab 4: Edit video (Snow + Zoom) ──────────────────────
with tab4:
    st.markdown("### ✨ Edit Video — Tuyết rơi + Zoom In/Out")

    EDIT_VIDEO_EXTS = {".mp4", ".mov", ".avi", ".mkv", ".webm"}
    EDIT_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif", ".tiff"}

    # ── Input method: Upload or URL ───────────────────────
    input_method = st.radio(
        "Nguồn file", ["📁 Upload trực tiếp", "🔗 Dán URL"],
        horizontal=True, key="edit_input_method"
    )

    local_media_edit = []   # list of local file paths, in order
    local_audio_edit = None

    if input_method == "📁 Upload trực tiếp":
        st.markdown("""<div class="info-box">
Tải ảnh hoặc video lên trực tiếp — không cần URL, không lo bị chặn.<br>
Thứ tự file = thứ tự xuất hiện trong video.<br>
Hỗ trợ: <code>jpg png webp mp4 mov avi</code>
</div>""", unsafe_allow_html=True)

        uploaded_media = st.file_uploader(
            "Chọn ảnh / video (có thể chọn nhiều file)",
            type=["jpg","jpeg","png","webp","bmp","gif","tiff","mp4","mov","avi","mkv","webm"],
            accept_multiple_files=True,
            key="edit_upload_media"
        )
        uploaded_audio = st.file_uploader(
            "Audio nền (tuỳ chọn)",
            type=["mp3","wav","aac","m4a","ogg","flac"],
            accept_multiple_files=False,
            key="edit_upload_audio"
        )

        if uploaded_media:
            st.markdown(f"**{len(uploaded_media)} file đã chọn:**")
            for i, f in enumerate(uploaded_media, 1):
                st.caption(f"{i}. {f.name}  ({f.size//1024} KB)")

            # Save uploaded files to temp dir immediately
            if "edit_saved_paths" not in st.session_state:
                st.session_state.edit_saved_paths = []
            if "edit_audio_path" not in st.session_state:
                st.session_state.edit_audio_path = None

            if st.button("💾 Lưu file đã upload", use_container_width=True, key="btn_save_upload"):
                save_tmp = tempfile.mkdtemp()
                saved = []
                for i, uf in enumerate(uploaded_media):
                    ext = Path(uf.name).suffix.lower() or ".jpg"
                    dest = os.path.join(save_tmp, f"media_{i:03d}{ext}")
                    with open(dest, "wb") as out_f:
                        out_f.write(uf.read())
                    saved.append(dest)
                st.session_state.edit_saved_paths = saved

                if uploaded_audio:
                    ext_a = Path(uploaded_audio.name).suffix.lower() or ".mp3"
                    dest_a = os.path.join(save_tmp, f"audio{ext_a}")
                    with open(dest_a, "wb") as out_f:
                        out_f.write(uploaded_audio.read())
                    st.session_state.edit_audio_path = dest_a
                else:
                    st.session_state.edit_audio_path = None

                st.success(f"✅ Đã lưu {len(saved)} file. Bấm 'Tạo Edit Video' bên dưới.")

        # Use saved paths
        if st.session_state.get("edit_saved_paths"):
            local_media_edit = [p for p in st.session_state.edit_saved_paths if os.path.exists(p)]
            local_audio_edit = st.session_state.get("edit_audio_path")
            if local_media_edit:
                st.markdown(f'<div class="success-box">✅ Sẵn sàng: {len(local_media_edit)} file media</div>',
                            unsafe_allow_html=True)

    else:  # URL mode
        st.markdown("""<div class="info-box">
Dán URL ảnh/video (Cloudinary, Google Drive direct link, v.v.).<br>
MediaFire thường bị chặn — nên dùng Upload trực tiếp thay thế.
</div>""", unsafe_allow_html=True)

        edit_urls = st.text_area("Dán URL ảnh/video", height=160,
            placeholder="https://res.cloudinary.com/.../anh1.jpg\nhttps://res.cloudinary.com/.../clip.mp4",
            key="edit_url_input")
        edit_audio_url = st.text_input("URL audio nền (tuỳ chọn)",
            placeholder="https://.../nhac_nen.mp3", key="edit_audio_url")

        if edit_urls.strip():
            raw_edit = [u.strip() for u in edit_urls.replace("\n",",").split(",") if u.strip()]
            edit_imgs = [u for u in raw_edit if Path(u.split("?")[0]).suffix.lower() in EDIT_IMAGE_EXTS]
            edit_vids = [u for u in raw_edit if Path(u.split("?")[0]).suffix.lower() in EDIT_VIDEO_EXTS]
            c1e, c2e = st.columns(2)
            with c1e:
                st.markdown(f"**🖼️ Ảnh: {len(edit_imgs)}**")
                for i, u in enumerate(edit_imgs, 1): st.caption(f"{i}. {u.split('/')[-1].split('?')[0]}")
            with c2e:
                st.markdown(f"**🎥 Video: {len(edit_vids)}**")
                for i, u in enumerate(edit_vids, 1): st.caption(f"{i}. {u.split('/')[-1].split('?')[0]}")

            if st.button("⬇️ Tải file từ URL", use_container_width=True, key="btn_dl_edit"):
                dl_tmp = tempfile.mkdtemp()
                saved_url = []
                prog_dl = st.progress(0)
                for i, url in enumerate(raw_edit):
                    ext = Path(url.split("?")[0]).suffix.lower() or ".jpg"
                    dest = os.path.join(dl_tmp, f"media_{i:03d}{ext}")
                    if download_file(url, dest):
                        saved_url.append(dest)
                    prog_dl.progress((i+1)/len(raw_edit))

                st.session_state.edit_saved_paths = saved_url
                st.session_state.edit_audio_path = None

                if edit_audio_url.strip():
                    ext_a = Path(edit_audio_url.strip().split("?")[0]).suffix.lower() or ".mp3"
                    dest_a = os.path.join(dl_tmp, f"audio{ext_a}")
                    if download_file(edit_audio_url.strip(), dest_a):
                        st.session_state.edit_audio_path = dest_a

                if saved_url:
                    st.success(f"✅ Tải thành công {len(saved_url)}/{len(raw_edit)} file.")
                else:
                    st.error("❌ Không tải được file nào.")

        if st.session_state.get("edit_saved_paths"):
            local_media_edit = [p for p in st.session_state.edit_saved_paths if os.path.exists(p)]
            local_audio_edit = st.session_state.get("edit_audio_path")

    # ── Effect settings ───────────────────────────────────
    st.markdown("---")
    st.markdown("**⚙️ Cài đặt hiệu ứng**")
    col_e1, col_e2, col_e3 = st.columns(3)
    with col_e1: img_duration = st.slider("Thời lượng mỗi ảnh (giây)", 2.0, 10.0, 5.0, 0.5, key="sl_dur")
    with col_e2: zoom_strength = st.slider("Mức zoom (%)", 5, 30, 15, 1, key="sl_zoom")
    with col_e3: snow_amount = st.slider("Số bông tuyết", 20, 120, 60, 10, key="sl_snow")
    edit_output_name = st.text_input("Tên file output", value="edit_snow_zoom.mp4", key="edit_out_name")

    # ── Process button ────────────────────────────────────
    if not local_media_edit:
        st.markdown('<div class="warn-box">⚠️ Chưa có file nào — upload hoặc tải từ URL trước.</div>',
                    unsafe_allow_html=True)
    else:
        if not st.session_state.dbx_token:
            st.markdown('<div class="warn-box">⚠️ Chưa kết nối Dropbox — chỉ tải xuống thủ công.</div>',
                        unsafe_allow_html=True)

        if st.button("✨ Tạo Edit Video", use_container_width=True, type="primary", key="btn_edit"):
            out_tmp = tempfile.mkdtemp()
            out_edit = os.path.join(out_tmp, edit_output_name)

            ok_e, msg_e = make_snow_zoom_video(
                media_paths=local_media_edit,
                output_path=out_edit,
                fps=30,
                duration_per_image=img_duration,
                zoom_max=1 + zoom_strength / 100,
                snow_count=snow_amount,
                audio_path=local_audio_edit,
            )

            if ok_e:
                st.markdown('<div class="success-box">🎉 Edit video hoàn tất!</div>', unsafe_allow_html=True)

                if st.session_state.dbx_token:
                    folder = dropbox_folder.strip() or "/"
                    if not folder.startswith("/"): folder = "/" + folder
                    api_folder = "" if folder == "/" else folder
                    if st.session_state.dbx_refresh_token:
                        new_tok, _ = dbx_get_access_token(
                            st.session_state.dbx_app_key,
                            st.session_state.dbx_app_secret,
                            st.session_state.dbx_refresh_token)
                        if new_tok: st.session_state.dbx_token = new_tok
                    with st.spinner("☁️ Upload Dropbox..."):
                        succ_e, fname_e, umsg_e, surl_e = dbx_upload(
                            st.session_state.dbx_token, out_edit, api_folder, edit_output_name)
                    if succ_e:
                        link_e = f'<br>🔗 <a href="{surl_e}" target="_blank" style="color:#60a5fa;">Link tải</a>' if surl_e else ""
                        st.markdown(f'<div class="success-box">☁️ Upload OK! File: <code>{fname_e}</code>{link_e}</div>',
                                    unsafe_allow_html=True)
                    else:
                        st.markdown(f'<div class="error-box">❌ Upload thất bại: {umsg_e}</div>',
                                    unsafe_allow_html=True)

                with open(out_edit, "rb") as fe:
                    st.download_button("⬇️ Tải xuống edit video",
                        data=fe, file_name=edit_output_name,
                        mime="video/mp4", use_container_width=True)
                st.markdown("#### 👀 Xem trước")
                st.video(out_edit)
            else:
                st.markdown(f'<div class="error-box">❌ {msg_e}</div>', unsafe_allow_html=True)


# ── Tab 5: Fire Particles effect ─────────────────────────
with tab5:
    st.markdown("### 🔥 Hiệu ứng Lửa — Tàn lửa bay lên")
    st.markdown("""<div class="info-box">
Thêm hiệu ứng <b>đốm lửa nhỏ màu vàng/cam</b> bay từ dưới lên — giống ảnh mẫu.<br>
Mỗi đốm có glow sáng, fade dần khi bay lên, chuyển động tự nhiên.<br>
Hỗ trợ: ảnh <code>jpg png webp</code> và video <code>mp4 mov</code>
</div>""", unsafe_allow_html=True)

    FIRE_VID_EXTS = {".mp4",".mov",".avi",".mkv",".webm"}
    FIRE_IMG_EXTS = {".jpg",".jpeg",".png",".webp",".bmp",".gif",".tiff"}

    fire_input = st.radio("Nguồn file", ["📁 Upload trực tiếp","🔗 Dán URL"],
                           horizontal=True, key="fire_input_method")

    local_fire_media = []
    local_fire_audio = None

    if fire_input == "📁 Upload trực tiếp":
        up_fire = st.file_uploader(
            "Chọn ảnh / video",
            type=["jpg","jpeg","png","webp","bmp","mp4","mov","avi","mkv","webm"],
            accept_multiple_files=True, key="fire_upload_media")
        up_fire_audio = st.file_uploader(
            "Audio nền (tuỳ chọn)", type=["mp3","wav","aac","m4a","ogg"],
            accept_multiple_files=False, key="fire_upload_audio")

        if up_fire:
            st.markdown(f"**{len(up_fire)} file đã chọn:**")
            for i,f in enumerate(up_fire,1): st.caption(f"{i}. {f.name}  ({f.size//1024} KB)")

            if st.button("💾 Lưu file", use_container_width=True, key="btn_save_fire"):
                stmp = tempfile.mkdtemp()
                saved = []
                for i,uf in enumerate(up_fire):
                    ext = Path(uf.name).suffix.lower() or ".jpg"
                    dest = os.path.join(stmp, f"fire_{i:03d}{ext}")
                    with open(dest,"wb") as out_f: out_f.write(uf.read())
                    saved.append(dest)
                st.session_state.fire_saved_paths = saved

                if up_fire_audio:
                    ext_a = Path(up_fire_audio.name).suffix.lower() or ".mp3"
                    dest_a = os.path.join(stmp, f"fire_audio{ext_a}")
                    with open(dest_a,"wb") as out_f: out_f.write(up_fire_audio.read())
                    st.session_state.fire_audio_path = dest_a
                else:
                    st.session_state.fire_audio_path = None
                st.success(f"✅ Đã lưu {len(saved)} file!")

        if st.session_state.get("fire_saved_paths"):
            local_fire_media = [p for p in st.session_state.fire_saved_paths if os.path.exists(p)]
            local_fire_audio = st.session_state.get("fire_audio_path")
            if local_fire_media:
                st.markdown(f'<div class="success-box">✅ Sẵn sàng: {len(local_fire_media)} file</div>',
                            unsafe_allow_html=True)
    else:
        fire_urls = st.text_area("Dán URL ảnh/video", height=140,
            placeholder="https://res.cloudinary.com/.../anh.jpg\nhttps://.../clip.mp4",
            key="fire_url_input")
        fire_audio_url = st.text_input("URL audio nền (tuỳ chọn)", key="fire_audio_url_input")

        if fire_urls.strip():
            raw_fire = [u.strip() for u in fire_urls.replace("\n",",").split(",") if u.strip()]
            st.markdown(f"**{len(raw_fire)} URL**")
            for i,u in enumerate(raw_fire,1): st.caption(f"{i}. {u.split('/')[-1].split('?')[0]}")

            if st.button("⬇️ Tải file từ URL", use_container_width=True, key="btn_dl_fire"):
                dl_tmp = tempfile.mkdtemp()
                saved_f = []
                pf = st.progress(0)
                for i,url in enumerate(raw_fire):
                    ext = Path(url.split("?")[0]).suffix.lower() or ".jpg"
                    dest = os.path.join(dl_tmp, f"fire_{i:03d}{ext}")
                    if download_file(url, dest): saved_f.append(dest)
                    pf.progress((i+1)/len(raw_fire))
                st.session_state.fire_saved_paths = saved_f
                st.session_state.fire_audio_path = None
                if fire_audio_url.strip():
                    ext_a = Path(fire_audio_url.strip().split("?")[0]).suffix.lower() or ".mp3"
                    dest_a = os.path.join(dl_tmp, f"fire_audio{ext_a}")
                    if download_file(fire_audio_url.strip(), dest_a):
                        st.session_state.fire_audio_path = dest_a
                if saved_f:
                    st.success(f"✅ Tải được {len(saved_f)}/{len(raw_fire)} file.")
                else:
                    st.error("❌ Không tải được file nào.")

        if st.session_state.get("fire_saved_paths"):
            local_fire_media = [p for p in st.session_state.fire_saved_paths if os.path.exists(p)]
            local_fire_audio = st.session_state.get("fire_audio_path")

    # ── Settings ──────────────────────────────────────────
    st.markdown("---")
    st.markdown("**✨ Chọn hiệu ứng**")

    EFFECT_OPTIONS = {
        "🔥 Lửa (Fire Embers)":          "fire",
        "✨ Vàng bay (Golden Particles)": "golden",
        "☁️ Ánh sáng thiên đường (Heaven Light)": "heaven",
        "🌟 Bụi thánh (Holy Dust)":      "holy_dust",
        "🌿 Đom đóm (Fireflies)":         "fireflies",
    }
    effect_label = st.selectbox("Hiệu ứng", list(EFFECT_OPTIONS.keys()), key="fire_effect_select")
    chosen_effect = EFFECT_OPTIONS[effect_label]

    EFFECT_DESCRIPTIONS = {
        "fire":      "Đốm lửa vàng/cam bay từ dưới lên, glow sáng, fade dần khi lên cao.",
        "golden":    "Hạt vàng lấp lánh trôi nổi khắp màn hình, nhấp nháy nhẹ nhàng.",
        "heaven":    "Ánh sáng trắng/xanh nhạt rơi từ trên xuống như ánh sáng thiên đường.",
        "holy_dust": "Bụi sáng nhỏ li ti trôi nổi chậm chạp, lung linh trong không trung.",
        "fireflies": "Đom đóm xanh lá nhấp nháy chậm, bay lờ lững như mùa hè.",
    }
    st.markdown(f'<div class="info-box">💡 {EFFECT_DESCRIPTIONS[chosen_effect]}</div>',
                unsafe_allow_html=True)

    st.markdown("**⚙️ Cài đặt**")
    fc1,fc2,fc3 = st.columns(3)
    with fc1: fire_img_dur = st.slider("Thời lượng mỗi ảnh (s)", 2.0, 10.0, 5.0, 0.5, key="fire_dur")
    with fc2: fire_particles = st.slider("Số hạt", 20, 150, 60, 10, key="fire_count")
    with fc3: fire_zoom = st.slider("Mức zoom (%)", 0, 20, 8, 1, key="fire_zoom")
    fire_out_name = st.text_input("Tên file output", value="effect_video.mp4", key="fire_out_name")

    # ── Process ───────────────────────────────────────────
    if not local_fire_media:
        st.markdown('<div class="warn-box">⚠️ Chưa có file — upload hoặc dán URL trước.</div>',
                    unsafe_allow_html=True)
    else:
        if not st.session_state.dbx_token:
            st.markdown('<div class="warn-box">⚠️ Chưa kết nối Dropbox — chỉ tải xuống thủ công.</div>',
                        unsafe_allow_html=True)

        btn_labels = {
            "fire": "🔥 Tạo video lửa",
            "golden": "✨ Tạo video vàng",
            "heaven": "☁️ Tạo video thiên đường",
            "holy_dust": "🌟 Tạo video bụi thánh",
            "fireflies": "🌿 Tạo video đom đóm",
        }
        if st.button(btn_labels[chosen_effect], use_container_width=True, type="primary", key="btn_fire"):
            fire_tmp = tempfile.mkdtemp()
            fire_out = os.path.join(fire_tmp, fire_out_name)

            ok_f, msg_f = make_fire_particles_video(
                media_paths=local_fire_media,
                output_path=fire_out,
                fps=30,
                duration_per_image=fire_img_dur,
                particle_count=fire_particles,
                zoom_max=1 + fire_zoom/100,
                effect_type=chosen_effect,
                audio_path=local_fire_audio,
            )

            if ok_f:
                st.markdown(f'<div class="success-box">🎉 Video hiệu ứng hoàn tất!</div>', unsafe_allow_html=True)

                if st.session_state.dbx_token:
                    folder = dropbox_folder.strip() or "/"
                    if not folder.startswith("/"): folder = "/" + folder
                    api_folder = "" if folder == "/" else folder
                    if st.session_state.dbx_refresh_token:
                        new_tok,_ = dbx_get_access_token(
                            st.session_state.dbx_app_key,
                            st.session_state.dbx_app_secret,
                            st.session_state.dbx_refresh_token)
                        if new_tok: st.session_state.dbx_token = new_tok
                    with st.spinner("☁️ Upload Dropbox..."):
                        succ_f, fname_f, umsg_f, surl_f = dbx_upload(
                            st.session_state.dbx_token, fire_out, api_folder, fire_out_name)
                    if succ_f:
                        link_f = f'<br>🔗 <a href="{surl_f}" target="_blank" style="color:#60a5fa;">Link tải</a>' if surl_f else ""
                        st.markdown(f'<div class="success-box">☁️ Upload OK! <code>{fname_f}</code>{link_f}</div>',
                                    unsafe_allow_html=True)
                    else:
                        st.markdown(f'<div class="error-box">❌ Upload thất bại: {umsg_f}</div>',
                                    unsafe_allow_html=True)

                with open(fire_out,"rb") as fe:
                    st.download_button("⬇️ Tải xuống fire video",
                        data=fe, file_name=fire_out_name,
                        mime="video/mp4", use_container_width=True)
                st.markdown("#### 👀 Xem trước")
                st.video(fire_out)
            else:
                st.markdown(f'<div class="error-box">❌ {msg_f}</div>', unsafe_allow_html=True)


# ── Tab 6: Bulk Video ─────────────────────────────────────
with tab6:
    st.markdown("### 📦 Bulk Video — Nhiều cặp → Nhiều video riêng")
    st.markdown("""<div class="info-box">
Mỗi hàng = 1 cặp <b>Video URL + Audio URL</b> → tạo ra 1 video riêng biệt.<br>
Tất cả video sau khi tạo xong sẽ tự động <b>upload lên Dropbox</b>.
</div>""", unsafe_allow_html=True)

    # ── Input mode ────────────────────────────────────────
    bulk_input_mode = st.radio(
        "Cách nhập", ["📋 Nhập từng cặp URL", "📁 Upload file"],
        horizontal=True, key="bulk_input_mode"
    )

    # Manage pairs in session state
    if "bulk_pairs" not in st.session_state:
        st.session_state.bulk_pairs = []

    if bulk_input_mode == "📋 Nhập từng cặp URL":
        st.markdown("**Nhập danh sách cặp — mỗi dòng: `video_url , audio_url`**")
        st.markdown("""<div class="info-box" style="font-size:0.82rem;">
Định dạng mỗi dòng:<br>
<code>https://.../video1.mp4 , https://.../audio1.mp3</code><br>
<code>https://.../video2.mp4 , https://.../audio2.mp3</code><br>
Chỉ dùng Cloudinary hoặc CDN trực tiếp (không dùng Dropbox/MediaFire link)
</div>""", unsafe_allow_html=True)

        bulk_text = st.text_area(
            "Danh sách cặp video+audio",
            height=220,
            placeholder="https://.../video1.mp4 , https://.../audio1.mp3\nhttps://.../video2.mp4 , https://.../audio2.mp3",
            key="bulk_text_input"
        )

        if bulk_text.strip():
            pairs_preview = []
            errors = []
            for i, line in enumerate(bulk_text.strip().splitlines()):
                line = line.strip()
                if not line: continue
                if "," not in line:
                    errors.append(f"Dòng {i+1}: thiếu dấu phẩy — `{line[:60]}`")
                    continue
                parts = [p.strip() for p in line.split(",", 1)]
                if len(parts) == 2 and parts[0] and parts[1]:
                    pairs_preview.append({"video": parts[0], "audio": parts[1]})
                else:
                    errors.append(f"Dòng {i+1}: không hợp lệ")

            if errors:
                for e in errors:
                    st.warning(f"⚠️ {e}")

            if pairs_preview:
                st.markdown(f"**✅ Phát hiện {len(pairs_preview)} cặp:**")
                for i, p in enumerate(pairs_preview, 1):
                    c1, c2 = st.columns(2)
                    with c1: st.caption(f"🎥 {i}. {p['video'].split('/')[-1].split('?')[0]}")
                    with c2: st.caption(f"🎵 {p['audio'].split('/')[-1].split('?')[0]}")

                if st.button("✅ Xác nhận danh sách", use_container_width=True, key="bulk_confirm_url"):
                    st.session_state.bulk_pairs = pairs_preview
                    st.success(f"✅ Đã lưu {len(pairs_preview)} cặp. Cài đặt và bấm Tạo bên dưới.")

    else:  # Upload mode
        st.markdown("""<div class="info-box">
Upload nhiều file video + audio. Tool sẽ ghép theo thứ tự:<br>
Video 1 + Audio 1 → Output 1 &nbsp;|&nbsp; Video 2 + Audio 2 → Output 2 &nbsp;|&nbsp; ...
</div>""", unsafe_allow_html=True)

        col_bv, col_ba = st.columns(2)
        with col_bv:
            bulk_videos_up = st.file_uploader(
                "📹 Upload VIDEO files (theo thứ tự)",
                type=["mp4","mov","avi","mkv","webm"],
                accept_multiple_files=True, key="bulk_up_videos"
            )
        with col_ba:
            bulk_audios_up = st.file_uploader(
                "🎵 Upload AUDIO files (theo thứ tự)",
                type=["mp3","wav","aac","m4a","ogg","flac"],
                accept_multiple_files=True, key="bulk_up_audios"
            )

        if bulk_videos_up and bulk_audios_up:
            n = min(len(bulk_videos_up), len(bulk_audios_up))
            if len(bulk_videos_up) != len(bulk_audios_up):
                st.warning(f"⚠️ Số video ({len(bulk_videos_up)}) ≠ số audio ({len(bulk_audios_up)}) — chỉ ghép {n} cặp đầu.")
            st.markdown(f"**{n} cặp sẽ ghép:**")
            for i in range(n):
                c1, c2 = st.columns(2)
                with c1: st.caption(f"🎥 {i+1}. {bulk_videos_up[i].name}")
                with c2: st.caption(f"🎵 {i+1}. {bulk_audios_up[i].name}")

            if st.button("💾 Lưu file upload", use_container_width=True, key="bulk_save_upload"):
                stmp = tempfile.mkdtemp()
                pairs = []
                for i in range(n):
                    vext = Path(bulk_videos_up[i].name).suffix.lower() or ".mp4"
                    aext = Path(bulk_audios_up[i].name).suffix.lower() or ".mp3"
                    vpath = os.path.join(stmp, f"bv_{i:03d}{vext}")
                    apath = os.path.join(stmp, f"ba_{i:03d}{aext}")
                    with open(vpath,"wb") as f: f.write(bulk_videos_up[i].read())
                    with open(apath,"wb") as f: f.write(bulk_audios_up[i].read())
                    pairs.append({"video": vpath, "audio": apath, "_local": True,
                                  "vname": bulk_videos_up[i].name})
                st.session_state.bulk_pairs = pairs
                st.success(f"✅ Đã lưu {n} cặp!")

    # ── Settings ──────────────────────────────────────────
    st.markdown("---")
    st.markdown("**⚙️ Cài đặt output**")
    bc1, bc2, bc3 = st.columns(3)
    with bc1:
        bulk_resolution = st.selectbox("Resolution", ["original","youtube","tiktok"],
            format_func=lambda x: {"original":"📐 Giữ nguyên","youtube":"▶️ YouTube 1280×720","tiktok":"📱 TikTok 576×1024"}[x],
            key="bulk_res")
    with bc2:
        bulk_audio_mode = st.selectbox("Audio mode", ["replace","mix"],
            format_func=lambda x: {"replace":"🔇 Thay audio gốc","mix":"🎛️ Hoà trộn"}[x],
            key="bulk_audio_mode")
    with bc3:
        bulk_prefix = st.text_input("Prefix tên file", value="bulk_video", key="bulk_prefix",
                                     help="Output: bulk_video_1.mp4, bulk_video_2.mp4, ...")
    bulk_dropbox_folder = st.text_input("Thư mục Dropbox", value="/Bulk",
                                         key="bulk_dbx_folder",
                                         help="Thư mục trên Dropbox để lưu tất cả video")

    # ── Process ───────────────────────────────────────────
    pairs_ready = st.session_state.get("bulk_pairs", [])
    if not pairs_ready:
        st.markdown('<div class="warn-box">⚠️ Chưa có cặp nào — nhập URL hoặc upload file trước.</div>',
                    unsafe_allow_html=True)
    else:
        st.markdown(f'<div class="success-box">✅ Sẵn sàng: <b>{len(pairs_ready)} cặp</b></div>',
                    unsafe_allow_html=True)
        if not st.session_state.get("dbx_token"):
            st.markdown('<div class="warn-box">⚠️ Chưa kết nối Dropbox — kết quả chỉ tải xuống thủ công.</div>',
                        unsafe_allow_html=True)

        if st.button(f"🚀 Tạo {len(pairs_ready)} video", use_container_width=True,
                     type="primary", key="bulk_run"):

            bulk_tmp = tempfile.mkdtemp()
            results = []  # list of (name, path, ok, msg)

            # Progress containers
            overall_prog = st.progress(0, text="Bắt đầu...")
            status_box = st.empty()
            result_placeholder = st.container()

            for i, pair in enumerate(pairs_ready):
                pair_name = f"{bulk_prefix}_{i+1}.mp4"
                out_path = os.path.join(bulk_tmp, pair_name)
                overall_prog.progress(i / len(pairs_ready),
                                      text=f"Đang xử lý {i+1}/{len(pairs_ready)}: {pair_name}")
                status_box.info(f"⚙️ Đang tạo **{pair_name}**...")

                # Get local paths
                if pair.get("_local"):
                    vpath = pair["video"]
                    apath = pair["audio"]
                    dl_ok = True
                else:
                    # Download video
                    vext = Path(pair["video"].split("?")[0]).suffix.lower() or ".mp4"
                    vpath = os.path.join(bulk_tmp, f"dl_v_{i:03d}{vext}")
                    aext = Path(pair["audio"].split("?")[0]).suffix.lower() or ".mp3"
                    apath = os.path.join(bulk_tmp, f"dl_a_{i:03d}{aext}")
                    dl_ok = download_file(pair["video"], vpath) and download_file(pair["audio"], apath)

                if not dl_ok:
                    results.append((pair_name, None, False, "Tải file thất bại"))
                    continue

                # Merge
                ok, msg = bulk_merge_one(
                    vpath, apath, out_path,
                    resolution=bulk_resolution,
                    audio_mode=bulk_audio_mode
                )
                if not ok:
                    results.append((pair_name, None, False, msg))
                    continue

                # Upload to Dropbox
                dbx_ok = False
                dbx_link = None
                if st.session_state.get("dbx_token"):
                    folder = bulk_dropbox_folder.strip() or "/Bulk"
                    if not folder.startswith("/"): folder = "/" + folder
                    api_folder = "" if folder == "/" else folder
                    # Refresh token
                    if st.session_state.get("dbx_refresh_token"):
                        new_tok, _ = dbx_get_access_token(
                            st.session_state.get("dbx_app_key",""),
                            st.session_state.get("dbx_app_secret",""),
                            st.session_state.get("dbx_refresh_token",""),
                        )
                        if new_tok: st.session_state.dbx_token = new_tok
                    succ, fname, umsg, surl = dbx_upload(
                        st.session_state.dbx_token, out_path, api_folder, pair_name)
                    dbx_ok = succ
                    dbx_link = surl

                results.append((pair_name, out_path, True, dbx_link))

            overall_prog.progress(1.0, text=f"Hoàn tất {len(pairs_ready)} video!")
            status_box.empty()

            # ── Summary ───────────────────────────────────
            ok_count  = sum(1 for r in results if r[2])
            fail_count = len(results) - ok_count

            st.markdown(f"""
            <div class="success-box">
            🎉 <b>Bulk xong!</b> &nbsp; ✅ {ok_count} thành công &nbsp; {'❌ ' + str(fail_count) + ' thất bại' if fail_count else ''}
            </div>
            """, unsafe_allow_html=True)

            # Result table
            st.markdown("**📋 Kết quả từng video:**")
            for name, path, ok, extra in results:
                if ok:
                    link_html = f' — <a href="{extra}" target="_blank">🔗 Link Dropbox</a>' if extra else " — (chỉ tải xuống)"
                    st.markdown(f'<div class="success-box" style="padding:0.5rem 1rem;margin-bottom:4px;">✅ <b>{name}</b>{link_html}</div>',
                                unsafe_allow_html=True)
                else:
                    st.markdown(f'<div class="error-box" style="padding:0.5rem 1rem;margin-bottom:4px;">❌ <b>{name}</b> — {extra}</div>',
                                unsafe_allow_html=True)

            # Download buttons for successful files
            ok_files = [(n, p) for n, p, ok, _ in results if ok and p]
            if ok_files:
                st.markdown("**⬇️ Tải xuống:**")
                cols = st.columns(min(3, len(ok_files)))
                for i, (name, path) in enumerate(ok_files):
                    with cols[i % 3]:
                        with open(path, "rb") as f:
                            st.download_button(
                                f"⬇️ {name}", data=f,
                                file_name=name, mime="video/mp4",
                                key=f"bulk_dl_{i}"
                            )



# ── Tab 7: Encode (HandBrake-style) ──────────────────────
with tab7:
    st.markdown("### 🎚️ Encode — YouTube Livestream Optimizer")
    st.markdown("""<div class="info-box">
Encode video về định dạng tối ưu cho <b>YouTube Livestream</b>.<br>
<code>H.264 • AAC 44100Hz • CBR Bitrate • Letterbox Scale • Faststart</code>
</div>""", unsafe_allow_html=True)

    ec1,ec2,ec3,ec4 = st.columns(4)
    with ec1:
        enc_res = st.selectbox("Resolution",["1280x720","1920x1080"],
            format_func=lambda x:"📐 HD 720p" if x=="1280x720" else "📐 FHD 1080p",key="enc_res")
    with ec2:
        enc_br = st.slider("Bitrate (kbps)",1500,6000,3500,250,key="enc_br")
    with ec3:
        enc_fps = st.selectbox("FPS",[30,60],key="enc_fps")
    with ec4:
        enc_abr = st.selectbox("Audio (kbps)",[128,192,256],key="enc_abr")
    enc_dbx_folder = st.text_input("Dropbox folder",value="/Encoded",key="enc_dbx_folder")

    if 2500<=enc_br<=4000: st.caption("🟢 Bitrate tối ưu cho YouTube (2500–4000 kbps)")
    elif enc_br<2500: st.caption("🟡 Bitrate thấp — chất lượng có thể giảm")
    else: st.caption("🔵 Bitrate cao — chất lượng tốt nhất, file lớn hơn")

    st.markdown(f"""<div class="spec-grid">
      <div class="spec-card"><div class="label">Codec</div><div class="value">H.264</div></div>
      <div class="spec-card"><div class="label">Resolution</div><div class="value">{enc_res.replace("x","x")}</div></div>
      <div class="spec-card"><div class="label">Bitrate</div><div class="value">{enc_br}K</div></div>
      <div class="spec-card"><div class="label">FPS</div><div class="value">{enc_fps}</div></div>
      <div class="spec-card"><div class="label">Audio</div><div class="value">AAC {enc_abr}K</div></div>
    </div>""", unsafe_allow_html=True)

    st.markdown("---")
    enc_input = st.radio("Nguon video",["Upload file","Dan URL (.mp4)"],horizontal=True,key="enc_input_mode")
    enc_files_ready = []

    if enc_input == "Upload file":
        up_enc = st.file_uploader("Chon file video",
            type=["mp4","mov","avi","mkv","webm","flv"],
            accept_multiple_files=True,key="enc_upload")
        if up_enc:
            st.markdown(f"**{len(up_enc)} file:**")
            for uf in up_enc: st.caption(f"* {uf.name}  ({uf.size//1024//1024:.1f} MB)")
            if st.button("Luu file",use_container_width=True,key="btn_save_enc"):
                stmp=tempfile.mkdtemp(); saved=[]
                for i,uf in enumerate(up_enc):
                    ext=Path(uf.name).suffix.lower() or ".mp4"
                    dest=os.path.join(stmp,f"src_{i:03d}{ext}")
                    with open(dest,"wb") as fo: fo.write(uf.read())
                    saved.append({"label":uf.name,"path":dest})
                st.session_state["enc_ready"]=saved
                st.success(f"Da luu {len(saved)} file!")
        if st.session_state.get("enc_ready"):
            enc_files_ready=[p for p in st.session_state["enc_ready"] if os.path.exists(p["path"])]
            if enc_files_ready:
                st.markdown(f'<div class="success-box">San sang: <b>{len(enc_files_ready)} video</b></div>',unsafe_allow_html=True)
    else:
        st.markdown('<div class="info-box">Dan link .mp4 (Cloudinary, CDN). Moi dong = 1 video.</div>',unsafe_allow_html=True)
        url_text=st.text_area("URL video",height=150,key="enc_url_input",
            placeholder="https://res.cloudinary.com/.../video1.mp4")
        if url_text.strip():
            raw_urls=[u.strip() for u in url_text.splitlines() if u.strip()]
            for i,u in enumerate(raw_urls,1): st.caption(f"{i}. {u.split('/')[-1].split('?')[0]}")
            if st.button("Tai file ve",use_container_width=True,key="btn_dl_enc"):
                dl_tmp=tempfile.mkdtemp(); downloaded=[]
                prog=st.progress(0)
                for i,url in enumerate(raw_urls):
                    ext=Path(url.split("?")[0]).suffix.lower() or ".mp4"
                    name=url.split("/")[-1].split("?")[0] or f"video_{i+1}.mp4"
                    dest=os.path.join(dl_tmp,f"src_{i:03d}{ext}")
                    ok2,info2=download_file(url,dest)
                    if ok2: downloaded.append({"label":name,"path":dest}); st.caption(f"OK {name} {info2}")
                    else: st.warning(f"Loi {name} {info2}")
                    prog.progress((i+1)/len(raw_urls))
                st.session_state["enc_ready"]=downloaded
                if downloaded: st.success(f"Tai xong {len(downloaded)}/{len(raw_urls)} file!")
            if st.session_state.get("enc_ready"):
                enc_files_ready=[p for p in st.session_state["enc_ready"] if os.path.exists(p["path"])]

    if enc_files_ready:
        st.markdown("---")
        if not st.session_state.dbx_token:
            st.markdown('<div class="warn-box">Chua ket noi Dropbox — chi tai xuong thu cong.</div>',unsafe_allow_html=True)
        if st.button(f"Encode {len(enc_files_ready)} video -> YouTube",use_container_width=True,type="primary",key="btn_encode_run"):
            enc_out_tmp=tempfile.mkdtemp(); enc_results=[]
            enc_prog=st.progress(0,text="Bat dau encode...")
            for i,item in enumerate(enc_files_ready):
                label=item["label"]; src_path=item["path"]
                out_name=f"{Path(label).stem}_{enc_res}.mp4"
                out_path=os.path.join(enc_out_tmp,out_name)
                enc_prog.progress(i/len(enc_files_ready),text=f"Encoding {i+1}/{len(enc_files_ready)}: {label}")
                src_info=get_video_info(src_path)
                if src_info:
                    st.markdown(f"""<div class="stat-row">
                      <div class="stat-item">File <span>{label[:35]}</span></div>
                      <div class="stat-item">Size <span>{src_info.get("size_mb",0)} MB</span></div>
                      <div class="stat-item">Res <span>{src_info.get("width",0)}x{src_info.get("height",0)}</span></div>
                      <div class="stat-item">FPS <span>{src_info.get("fps_num",0)}</span></div>
                      <div class="stat-item">Bitrate <span>{src_info.get("tbr",0)} kbps</span></div>
                      <div class="stat-item">Duration <span>{src_info.get("duration",0):.1f}s</span></div>
                    </div>""", unsafe_allow_html=True)
                enc_st=st.empty(); enc_st.info(f"Encoding {label}...")
                ok_e,msg_e,elapsed=encode_for_youtube(src_path,out_path,resolution=enc_res,bitrate=enc_br,fps=enc_fps,audio_bitrate=enc_abr)
                enc_st.empty()
                if not ok_e:
                    st.markdown(f'<div class="result-err">Loi {label} | {msg_e[:400]}</div>',unsafe_allow_html=True)
                    enc_results.append((label,out_name,None,False,None)); continue
                out_info=get_video_info(out_path); out_size=os.path.getsize(out_path)//1024//1024
                st.markdown(f"""<div class="result-ok">
OK {out_name} — {elapsed:.1f}s |
{out_info.get("width",0)}x{out_info.get("height",0)} •
{out_info.get("fps_num",0)}fps •
{out_info.get("tbr",0)}kbps •
{out_size}MB
</div>""", unsafe_allow_html=True)
                dbx_link=None
                if st.session_state.dbx_token:
                    fe=enc_dbx_folder.strip() or "/Encoded"
                    if not fe.startswith("/"): fe="/"+fe
                    afe="" if fe=="/" else fe
                    if st.session_state.dbx_refresh_token:
                        nt,_=dbx_get_access_token(st.session_state.dbx_app_key,st.session_state.dbx_app_secret,st.session_state.dbx_refresh_token)
                        if nt: st.session_state.dbx_token=nt
                    with st.spinner(f"Uploading {out_name}..."):
                        se,fn,um,su=dbx_upload(st.session_state.dbx_token,out_path,afe,out_name)
                    if se:
                        lh=f'<a href="{su}" target="_blank" style="color:#60a5fa;">Dropbox link</a>' if su else ""
                        st.markdown(f'<div class="result-ok">Upload OK {fn} {lh}</div>',unsafe_allow_html=True)
                        dbx_link=su
                    else:
                        st.markdown(f'<div class="result-err">Upload that bai: {um}</div>',unsafe_allow_html=True)
                enc_results.append((label,out_name,out_path,True,dbx_link))
            enc_prog.progress(1.0,text="Encode hoan tat!")
            ok_el=[(n,p,lnk) for _,n,p,ok,lnk in enc_results if ok and p]
            fail_el=[l for l,_,_,ok,_ in enc_results if not ok]
            st.markdown(f'<div class="result-ok">Xong! {len(ok_el)} thanh cong {"| " + str(len(fail_el)) + " that bai" if fail_el else ""}</div>',unsafe_allow_html=True)
            if ok_el:
                dlc=st.columns(min(3,len(ok_el)))
                for i,(name,path,link) in enumerate(ok_el):
                    with dlc[i%3]:
                        with open(path,"rb") as fd:
                            st.download_button(f"Tai {name}",data=fd,file_name=name,mime="video/mp4",key=f"enc_dl_{i}")
                        if link:
                            st.markdown(f'<a href="{link}" target="_blank" style="font-size:0.75rem;color:#60a5fa;">Dropbox</a>',unsafe_allow_html=True)
    else:
        st.markdown('<div class="warn-box">Upload file hoac dan URL de bat dau encode.</div>',unsafe_allow_html=True)
