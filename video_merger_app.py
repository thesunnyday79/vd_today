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
def download_file(url, dest):
    try:
        r=requests.get(url,stream=True,timeout=120); r.raise_for_status()
        with open(dest,"wb") as f:
            for chunk in r.iter_content(512*1024): f.write(chunk)
        return True
    except Exception as e:
        st.error(f"Download failed: {e}"); return False


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
# ─────────────────────────────────────────────
IMAGE_EXTS_EDIT = {".jpg",".jpeg",".png",".webp",".bmp",".gif",".tiff"}

def _combine_max(parts):
    if len(parts)==1: return parts[0]
    mid=len(parts)//2
    return f"max({_combine_max(parts[:mid])},{_combine_max(parts[mid:])})"

def _snow_alpha_expr(flakes):
    parts=[]
    for flk in flakes:
        sx=flk["x"]; sp=flk["speed"]; dr=flk["drift"]
        sz=flk["size"]; op=flk["opacity"]; ph=flk["phase"]
        px=f"({sx}*W+t*{dr}*W)"
        py=f"mod({ph}+t*{sp},1)*H"
        d=f"sqrt(pow(X-({px}),2)+pow(Y-({py}),2))"
        parts.append(f"if(lt({d},{sz}),{op},0)")
    return _combine_max(parts) if parts else "0"

def make_snow_zoom_video(media_paths, output_path, fps=30,
                          duration_per_image=5.0, zoom_max=1.15,
                          snow_count=60, audio_path=None):
    import random, shutil
    tmp=tempfile.mkdtemp()
    clips=[]
    rng=random.Random(42)
    flakes=[{
        "x":rng.uniform(0,1),"speed":rng.uniform(0.05,0.18),
        "size":rng.randint(2,6),"opacity":rng.uniform(0.5,1.0),
        "drift":rng.uniform(-0.02,0.02),"phase":rng.uniform(0,1),
    } for _ in range(snow_count)]

    snow_expr=_snow_alpha_expr(flakes)
    prog=st.progress(0,text="Dang xu ly...")
    total=len(media_paths)

    for idx,mpath in enumerate(media_paths):
        ext=Path(mpath).suffix.lower()
        out_clip=os.path.join(tmp,f"clip_{idx}.mp4")

        # Get dimensions
        probe=subprocess.run(
            ["ffprobe","-v","error","-select_streams","v:0",
             "-show_entries","stream=width,height","-of","csv=p=0",mpath],
            capture_output=True,text=True)
        try:
            w,h=map(int,probe.stdout.strip().split(","))
            w=w if w%2==0 else w-1; h=h if h%2==0 else h-1
        except Exception:
            w,h=1280,720

        if ext in IMAGE_EXTS_EDIT:
            n_frames=int(fps*duration_per_image)
            half=n_frames//2
            z=f"if(lt(on\\,{half})\\,1+{zoom_max-1}*(on/{half})\\,1+{zoom_max-1}*(1-(on-{half})/{half}))"
            fg=(
                f"[0:v]loop=loop={n_frames}:size=1:start=0,"
                f"zoompan=z='{z}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
                f":d={n_frames}:s={w}x{h}:fps={fps},"
                f"setpts=PTS-STARTPTS[zoomed];"
                f"color=white:size={w}x{h}:rate={fps},"
                f"geq=r=255:g=255:b=255:a='255*({snow_expr})'[snow];"
                f"[zoomed][snow]overlay=format=auto,setpts=PTS-STARTPTS"
            )
            cmd=["ffmpeg","-y","-i",mpath,"-filter_complex",fg,
                 "-t",str(duration_per_image),
                 "-c:v","libx264","-preset","fast","-crf","23",
                 "-pix_fmt","yuv420p","-an",out_clip]
        else:
            dur_p=subprocess.run(
                ["ffprobe","-v","error","-show_entries","format=duration",
                 "-of","default=noprint_wrappers=1:nokey=1",mpath],
                capture_output=True,text=True)
            try: vdur=float(dur_p.stdout.strip())
            except: vdur=5.0
            n_frames=int(fps*vdur); half=n_frames//2
            z=f"if(lt(on\\,{half})\\,1+{zoom_max-1}*(on/{half})\\,1+{zoom_max-1}*(1-(on-{half})/{half}))"
            fg=(
                f"[0:v]"
                f"zoompan=z='{z}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
                f":d={n_frames}:s={w}x{h}:fps={fps},"
                f"setpts=PTS-STARTPTS[zoomed];"
                f"color=white:size={w}x{h}:rate={fps},"
                f"geq=r=255:g=255:b=255:a='255*({snow_expr})'[snow];"
                f"[zoomed][snow]overlay=format=auto,setpts=PTS-STARTPTS"
            )
            cmd=["ffmpeg","-y","-i",mpath,"-filter_complex",fg,
                 "-c:v","libx264","-preset","fast","-crf","23",
                 "-pix_fmt","yuv420p","-an",out_clip]

        r=subprocess.run(cmd,capture_output=True)
        if r.returncode!=0:
            return False,f"Loi xu ly [{os.path.basename(mpath)}]:\n{r.stderr.decode()[-600:]}"
        clips.append(out_clip)
        prog.progress((idx+1)/total,text=f"Xu ly {idx+1}/{total}: {os.path.basename(mpath)}")
    prog.empty()

    # Concat clips
    st.info("Ghep tat ca clip...")
    ctxt=os.path.join(tmp,"edit_concat.txt")
    with open(ctxt,"w") as f:
        f.write("\n".join(f"file '{c}'" for c in clips))
    cout=os.path.join(tmp,"edit_concat.mp4")
    r=subprocess.run(["ffmpeg","-y","-f","concat","-safe","0","-i",ctxt,"-c","copy",cout],capture_output=True)
    if r.returncode!=0:
        return False,f"Concat that bai:\n{r.stderr.decode()[-600:]}"

    # Add audio
    if audio_path and os.path.exists(audio_path):
        st.info("Ghep audio...")
        vid_dur=get_duration(cout); aud_dur=get_duration(audio_path)
        aac=os.path.join(tmp,"edit_audio.aac")
        subprocess.run(["ffmpeg","-y","-i",audio_path,"-vn","-c:a","aac","-b:a","192k","-ar","44100","-ac","2",aac],capture_output=True)
        adj=os.path.join(tmp,"edit_adj.mp4")
        if aud_dur and vid_dur and aud_dur>vid_dur:
            subprocess.run(["ffmpeg","-y","-stream_loop","-1","-i",cout,"-t",str(aud_dur),"-c:v","libx264","-preset","fast","-crf","23","-an",adj],capture_output=True)
        else:
            subprocess.run(["ffmpeg","-y","-i",cout,"-t",str(aud_dur or vid_dur),"-c:v","libx264","-preset","fast","-crf","23","-an",adj],capture_output=True)
        r=subprocess.run(["ffmpeg","-y","-i",adj,"-i",aac,"-c:v","copy","-c:a","aac","-b:a","192k","-map","0:v:0","-map","1:a:0","-shortest",output_path],capture_output=True)
    else:
        shutil.copy(cout,output_path)
        r=type("R",(),{"returncode":0})()

    if r.returncode!=0:
        return False,f"Loi ghep audio:\n{r.stderr.decode()[-600:]}"
    return True,"Edit video hoan tat!"

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

