# -*- coding: utf-8 -*-
import os, sys, re, json, tempfile, hashlib, subprocess, urllib.request, webbrowser, ctypes
from pathlib import Path

from PySide6 import QtCore, QtGui, QtWidgets
from PySide6.QtCore import Qt, Signal, Slot, QUrl
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QFileDialog, QMessageBox, QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QTabWidget, QScrollArea, QSpinBox, QDoubleSpinBox,
    QCheckBox, QSlider, QGroupBox, QStyle, QProgressBar, QFormLayout, QComboBox,
    QToolBar, QSystemTrayIcon, QMenu
)
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtMultimediaWidgets import QVideoWidget

# ---- Windows extras (opsiyonel – sadece Windows'ta) ----
try:
    from PySide6.QtWinExtras import QWinTaskbarButton, QWinJumpList, QWinJumpListItem
    HAS_WINEXTRAS = True
except Exception:
    HAS_WINEXTRAS = False

APP_TITLE   = "NEXOAUDIO · Qt Studio AI"
APP_VERSION = "v4.3.2"

# ---- LOGO & LİNKLER (burayı özelleştir) ----
LOGO_IMAGE_URL   = "https://osmantemiz.com/storage/favicons/BdfMJu9ZObo7vv8qwrM1u1Z8cVbp6PQ3mzvrYImI.svg"         # PNG/ICO URL'i (256x256 ICO önerilir)
LOGO_LINK_URL    = "https://osmantemiz.com"                  # Pencere/toolbar logoları
TASKBAR_LINK_URL = "https://osmantemiz.com/storage/favicons/BdfMJu9ZObo7vv8qwrM1u1Z8cVbp6PQ3mzvrYImI.svg"          # Görev çubuğu/tepsi linki

PREVIEW_SECONDS_DEFAULT = 15

# ------------------ FFmpeg yardımcıları ------------------
def ff_ok():
    try:
        subprocess.run(["ffmpeg","-version"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
        subprocess.run(["ffprobe","-version"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
        return True
    except Exception:
        return False

def has_filter(name:str)->bool:
    try:
        out=subprocess.run(["ffmpeg","-hide_banner","-filters"], stdout=subprocess.PIPE,
                           stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="ignore", check=True).stdout
        return f" {name} " in out or f" {name}\n" in out
    except Exception:
        return False

def arnndn_available(model:str|None)->bool:
    if not has_filter("arnndn"): return False
    test = f"anullsrc=r=48000,arnndn=m={model}" if model else "anullsrc=r=48000,arnndn=m=rnnoise"
    try:
        p = subprocess.run(["ffmpeg","-hide_banner","-f","lavfi","-i",test,"-t","0.05","-f","null","-"],
                           stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        return p.returncode==0
    except Exception:
        return False

def has_stream(path:str, kind:str)->bool:
    try:
        out=subprocess.run(["ffprobe","-v","error","-select_streams",f"{kind}:0",
                            "-show_entries","stream=codec_type","-of","csv=p=0", path],
                           stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True).stdout.strip()
        return out!=""
    except Exception:
        return True

def media_duration(path:str)->float:
    try:
        out=subprocess.run(["ffprobe","-v","error","-show_entries","format=duration",
                            "-of","default=noprint_wrappers=1:nokey=1", path],
                           stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True).stdout.strip()
        return float(out)
    except Exception:
        return 0.0

def clamp(v,a,b): return max(a, min(b, v))
def suggest_output_path(inp: str) -> str:
    p=Path(inp); ext=p.suffix.lower()
    if ext not in [".mp4",".mov",".mkv",".m4v"]: ext=".mp4"
    return str(p.with_name(p.stem + "_cleaned" + ext))

def run_capture(cmd:list, timeout:int=30):
    try:
        p=subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, universal_newlines=True)
        out=p.communicate(timeout=timeout)[0]
        return (p.returncode==0, out)
    except subprocess.TimeoutExpired:
        try:
            p.terminate()
            try: p.wait(timeout=2)
            except subprocess.TimeoutExpired: p.kill()
        except Exception: pass
        return (False, "[TIMEOUT]")
    except Exception as e:
        return (False, str(e))

# ----------------- Windows AppUserModelID ----------------
def set_windows_app_id(app_id: str = "NEXOAUDIO.QtStudioAI"):
    if sys.platform.startswith("win"):
        try:
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(app_id)
        except Exception:
            pass

# ------------------- Thread İşçileri ---------------------
class FFmpegStreamWorker(QtCore.QThread):
    percent = Signal(int); finished = Signal(bool, str)
    def __init__(self, cmd, log_path, total_seconds:float, parent=None):
        super().__init__(parent); self.cmd=cmd; self.log_path=log_path; self.total=total_seconds; self._proc=None
    def run(self):
        try:
            with open(self.log_path,"w",encoding="utf-8",errors="ignore") as lf:
                lf.write(" ".join(self.cmd)+"\n\n")
                self._proc = subprocess.Popen(self.cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                              text=True, universal_newlines=True)
                for line in self._proc.stdout:
                    lf.write(line)
                    t=None
                    m=re.search(r"time=(\d+):(\d+):(\d+)\.(\d+)", line)
                    if m:
                        t = int(m.group(1))*3600 + int(m.group(2))*60 + int(m.group(3)) + int(m.group(4))/100.0
                    else:
                        m=re.search(r"time=(\d+)\.(\d+)", line)
                        if m: t=float(f"{m.group(1)}.{m.group(2)}")
                    if t is not None and self.total>0:
                        pct=int(clamp(100.0*t/self.total, 0, 100))
                        self.percent.emit(pct)
                ret = self._proc.wait()
            self.finished.emit(ret==0, self.log_path)
        except Exception:
            self.finished.emit(False, self.log_path)
    def cancel(self):
        try:
            if self._proc and self._proc.poll() is None: self._proc.terminate()
        except Exception: pass

class AIStudioWorker(QtCore.QThread):
    done = Signal(bool, str, dict)
    progress = Signal(int, str)
    def __init__(self, input_path:str, target_lufs:float=-18.0,
                 rnn_model:str|None=None, leveler:bool=True,
                 nr_aggr:bool=True, style:str="Natural", humanize:bool=True, enhance_beta:bool=False, parent=None):
        super().__init__(parent)
        self.input_path=input_path; self.target_lufs=target_lufs
        self.rnn_model=rnn_model; self.leveler=leveler; self.nr_aggr=nr_aggr
        self.style=style; self.humanize=humanize; self.enhance_beta=enhance_beta

    @staticmethod
    def _deess_eq(human:bool):
        return ["equalizer=f=6500:t=q:w=2.5:g=-2.5"] if human else \
               ["equalizer=f=6500:t=q:w=2.2:g=-3.5","equalizer=f=8000:t=q:w=1.8:g=-2.0"]

    @staticmethod
    def _style_eq(style:str, human:bool):
        if not has_filter("equalizer"): return []
        if style=="Warm":
            return ["equalizer=f=120:t=q:w=1.2:g=1.2","equalizer=f=3500:t=q:w=1.0:g=1.2","equalizer=f=11000:t=q:w=1.0:g=0.8"]
        if style=="Crisp":
            return ["equalizer=f=180:t=q:w=1.0:g=0.6","equalizer=f=3000:t=q:w=0.9:g=1.8","equalizer=f=12000:t=q:w=0.8:g=1.6"]
        if style=="Radio":
            return ["equalizer=f=150:t=q:w=1.2:g=1.5","equalizer=f=2800:t=q:w=0.9:g=1.6",
                    "equalizer=f=6500:t=q:w=1.2:g=0.6","equalizer=f=12000:t=q:w=0.8:g=1.0"]
        return ["equalizer=f=200:t=q:w=1.0:g=0.8","equalizer=f=3200:t=q:w=1.0:g=1.2","equalizer=f=12000:t=q:w=0.9:g=1.0"]

    @staticmethod
    def _glue_peak():
        return ["acompressor=threshold=-22dB:ratio=2.0:attack=12:release=200:knee=5",
                "acompressor=threshold=-10dB:ratio=1.6:attack=1:release=60:knee=4"]

    @staticmethod
    def _leveler(human:bool):
        parts=[]
        if has_filter("compand"):
            parts.append("compand=attacks=0.5:decays=1.0:points=-80/-36|-36/-24|-24/-12|-12/-6|0/-2:delay=0")
        if has_filter("dynaudnorm"):
            parts.append("dynaudnorm=f=260:g=6:p=0.90")
        if has_filter("alimiter"): parts.append("alimiter=limit=0.93")
        return parts

    def _noise_block(self, noise_floor_db:float, human:bool, strong:bool=False):
        model = self.rnn_model if self.rnn_model else None
        if arnndn_available(model): 
            return [f"arnndn=m={model}" if model else "arnndn=m=rnnoise"]
        if has_filter("afftdn"):
            nr = 20 if strong else (18 if self.nr_aggr and not human else 9)
            nf = int(clamp(noise_floor_db - (10 if strong else (8 if self.nr_aggr and not human else 2)), -34, -16))
            return [f"afftdn=nr={nr}:nf={nf}:nt=w"]
        return []

    def run(self):
        try:
            self.progress.emit(10, "Analiz")
            ok,msg,res=self.process()
            self.progress.emit(100, "Hazır")
            self.done.emit(ok,msg,res)
        except Exception as e:
            self.done.emit(False, str(e), {})

    def process(self):
        ip = self.input_path
        SAMPLE_T = "35"

        def astatslog():
            return ["ffmpeg","-hide_banner","-t", SAMPLE_T, "-i", ip,
                    "-map","a:0","-vn","-analyzeduration","0","-probesize","2000000",
                    "-filter:a","astats=metadata=1:reset=1","-f","null","-"]
        def loudnormlog():
            return ["ffmpeg","-hide_banner","-t", SAMPLE_T, "-i", ip,
                    "-map","a:0","-vn","-analyzeduration","0","-probesize","2000000",
                    "-filter:a", f"loudnorm=I={self.target_lufs}:TP=-1.0:LRA=11.0:print_format=json","-f","null","-"]

        ok2,out2=run_capture(astatslog(),25); self.progress.emit(45,"astats")
        rms_min=-60.0; rms_max=-18.0
        if ok2:
            for ln in out2.splitlines():
                if "RMS_level" in ln:
                    m=re.search(r"RMS_level:\s*(-?\d+(\.\d+)?)", ln)
                    if m:
                        v=float(m.group(1)); rms_max=max(rms_max,v); rms_min=min(rms_min,v)
        noise_floor=rms_min

        okm, meas = run_capture(loudnormlog(), 30); self.progress.emit(65,"loudnorm ölçüm")
        measured=None
        if okm:
            m=re.search(r"\{\s*\"input_i\".*\}", meas, re.S)
            if m:
                try: measured=json.loads(m.group(0))
                except: measured=None

        human=True
        comp_thr = clamp(rms_max-4, -40, -8); gate_thr=clamp(noise_floor+6, -80, -20)

        if self.enhance_beta:
            chain=[]
            chain+=["highpass=f=80","lowpass=f=14000"]
            chain+=self._noise_block(noise_floor,human, strong=True)
            if has_filter("agate"): chain.append(f"agate=threshold={int(gate_thr)}dB:ratio=2.0:attack=8:release=140")
            chain+=["equalizer=f=6500:t=q:w=2.0:g=-2.2","equalizer=f=8500:t=q:w=1.6:g=-1.5"]
            chain+=["equalizer=f=180:t=q:w=1.0:g=0.8","equalizer=f=3000:t=q:w=0.9:g=1.6","equalizer=f=12000:t=q:w=0.8:g=1.4"]
            chain+=self._glue_peak()
            if self.leveler: chain+=self._leveler(human)
            chain.append(f"acompressor=threshold={int(comp_thr)}dB:ratio=2.1:attack=8:release=150:knee=4")
            if measured:
                chain.append(
                    "loudnorm=I={I}:TP=-1.0:LRA=11.0:measured_I={mi}:measured_LRA={mlra}:"
                    "measured_TP={mtp}:measured_thresh={mth}:offset={ofs}:linear=true".format(
                        I=self.target_lufs, mi=measured.get("input_i","-20.0"),
                        mlra=measured.get("input_lra","8.0"), mtp=measured.get("input_tp","-2.0"),
                        mth=measured.get("input_thresh","-30.0"), ofs=measured.get("target_offset","0.0"))
                )
            else:
                chain.append(f"loudnorm=I={self.target_lufs}:TP=-1.0:LRA=11.0")
            if has_filter("adeclip"): chain.append("adeclip")
            if has_filter("asoftclip"): chain.append("asoftclip")
            if has_filter("alimiter"): chain.append("alimiter=limit=0.93")
        else:
            chain=[]
            chain+=["highpass=f=70","lowpass=f=14500"]
            chain+=self._noise_block(noise_floor,human)
            if has_filter("agate"): chain.append(f"agate=threshold={int(gate_thr)}dB:ratio=2.1:attack=10:release=160")
            chain+=self._deess_eq(human)
            chain+=self._style_eq(style=self.style, human=human)
            chain+=self._glue_peak()
            if self.leveler: chain+=self._leveler(human)
            chain.append(f"acompressor=threshold={int(comp_thr)}dB:ratio=2.2:attack=8:release=150:knee=4")
            if measured:
                chain.append(
                    "loudnorm=I={I}:TP=-1.0:LRA=11.0:measured_I={mi}:measured_LRA={mlra}:"
                    "measured_TP={mtp}:measured_thresh={mth}:offset={ofs}:linear=true".format(
                        I=self.target_lufs, mi=measured.get("input_i","-20.0"),
                        mlra=measured.get("input_lra","8.0"), mtp=measured.get("input_tp","-2.0"),
                        mth=measured.get("input_thresh","-30.0"), ofs=measured.get("target_offset","0.0"))
                )
            else:
                chain.append(f"loudnorm=I={self.target_lufs}:TP=-1.0:LRA=11.0")
            if has_filter("adeclip"): chain.append("adeclip")
            if has_filter("asoftclip"): chain.append("asoftclip")
            if has_filter("alimiter"): chain.append("alimiter=limit=0.93")

        studio_chain=",".join([c for c in chain if c])
        return True, ("Adobe Podcast (Beta)" if self.enhance_beta else "AI Studio hazır"), {"studio_chain": studio_chain}

# ----------------- Logo indirme yardımcı -----------------
def fetch_logo_pixmap(url:str)->QPixmap|None:
    try:
        data = urllib.request.urlopen(url, timeout=6).read()
        pm = QPixmap(); pm.loadFromData(data)
        return pm if not pm.isNull() else None
    except Exception:
        return None

# ----------------------- UI ------------------------------
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"{APP_TITLE} {APP_VERSION}")
        self.resize(1260,940)
        self.preview_mode="orig"; self.preview_sec=PREVIEW_SECONDS_DEFAULT
        self.preview_path=None; self.studio_chain=None
        self._worker=None; self._ai=None

        # Logo → pencere, görev çubuğu, tepsi
        self.logo_pixmap = fetch_logo_pixmap(LOGO_IMAGE_URL)
        if self.logo_pixmap:
            icon = QIcon(self.logo_pixmap)
            self.setWindowIcon(icon)
            QApplication.instance().setWindowIcon(icon)  # görev çubuğu simgesi

        self._setup_tray_icon()   # tepsi simgesi (sol tık → site)
        self._setup_taskbar()     # görev çubuğu düğmesi ikonu
        self._setup_jumplist()    # sağ tık menüsüne "Web Sitesi" kısayolu

        self._build_ui()
        if not ff_ok(): QMessageBox.critical(self,"FFmpeg","FFmpeg/FFprobe bulunamadı. PATH'e ekleyin.")

    # ---------- görev çubuğu & jump list ----------
    def _setup_taskbar(self):
        if not (HAS_WINEXTRAS and sys.platform.startswith("win")): return
        try:
            self._taskbar_btn = QWinTaskbarButton(self)
            self._taskbar_btn.setWindow(self.windowHandle())
            if self.logo_pixmap:
                self._taskbar_btn.setIcon(QIcon(self.logo_pixmap))
        except Exception:
            pass

    def _setup_jumplist(self):
        if not (HAS_WINEXTRAS and sys.platform.startswith("win")): return
        try:
            jl = QWinJumpList(self)
            jl.clear()
            cat = jl.tasks()
            item = QWinJumpListItem(QWinJumpListItem.Link)
            item.setTitle("Web Sitesi")
            item.setFilePath("cmd")
            item.setArguments(f'/c start "" "{TASKBAR_LINK_URL}"')
            if self.logo_pixmap: item.setIcon(QIcon(self.logo_pixmap))
            cat.addItem(item)
            jl.refresh()
            self._jumplist = jl
        except Exception:
            pass

    def _setup_tray_icon(self):
        self.tray = QSystemTrayIcon(self)
        if self.logo_pixmap:
            self.tray.setIcon(QIcon(self.logo_pixmap))
        else:
            self.tray.setIcon(self.style().standardIcon(QStyle.SP_ComputerIcon))
        self.tray.setToolTip(f"{APP_TITLE} {APP_VERSION}")
        self.tray.activated.connect(self._tray_activated)
        menu = QMenu()
        actOpen = menu.addAction("Uygulamayı Göster"); actOpen.triggered.connect(self.showNormal)
        actLink = menu.addAction("Web Sitesi");         actLink.triggered.connect(lambda: webbrowser.open(TASKBAR_LINK_URL))
        actQuit = menu.addAction("Çıkış");              actQuit.triggered.connect(QApplication.instance().quit)
        self.tray.setContextMenu(menu)
        self.tray.show()

    def _tray_activated(self, reason):
        if reason in (QSystemTrayIcon.Trigger, QSystemTrayIcon.DoubleClick):
            webbrowser.open(TASKBAR_LINK_URL)

    # ---------------- UI kurulum -----------------
    def status(self, msg: str):
        self.status_label.setText(msg)
        QtWidgets.QApplication.processEvents(QtCore.QEventLoop.AllEvents, 50)

    def _add_logo_toolbar(self):
        tb = QToolBar("Logo"); tb.setMovable(False)
        self.addToolBar(Qt.TopToolBarArea, tb)
        act = QtGui.QAction("Logo", self)
        if self.logo_pixmap: act.setIcon(QIcon(self.logo_pixmap))
        act.triggered.connect(lambda: webbrowser.open(LOGO_LINK_URL))
        tb.addAction(act)

    def _build_ui(self):
        self._add_logo_toolbar()
        cw=QWidget(self); self.setCentralWidget(cw); root=QVBoxLayout(cw)

        r0=QHBoxLayout()
        if self.logo_pixmap:
            lbl = QLabel(); lbl.setPixmap(self.logo_pixmap.scaledToHeight(28, Qt.SmoothTransformation))
            lbl.setCursor(Qt.PointingHandCursor)
            lbl.mousePressEvent = lambda e: webbrowser.open(LOGO_LINK_URL)
            r0.addWidget(lbl)
        title_lbl=QLabel(f"<b>{APP_TITLE} {APP_VERSION}</b>")
        r0.addWidget(title_lbl); r0.addStretch(1)
        root.addLayout(r0)

        r1=QHBoxLayout()
        self.in_edit=QLineEdit(); self.in_btn=QPushButton("Seç…")
        self.out_edit=QLineEdit(); self.out_btn=QPushButton("Kaydet Yeri…")
        self.ai_studio_btn=QPushButton("AI: Studio/Podcast")
        r1.addWidget(QLabel("Girdi:")); r1.addWidget(self.in_edit); r1.addWidget(self.in_btn); r1.addWidget(self.ai_studio_btn)
        r2=QHBoxLayout(); r2.addWidget(QLabel("Çıktı:")); r2.addWidget(self.out_edit); r2.addWidget(self.out_btn)
        self.in_btn.clicked.connect(self.pick_input); self.out_btn.clicked.connect(self.pick_output); self.ai_studio_btn.clicked.connect(self.run_ai_studio)
        root.addLayout(r1); root.addLayout(r2)

        grp=QGroupBox("Önizleme (Video+Ses)"); gl=QVBoxLayout(grp)
        self.video_widget=QVideoWidget(); gl.addWidget(self.video_widget)
        self.player=QMediaPlayer(self); self.audio_out=QAudioOutput(self); self.player.setVideoOutput(self.video_widget); self.player.setAudioOutput(self.audio_out)
        self.audio_out.setVolume(0.9)

        ctr=QHBoxLayout()
        self.play_btn=QPushButton(self.style().standardIcon(QStyle.SP_MediaPlay),"")
        self.pause_btn=QPushButton(self.style().standardIcon(QStyle.SP_MediaPause),"")
        self.stop_btn=QPushButton(self.style().standardIcon(QStyle.SP_MediaStop),"")
        self.slider=QSlider(Qt.Horizontal); self.slider.setRange(0,1000); self.time_lbl=QLabel("00:00 / 00:00")
        ctr.addWidget(self.play_btn); ctr.addWidget(self.pause_btn); ctr.addWidget(self.stop_btn); ctr.addWidget(self.slider,1); ctr.addWidget(self.time_lbl)
        gl.addLayout(ctr)

        mrow=QHBoxLayout()
        self.orig_btn=QPushButton("Orijinal"); self.filt_btn=QPushButton("Filtreli (klip)")
        self.len_spin=QSpinBox(); self.len_spin.setRange(3,120); self.len_spin.setValue(PREVIEW_SECONDS_DEFAULT)
        self.studio_mode_cb=QCheckBox("Studio Modunu Kullan (AI)")
        self.cb_human=QCheckBox("Doğal/Humanize"); self.cb_human.setChecked(True)
        self.style_box=QComboBox(); self.style_box.addItems(["Natural","Warm","Crisp","Radio"])
        self.always_processed_cb=QCheckBox("Her zaman işlenmiş sesi dışa aktar"); self.always_processed_cb.setChecked(True)
        self.cb_enhance=QCheckBox("Adobe Podcast (Beta)")
        self.rnn_path=QLineEdit(""); self.rnn_path.setPlaceholderText("RNNoise .model yolu (ops.)")
        mrow.addWidget(QLabel("Önizleme:")); mrow.addWidget(self.orig_btn); mrow.addWidget(self.filt_btn)
        mrow.addSpacing(12); mrow.addWidget(QLabel("Klip (sn):")); mrow.addWidget(self.len_spin)
        mrow.addStretch(1); mrow.addWidget(QLabel("Stil:")); mrow.addWidget(self.style_box)
        mrow.addWidget(self.studio_mode_cb); mrow.addWidget(self.cb_human); mrow.addWidget(self.always_processed_cb); mrow.addWidget(self.cb_enhance)
        mrow.addWidget(self.rnn_path,1)
        gl.addLayout(mrow); root.addWidget(grp)

        self.play_btn.clicked.connect(self.player.play); self.pause_btn.clicked.connect(self.player.pause)
        self.stop_btn.clicked.connect(self.player.stop)
        self.slider.sliderMoved.connect(self.on_seek); self.player.positionChanged.connect(self.on_pos)
        self.player.durationChanged.connect(self.on_dur)
        self.orig_btn.clicked.connect(lambda:self.set_mode("orig"))
        self.filt_btn.clicked.connect(lambda:self.set_mode("filtered"))

        tabs=QTabWidget(); tabs.addTab(self._build_audio_tab(),"Ses"); tabs.addTab(self._build_video_tab(),"Video")
        root.addWidget(tabs)

        btm=QHBoxLayout()
        self.progress=QProgressBar(); self.progress.setRange(0,100); self.progress.setValue(0); self.progress.setVisible(False)
        self.progress_label=QLabel("")
        self.cancel_btn=QPushButton("İptal"); self.export_btn=QPushButton("Dışa Aktar")
        btm.addWidget(self.progress,2); btm.addWidget(self.progress_label,1); btm.addWidget(self.cancel_btn); btm.addWidget(self.export_btn)
        root.addLayout(btm)
        self.cancel_btn.clicked.connect(self.cancel_current); self.export_btn.clicked.connect(self.export)
        self.status_label=QLabel("Hazır"); root.addWidget(self.status_label)

        pal=self.palette()
        pal.setColor(QtGui.QPalette.Window, QtGui.QColor(18,18,28))
        pal.setColor(QtGui.QPalette.WindowText, Qt.white)
        pal.setColor(QtGui.QPalette.Base, QtGui.QColor(22,26,40))
        pal.setColor(QtGui.QPalette.AlternateBase, QtGui.QColor(30,34,52))
        pal.setColor(QtGui.QPalette.Text, Qt.white)
        pal.setColor(QtGui.QPalette.Button, QtGui.QColor(40,46,66))
        pal.setColor(QtGui.QPalette.ButtonText, Qt.white)
        pal.setColor(QtGui.QPalette.Highlight, QtGui.QColor(121,242,255))
        pal.setColor(QtGui.QPalette.HighlightedText, Qt.black)
        self.setPalette(pal)

    def _build_audio_tab(self):
        w=QWidget(); v=QVBoxLayout(w); sa=QScrollArea(); sa.setWidgetResizable(True)
        inner=QWidget(); f=QFormLayout(inner)
        self.cb_nr_aggr=QCheckBox(); self.cb_nr_aggr.setChecked(True)
        self.cb_leveler=QCheckBox(); self.cb_leveler.setChecked(True)
        self.sb_high=QSpinBox(); self.sb_high.setRange(20,300); self.sb_high.setValue(80)
        self.sb_low=QSpinBox(); self.sb_low.setRange(6000,20000); self.sb_low.setSingleStep(500); self.sb_low.setValue(14500)
        self.sb_aff=QSpinBox(); self.sb_aff.setRange(-35,-12); self.sb_aff.setValue(-24)
        self.db_lufs=QDoubleSpinBox(); self.db_lufs.setRange(-30,-12); self.db_lufs.setSingleStep(0.5); self.db_lufs.setValue(-18.0)
        self.cb_gate=QCheckBox(); self.cb_gate.setChecked(False)
        self.sb_gate=QSpinBox(); self.sb_gate.setRange(-80,-5); self.sb_gate.setValue(-48)
        self.sb_cth=QSpinBox(); self.sb_cth.setRange(-40,-5); self.sb_cth.setValue(-20)
        self.db_cr=QDoubleSpinBox(); self.db_cr.setRange(1.2,4.0); self.db_cr.setSingleStep(0.1); self.db_cr.setValue(2.1)
        self.cb_sib=QCheckBox(); self.cb_sib.setChecked(True)
        self.sb_sibf=QSpinBox(); self.sb_sibf.setRange(3000,9000); self.sb_sibf.setValue(6500)
        self.db_sibq=QDoubleSpinBox(); self.db_sibq.setRange(0.5,6.0); self.db_sibq.setSingleStep(0.1); self.db_sibq.setValue(2.0)
        self.db_sibg=QDoubleSpinBox(); self.db_sibg.setRange(-12.0,-1.0); self.db_sibg.setSingleStep(0.5); self.db_sibg.setValue(-2.2)
        self.sb_ba=QSpinBox(); self.sb_ba.setRange(64,384); self.sb_ba.setSingleStep(32); self.sb_ba.setValue(256)
        self.cb_lim=QCheckBox(); self.cb_lim.setChecked(True)
        self.cb_decl=QCheckBox(); self.cb_decl.setChecked(True)
        self.cb_rnn=QCheckBox(); self.cb_rnn.setChecked(False)
        self.ed_rnnm=QLineEdit("")
        items=[
            ("Agresif Arka Plan Bastırma", self.cb_nr_aggr),
            ("Seviye Sabitle (Leveler)", self.cb_leveler),
            ("High-pass (Hz)",self.sb_high),("Low-pass (Hz)",self.sb_low),("afftdn nf (dB)",self.sb_aff),
            ("Hedef LUFS",self.db_lufs),("Noise Gate",self.cb_gate),("Gate eşiği (dB)",self.sb_gate),
            ("Kompresör eşiği (dB)",self.sb_cth),("Kompresör oranı",self.db_cr),
            ("Sibilans azalt",self.cb_sib),("Sibilans freq (Hz)",self.sb_sibf),
            ("Sibilans Q",self.db_sibq),("Sibilans gain (dB)",self.db_sibg),
            ("Ses bitrate (kbps)",self.sb_ba),("alimiter",self.cb_lim),("adeclip",self.cb_decl),
            ("RNNoise kullan",self.cb_rnn),("RNNoise model (ops.)",self.ed_rnnm),
        ]
        for label,widget in items: f.addRow(label, widget)
        sa.setWidget(inner); v.addWidget(sa); return w

    def _build_video_tab(self):
        w=QWidget(); v=QVBoxLayout(w); sa=QScrollArea(); sa.setWidgetResizable(True)
        inner=QWidget(); f=QFormLayout(inner)
        self.cb_copy=QCheckBox(); self.cb_copy.setChecked(True)
        self.sb_scale=QSpinBox(); self.sb_scale.setRange(0,3840); self.sb_scale.setValue(0)
        self.sb_fps=QSpinBox(); self.sb_fps.setRange(0,120); self.sb_fps.setValue(0)
        for label,widget in [
            ("Videoyu kopyala (hızlı)",self.cb_copy),
            ("Ölçek genişliği (0=aynı)",self.sb_scale),
            ("FPS (0=aynı)",self.sb_fps),
        ]: f.addRow(label, widget)
        sa.setWidget(inner); v.addWidget(sa); return w

    def _style_eq_profile(self, style:str, human:bool):
        if not has_filter("equalizer"): return []
        if style=="Warm":
            return ["equalizer=f=120:t=q:w=1.2:g=1.2","equalizer=f=3500:t=q:w=1.0:g=1.2","equalizer=f=11000:t=q:w=1.0:g=0.8"]
        if style=="Crisp":
            return ["equalizer=f=180:t=q:w=1.0:g=0.6","equalizer=f=3000:t=q:w=0.9:g=1.8","equalizer=f=12000:t=q:w=0.8:g=1.6"]
        if style=="Radio":
            return ["equalizer=f=150:t=q:w=1.2:g=1.5","equalizer=f=2800:t=q:w=0.9:g=1.6","equalizer=f=6500:t=q:w=1.2:g=0.6","equalizer=f=12000:t=q:w=0.8:g=1.0"]
        return ["equalizer=f=200:t=q:w=1.0:g=0.8","equalizer=f=3200:t=q:w=1.0:g=1.2","equalizer=f=12000:t=q:w=0.9:g=1.0"]

    def build_filters(self):
        human = self.cb_human.isChecked()
        style = self.style_box.currentText()
        if self.cb_enhance.isChecked():
            af=[f"highpass=f={max(70,self.sb_high.value())}",
                f"lowpass=f={min(14500,self.sb_low.value())}"]
            use_rnn=self.cb_rnn.isChecked(); rnn_model=self.ed_rnnm.text().strip() or None
            if use_rnn and arnndn_available(rnn_model):
                af.append(f"arnndn=m={rnn_model}" if rnn_model else "arnndn=m=rnnoise")
            else:
                af.append(f"afftdn=nr=20:nf={self.sb_aff.value()}:nt=w")
            if self.cb_gate.isChecked() and has_filter("agate"):
                af.append(f"agate=threshold={self.sb_gate.value()}dB:ratio=2:attack=8:release=140")
            af += ["equalizer=f=6500:t=q:w=2.0:g=-2.2","equalizer=f=8500:t=q:w=1.6:g=-1.5"]
            af += ["equalizer=f=180:t=q:w=1.0:g=0.8","equalizer=f=3000:t=q:w=0.9:g=1.6","equalizer=f=12000:t=q:w=0.8:g=1.4"]
            af += ["acompressor=threshold=-22dB:ratio=2.0:attack=12:release=200:knee=5",
                   "acompressor=threshold=-10dB:ratio=1.6:attack=1:release=60:knee=4"]
            if self.cb_leveler.isChecked():
                if has_filter("compand"):   af.append("compand=attacks=0.5:decays=1.0:points=-80/-36|-36/-24|-24/-12|-12/-6|0/-2:delay=0")
                if has_filter("dynaudnorm"): af.append("dynaudnorm=f=260:g=6:p=0.90")
            af.append(f"acompressor=threshold={self.sb_cth.value()}dB:ratio={self.db_cr.value():.1f}:attack=8:release=150:knee=4")
            af.append(f"loudnorm=I={self.db_lufs.value():.1f}:TP=-1.0:LRA=11.0")
            if has_filter("adeclip") and self.cb_decl.isChecked(): af.append("adeclip")
            if has_filter("asoftclip") and human: af.append("asoftclip")
            if has_filter("alimiter"): af.append("alimiter=limit=0.93")
            return ",".join([a for a in af if a])

        af=[f"highpass=f={self.sb_high.value()}",
            f"lowpass=f={self.sb_low.value()}"]
        use_rnn=self.cb_rnn.isChecked(); rnn_model=self.ed_rnnm.text().strip() or None
        if use_rnn and arnndn_available(rnn_model):
            af.append(f"arnndn=m={rnn_model}" if rnn_model else "arnndn=m=rnnoise")
        else:
            af.append(f"afftdn=nr=9:nf={self.sb_aff.value()}")
        if self.cb_gate.isChecked() and has_filter("agate"):
            af.append(f"agate=threshold={self.sb_gate.value()}dB:ratio=2.1:attack=10:release=160")
        af.append(f"equalizer=f={self.sb_sibf.value()}:t=q:w={max(1.2,self.db_sibq.value()):.2f}:g={self.db_sibg.value():.1f}")
        af += ["acompressor=threshold=-22dB:ratio=2.0:attack=12:release=200:knee=5",
               "acompressor=threshold=-10dB:ratio=1.6:attack=1:release=60:knee=4"]
        if self.cb_leveler.isChecked():
            if has_filter("compand"):   af.append("compand=attacks=0.5:decays=1.0:points=-80/-36|-36/-24|-24/-12|-12/-6|0/-2:delay=0")
            if has_filter("dynaudnorm"): af.append("dynaudnorm=f=260:g=6:p=0.90")
        af += self._style_eq_profile(style, human)
        af.append(f"acompressor=threshold={self.sb_cth.value()}dB:ratio={self.db_cr.value():.1f}:attack=8:release=150:knee=4")
        af.append(f"loudnorm=I={self.db_lufs.value():.1f}:TP=-1.0:LRA=11.0")
        if has_filter("adeclip") and self.cb_decl.isChecked(): af.append("adeclip")
        if has_filter("asoftclip") and human: af.append("asoftclip")
        if has_filter("alimiter"): af.append("alimiter=limit=0.93")
        return ",".join([a for a in af if a])

    def _has_audio_filter(self, cmd:list)->bool:
        return any(a.startswith("-filter:a") or a=="-af" for a in cmd)

    def _inject_filter_before_output(self, cmd:list, af:str)->list:
        if not af or self._has_audio_filter(cmd): return cmd
        return cmd[:-1] + ["-filter:a:0", af] + [cmd[-1]]

    def _simplify_on_error(self, af:str, err:str)->str:
        removes=[]
        for key in ["arnndn","agate","asoftclip","alimiter","adeclip","equalizer","compand","dynaudnorm","loudnorm"]:
            if f"filter '{key}'" in err or f"No such filter: '{key}'" in err: removes.append(key)
        if not removes: return af
        kept=[]
        for p in af.split(","):
            if any(p.strip().startswith(r+"=") or p.strip()==r for r in removes): continue
            kept.append(p)
        return ",".join(kept)

    def _ff_try_with_rescue(self, base_cmd:list, af:str, timeout:int):
        cmd = self._inject_filter_before_output(list(base_cmd), af)
        ok, out = run_capture(cmd, timeout)
        if ok: return True, out, af
        new_af = self._simplify_on_error(af, out)
        if new_af != af:
            self.status("Filtrelerin bir kısmı desteklenmiyor → sadeleştiriliyor…")
            cmd2 = self._inject_filter_before_output(list(base_cmd), new_af)
            ok2, out2 = run_capture(cmd2, timeout)
            if ok2: return True, out2, new_af
            basic=[p for p in af.split(",") if p.startswith("highpass") or p.startswith("lowpass")]
            if has_filter("alimiter"): basic.append("alimiter=limit=0.93")
            cmd3 = self._inject_filter_before_output(list(base_cmd), ",".join(basic) if basic else "")
            ok3, out3 = run_capture(cmd3, timeout)
            if ok3: return True, out3, ",".join(basic)
            return False, out3, ",".join(basic)
        return False, out, af

    # --------------- dosya & önizleme ---------------
    def pick_input(self):
        p,_=QFileDialog.getOpenFileName(self,"Video seç","","Video (*.mp4 *.mov *.mkv *.m4v *.avi *.webm);;Tümü (*.*)")
        if p:
            self.in_edit.setText(p)
            if not self.out_edit.text(): self.out_edit.setText(suggest_output_path(p))
            self.status("Girdi seçildi. Orijinal/Filtreli ile önizleyin.")

    def pick_output(self):
        p,_=QFileDialog.getSaveFileName(self,"Çıktı", self.out_edit.text() or "", "MP4 (*.mp4);;MOV (*.mov);;MKV (*.mkv);;M4V (*.m4v)")
        if p: self.out_edit.setText(p)

    def set_mode(self, mode):
        if mode not in ("orig","filtered"): return
        self.preview_mode=mode; self.preview_sec=max(3,int(self.len_spin.value()))
        if mode=="orig": self.load_media(self.in_edit.text().strip())
        else: self.make_preview_clip()

    def load_media(self, path):
        if not path or not os.path.isfile(path): self.status("Önce giriş videosu seç."); return
        self.player.setSource(QUrl.fromLocalFile(path)); self.player.play(); self.status("Önizleme başladı.")

    def make_preview_clip(self):
        ip=self.in_edit.text().strip()
        if not ip or not os.path.isfile(ip): self.status("Önce giriş videosu seç."); return
        sec=max(3,int(self.len_spin.value()))
        af = (self.studio_chain if (self.studio_mode_cb.isChecked() and self.studio_chain) else self.build_filters())
        sig=f"{os.path.abspath(ip)}|{sec}|{af}"
        h=hashlib.sha1(sig.encode("utf-8")).hexdigest()[:10]
        out=str(Path(tempfile.gettempdir())/f"nxa_prev_{h}.mp4"); self.preview_path=out

        base=["ffmpeg","-y","-t",str(sec),"-threads","0","-i",ip]
        if has_stream(ip,"a"):
            base+=["-map","0:a:0?","-c:a:0","aac","-b:a:0","192k","-ac:a:0","1"]
        if has_stream(ip,"v"):
            base+=["-map","0:v:0?","-c:v:0","copy"]
        base+=["-movflags","+faststart",out]

        preview_timeout = max(120, sec*8)
        ok, outlog, used_af = self._ff_try_with_rescue(base, af, timeout=preview_timeout)
        if not ok:
            QMessageBox.critical(self,"Önizleme","Klip üretilemedi (timeout/filtre):\n\n"+outlog[-1200:])
            return
        self.load_media(out)

    # ---------------- dışa aktarım ----------------
    def export(self):
        ip=self.in_edit.text().strip()
        if not ip or not os.path.isfile(ip): self.status("Önce giriş videosu seç."); return
        op=self.out_edit.text().strip() or suggest_output_path(ip)
        os.makedirs(str(Path(op).parent), exist_ok=True); self.out_edit.setText(op)

        af = (self.studio_chain if (self.studio_mode_cb.isChecked() and self.studio_chain) else self.build_filters())
        if not af and self.always_processed_cb.isChecked(): af="highpass=f=80,lowpass=f=14000"

        base=["ffmpeg","-y","-threads","0","-i",ip]
        if has_stream(ip,"a"): base+=["-map","0:a:0?","-filter:a:0",af,"-c:a:0","aac","-b:a:0","256k"]
        base+=["-map","0:v:0?","-c:v:0","copy"]
        base+=["-movflags","+faststart",op]

        total = media_duration(ip)
        log=str(Path(op).with_suffix(""))+"_ffmpeg.log"
        self._worker=FFmpegStreamWorker(base, log, total, self)
        self._worker.percent.connect(lambda p:(self.progress.setVisible(True), self.progress.setValue(p), self.progress_label.setText(f"İşleniyor… %{p}")))
        self._worker.finished.connect(self.on_export_done)
        self.progress.setVisible(True); self.progress.setRange(0,100); self.progress.setValue(0)
        self.status("Dışa aktarma başladı…"); self._worker.start()

    def on_export_done(self,ok,log_path):
        self.progress.setVisible(False); self.progress_label.setText("")
        if ok:
            self.status("Tamamlandı. Dosya kaydedildi.")
            QMessageBox.information(self,"Tamamlandı",f"Çıktı kaydedildi.\nLog: {log_path}")
        else:
            tail=""
            try: tail=open(log_path,"r",encoding="utf-8",errors="ignore").read()[-1600:]
            except Exception: pass
            self.status("Hata."); QMessageBox.critical(self,"Hata",tail or "FFmpeg başarısız.")

    def cancel_current(self):
        try:
            if hasattr(self,"_ai") and self._ai and self._ai.isRunning(): self._ai.terminate()
            if hasattr(self,"_worker") and self._worker and self._worker.isRunning(): self._worker.cancel()
        except Exception: pass
        self.status("İptal istendi.")

    def run_ai_studio(self):
        ip=self.in_edit.text().strip()
        if not ip or not os.path.isfile(ip): self.status("Önce giriş videosu seç."); return
        try:
            subprocess.run(["ffmpeg","-version"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
        except Exception:
            QMessageBox.critical(self,"FFmpeg","FFmpeg bulunamadı."); return
        model_path = self.rnn_path.text().strip() or None
        if model_path and not Path(model_path).is_file():
            QMessageBox.warning(self,"RNNoise","Model yolu geçersiz, afftdn kullanılacak."); model_path=None

        self.ai_studio_btn.setEnabled(False)
        self.progress.setVisible(True); self.progress.setRange(0,100); self.progress.setValue(0)
        self.progress_label.setText("Hazırlanıyor")
        self._ai=AIStudioWorker(
            ip, target_lufs=self.db_lufs.value(),
            rnn_model=model_path,
            leveler=self.cb_leveler.isChecked(),
            nr_aggr=self.cb_nr_aggr.isChecked(),
            style=self.style_box.currentText(),
            humanize=self.cb_human.isChecked(),
            enhance_beta=self.cb_enhance.isChecked(),
            parent=self
        )
        self._ai.progress.connect(lambda p,l:(self.progress.setValue(p), self.progress_label.setText(l)))
        self._ai.done.connect(self.on_ai_studio_done)
        self.status("AI Studio: analiz ediliyor…"); self._ai.start()

    @Slot(bool,str,dict)
    def on_ai_studio_done(self,ok,msg,res):
        self.ai_studio_btn.setEnabled(True)
        self.progress.setVisible(False); self.progress_label.setText("")
        if not ok:
            self.status("AI Studio hatası."); QMessageBox.critical(self,"AI Studio",msg); return
        self.studio_chain=res.get("studio_chain")
        self.studio_mode_cb.setChecked(True); self.status(msg)
        QMessageBox.information(self,"AI Studio",msg)

    # --------------- oynatıcı geri bildirim ---------------
    def on_pos(self,pos_ms):
        dur=self.player.duration() or 1
        self.slider.blockSignals(True); self.slider.setValue(int(1000*pos_ms/dur)); self.slider.blockSignals(False)
        self.time_lbl.setText(f"{self.fmt(pos_ms/1000)} / {self.fmt(dur/1000)}")
    def on_dur(self,dur_ms):
        self.slider.setValue(0); self.time_lbl.setText(f"00:00 / {self.fmt((dur_ms or 0)/1000)}")
    def on_seek(self,val):
        dur=self.player.duration()
        if dur>0: self.player.setPosition(int((val/1000.0)*dur))
    @staticmethod
    def fmt(s): s=max(0.0,float(s)); m=int(s//60); sec=int(s%60); return f"{m:02d}:{sec:02d}"

# ------------------------- main --------------------------
def main():
    os.environ["AV_LOG_FORCE_NOCOLOR"]="1"
    set_windows_app_id("NEXOAUDIO.QtStudioAI")  # görev çubuğu gruplaması+ikon
    app=QApplication(sys.argv); app.setStyle("Fusion")
    win=MainWindow(); win.show(); sys.exit(app.exec())

if __name__=="__main__":
    main()