tab1,tab2,tab3,tab4=st.tabs(["🔗 Nhập URL","📋 Danh sách","🚀 Xuất video","✨ Edit video"])

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
    st.markdown("""<div class="info-box">
Dán URL ảnh (<code>.jpg .png .webp</code>) hoặc video (<code>.mp4 .mov</code>) vào ô bên dưới.<br>
Mỗi file sẽ được thêm hiệu ứng <b>tuyết rơi</b> và <b>zoom in → zoom out</b>.<br>
Thứ tự URL = thứ tự xuất hiện trong video.
</div>""",unsafe_allow_html=True)

    edit_urls=st.text_area("Dán URL ảnh/video",height=180,
        placeholder="https://.../anh1.jpg, https://.../clip.mp4",
        key="edit_url_input")
    edit_audio_url=st.text_input("URL audio nền (tuỳ chọn)",
        placeholder="https://.../nhac_nen.mp3",key="edit_audio_url")

    col_e1,col_e2,col_e3=st.columns(3)
    with col_e1: img_duration=st.slider("Thời lượng mỗi ảnh (giây)",2.0,10.0,5.0,0.5)
    with col_e2: zoom_strength=st.slider("Mức zoom (%)",5,30,15,1)
    with col_e3: snow_amount=st.slider("Số bông tuyết",20,120,60,10)
    edit_output_name=st.text_input("Tên file output",value="edit_snow_zoom.mp4",key="edit_out_name")

    EDIT_VIDEO_EXTS={".mp4",".mov",".avi",".mkv",".webm"}
    EDIT_IMAGE_EXTS={".jpg",".jpeg",".png",".webp",".bmp",".gif",".tiff"}

    if edit_urls.strip():
        raw_edit=[u.strip() for u in edit_urls.replace("\n",",").split(",") if u.strip()]
        edit_imgs=[u for u in raw_edit if Path(u.split("?")[0]).suffix.lower() in EDIT_IMAGE_EXTS]
        edit_vids=[u for u in raw_edit if Path(u.split("?")[0]).suffix.lower() in EDIT_VIDEO_EXTS]
        c1e,c2e=st.columns(2)
        with c1e:
            st.markdown(f"**Anh: {len(edit_imgs)}**")
            for i,u in enumerate(edit_imgs,1): st.caption(f"{i}. {u.split('/')[-1].split('?')[0]}")
        with c2e:
            st.markdown(f"**Video: {len(edit_vids)}**")
            for i,u in enumerate(edit_vids,1): st.caption(f"{i}. {u.split('/')[-1].split('?')[0]}")

        if not st.session_state.dbx_token:
            st.markdown('<div class="warn-box">Chua ket noi Dropbox.</div>',unsafe_allow_html=True)

        if st.button("Tao Edit Video",use_container_width=True,type="primary",key="btn_edit"):
            tmp_edit=tempfile.mkdtemp()
            local_media=[]; local_audio=None
            st.markdown("#### Tai media...")
            pme=st.progress(0)
            for i,url in enumerate(raw_edit):
                ext=Path(url.split("?")[0]).suffix.lower() or ".jpg"
                dest=os.path.join(tmp_edit,f"media_{i}{ext}")
                if download_file(url,dest): local_media.append(dest)
                pme.progress((i+1)/len(raw_edit))
            if edit_audio_url.strip():
                ext_a=Path(edit_audio_url.strip().split("?")[0]).suffix.lower() or ".mp3"
                dest_a=os.path.join(tmp_edit,f"edit_audio{ext_a}")
                if download_file(edit_audio_url.strip(),dest_a): local_audio=dest_a
            if not local_media:
                st.markdown('<div class="error-box">Khong tai duoc file nao.</div>',unsafe_allow_html=True)
            else:
                out_edit=os.path.join(tmp_edit,edit_output_name)
                ok_e,msg_e=make_snow_zoom_video(
                    media_paths=local_media,output_path=out_edit,fps=30,
                    duration_per_image=img_duration,zoom_max=1+zoom_strength/100,
                    snow_count=snow_amount,audio_path=local_audio)
                if ok_e:
                    st.markdown('<div class="success-box">Edit video hoan tat!</div>',unsafe_allow_html=True)
                    if st.session_state.dbx_token:
                        folder=dropbox_folder.strip() or "/"
                        if not folder.startswith("/"): folder="/"+folder
                        api_folder="" if folder=="/" else folder
                        if st.session_state.dbx_refresh_token:
                            new_tok,_=dbx_get_access_token(
                                st.session_state.dbx_app_key,
                                st.session_state.dbx_app_secret,
                                st.session_state.dbx_refresh_token)
                            if new_tok: st.session_state.dbx_token=new_tok
                        with st.spinner("Upload Dropbox..."):
                            succ_e,fname_e,umsg_e,surl_e=dbx_upload(
                                st.session_state.dbx_token,out_edit,api_folder,edit_output_name)
                        if succ_e:
                            link_e=f'<br>Link: <a href="{surl_e}" target="_blank">{surl_e}</a>' if surl_e else ""
                            st.markdown(f'<div class="success-box">Upload OK! File: <code>{fname_e}</code>{link_e}</div>',unsafe_allow_html=True)
                        else:
                            st.markdown(f'<div class="error-box">Upload that bai: {umsg_e}</div>',unsafe_allow_html=True)
                    with open(out_edit,"rb") as fe:
                        st.download_button("Tai xuong edit video",data=fe,file_name=edit_output_name,mime="video/mp4",use_container_width=True)
                    st.markdown("#### Xem truoc")
                    st.video(out_edit)
                else:
                    st.markdown(f'<div class="error-box">{msg_e}</div>',unsafe_allow_html=True)
    else:
        st.markdown('<div class="info-box">Dan URL anh hoac video vao o tren de bat dau.</div>',unsafe_allow_html=True)
