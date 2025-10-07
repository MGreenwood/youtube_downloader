#!/usr/bin/env python3
"""
YouTube Video Downloader GUI Application
A simple desktop application to download YouTube videos with various quality options.
"""

import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext
import threading
import os
import sys
from pathlib import Path
import re
import json
import shutil
import subprocess
import time

# We'll prefer using an external yt-dlp executable when packaging to avoid
# PyInstaller scanning the entire yt_dlp Python package. If yt_dlp Python
# package is installed and we're running from source, it will still be used.

def _find_yt_dlp_exe():
    # Look for a bundled yt-dlp.exe next to the script or in the bundle dir
    try:
        if getattr(sys, 'frozen', False):
            base = sys._MEIPASS  # type: ignore[attr-defined]
        else:
            base = os.path.dirname(os.path.abspath(__file__))
    except Exception:
        base = os.path.dirname(os.path.abspath(__file__))

    candidates = [
        os.path.join(base, 'yt-dlp.exe'),
        os.path.join(base, 'yt-dlp'),
    ]

    for c in candidates:
        if os.path.isfile(c) and os.access(c, os.X_OK):
            return c

    # Fall back to PATH
    which = shutil.which('yt-dlp') or shutil.which('yt-dlp.exe')
    return which


def _run_yt_dlp_info(exe_path, url):
    """Run yt-dlp executable to get JSON info for a URL."""
    try:
        # -j prints JSON info
        proc = subprocess.run([exe_path, '-j', url], capture_output=True, text=True, timeout=30)
        if proc.returncode != 0:
            raise RuntimeError(proc.stderr.strip() or 'yt-dlp failed')
        return json.loads(proc.stdout)
    except Exception as e:
        raise


def _run_yt_dlp_download(exe_path, url, outtmpl, format_string, ffmpeg_location=None, progress_callback=None, extra_args=None):
    """Run yt-dlp executable to download a URL and optionally report progress via progress_callback(percent, status)."""
    # Build command with options before the URL
    cmd = [exe_path]
    # Extra arguments (e.g., extract audio) before format
    if extra_args:
        cmd += extra_args
    # Format and output template
    cmd += ['-f', format_string, '-o', outtmpl]
    # FFMPEG location if specified
    if ffmpeg_location:
        cmd += ['--ffmpeg-location', ffmpeg_location]
    # Newline progress marker
    cmd += ['--newline']
    # Finally add URL
    cmd += [url]
    if ffmpeg_location:
        cmd += ['--ffmpeg-location', ffmpeg_location]

    # For audio postprocessing to mp3/m4a let yt-dlp handle if the exe has ffmpeg
    # We'll run it and parse stdout lines for percentages
    with subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1) as p:
        for line in p.stdout:
            line = line.strip()
            # Try to extract a percent like '12.3%' from the line
            m = re.search(r"(\d{1,3}\.\d)%", line)
            if not m:
                m = re.search(r"(\d{1,3})%", line)
            if m:
                try:
                    percent = float(m.group(1))
                    if progress_callback:
                        progress_callback(percent, line)
                except Exception:
                    if progress_callback:
                        progress_callback(-1, line)
            else:
                if progress_callback:
                    progress_callback(-1, line)

        p.wait()
        if p.returncode != 0:
            raise RuntimeError(f"yt-dlp exited with {p.returncode}")


class YouTubeDownloader:
    def __init__(self, root):
        self.root = root
        self.root.title("YouTube Video Downloader")
        self.root.geometry("700x600")
        self.root.resizable(True, True)
        
        # Variables
        self.download_path = tk.StringVar(value=str(Path.home() / "Downloads"))
        self.url_var = tk.StringVar()
        self.quality_var = tk.StringVar(value="best")
        self.format_var = tk.StringVar(value="mp4")
        self.is_downloading = False
        
        # Style configuration
        self.setup_styles()
        
        # Create GUI
        self.create_widgets()
        
        # Center window
        self.center_window()
    
    def setup_styles(self):
        """Configure ttk styles for better appearance"""
        style = ttk.Style()
        
        # Configure button style
        style.configure("Download.TButton", 
                       font=("Arial", 10, "bold"))
        
        # Configure frame style
        style.configure("Main.TFrame", 
                       relief="ridge", borderwidth=1)
    
    def center_window(self):
        """Center the window on the screen"""
        self.root.update_idletasks()
        width = self.root.winfo_width()
        height = self.root.winfo_height()
        x = (self.root.winfo_screenwidth() // 2) - (width // 2)
        y = (self.root.winfo_screenheight() // 2) - (height // 2)
        self.root.geometry(f"{width}x{height}+{x}+{y}")
    
    def create_widgets(self):
        """Create and arrange all GUI widgets"""
        # Main container
        main_frame = ttk.Frame(self.root, style="Main.TFrame", padding="10")
        main_frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        
        # Configure grid weights
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)
        main_frame.columnconfigure(1, weight=1)
        
        # Title
        title_label = ttk.Label(main_frame, text="YouTube Video Downloader", 
                               font=("Arial", 16, "bold"))
        title_label.grid(row=0, column=0, columnspan=3, pady=(0, 20))
        
        # URL input section
        url_frame = ttk.LabelFrame(main_frame, text="Video URL", padding="10")
        url_frame.grid(row=1, column=0, columnspan=3, sticky=(tk.W, tk.E), pady=(0, 10))
        url_frame.columnconfigure(0, weight=1)
        
        self.url_entry = ttk.Entry(url_frame, textvariable=self.url_var, font=("Arial", 10))
        self.url_entry.grid(row=0, column=0, sticky=(tk.W, tk.E), padx=(0, 10))
        
        self.info_button = ttk.Button(url_frame, text="Get Info", command=self.get_video_info)
        self.info_button.grid(row=0, column=1)
        
        # Video information section
        info_frame = ttk.LabelFrame(main_frame, text="Video Information", padding="10")
        info_frame.grid(row=2, column=0, columnspan=3, sticky=(tk.W, tk.E), pady=(0, 10))
        info_frame.columnconfigure(0, weight=1)
        
        self.info_text = scrolledtext.ScrolledText(info_frame, height=6, width=70, 
                                                  font=("Arial", 9), state="disabled")
        self.info_text.grid(row=0, column=0, sticky=(tk.W, tk.E))
        
        # Download options section
        options_frame = ttk.LabelFrame(main_frame, text="Download Options", padding="10")
        options_frame.grid(row=3, column=0, columnspan=3, sticky=(tk.W, tk.E), pady=(0, 10))
        options_frame.columnconfigure(1, weight=1)
        
        # Quality selection
        ttk.Label(options_frame, text="Quality:").grid(row=0, column=0, sticky=tk.W, padx=(0, 10))
        quality_combo = ttk.Combobox(options_frame, textvariable=self.quality_var, 
                                   values=["best", "worst", "720p", "480p", "360p", "240p", "144p"],
                                   state="readonly", width=15)
        quality_combo.grid(row=0, column=1, sticky=tk.W, padx=(0, 20))
        
        # Format selection
        ttk.Label(options_frame, text="Format:").grid(row=0, column=2, sticky=tk.W, padx=(0, 10))
        format_combo = ttk.Combobox(options_frame, textvariable=self.format_var,
                                  values=["mp4", "webm", "mkv", "mp3", "m4a"],
                                  state="readonly", width=10)
        format_combo.grid(row=0, column=3, sticky=tk.W)
        
        # Download path section
        path_frame = ttk.LabelFrame(main_frame, text="Download Location", padding="10")
        path_frame.grid(row=4, column=0, columnspan=3, sticky=(tk.W, tk.E), pady=(0, 10))
        path_frame.columnconfigure(0, weight=1)
        
        self.path_entry = ttk.Entry(path_frame, textvariable=self.download_path, 
                                   font=("Arial", 10), state="readonly")
        self.path_entry.grid(row=0, column=0, sticky=(tk.W, tk.E), padx=(0, 10))
        
        self.browse_button = ttk.Button(path_frame, text="Browse", command=self.browse_folder)
        self.browse_button.grid(row=0, column=1)
        
        # Progress section
        progress_frame = ttk.LabelFrame(main_frame, text="Download Progress", padding="10")
        progress_frame.grid(row=5, column=0, columnspan=3, sticky=(tk.W, tk.E), pady=(0, 10))
        progress_frame.columnconfigure(0, weight=1)
        
        self.progress_var = tk.DoubleVar()
        self.progress_bar = ttk.Progressbar(progress_frame, variable=self.progress_var, 
                                          maximum=100, length=400)
        self.progress_bar.grid(row=0, column=0, sticky=(tk.W, tk.E), pady=(0, 5))
        
        self.status_label = ttk.Label(progress_frame, text="Ready to download", 
                                     font=("Arial", 9))
        self.status_label.grid(row=1, column=0, sticky=tk.W)
        
        # Download button
        self.download_button = ttk.Button(main_frame, text="Download Video", 
                                        command=self.start_download, style="Download.TButton")
        self.download_button.grid(row=6, column=0, columnspan=3, pady=20)
        
        # Bind Enter key to URL entry
        self.url_entry.bind('<Return>', lambda e: self.get_video_info())
    
    def browse_folder(self):
        """Open folder browser dialog"""
        folder = filedialog.askdirectory(initialdir=self.download_path.get())
        if folder:
            self.download_path.set(folder)
    
    def get_video_info(self):
        """Get video information without downloading"""
        url = self.url_var.get().strip()
        if not url:
            messagebox.showwarning("Warning", "Please enter a YouTube URL")
            return
        
        if not self.is_valid_youtube_url(url):
            messagebox.showerror("Error", "Please enter a valid YouTube URL")
            return
        
        self.info_button.config(state="disabled")
        self.status_label.config(text="Getting video information...")
        
        # Run in separate thread to avoid freezing GUI
        thread = threading.Thread(target=self._get_video_info_thread, args=(url,))
        thread.daemon = True
        thread.start()
    
    def _get_video_info_thread(self, url):
        """Thread function to get video info"""
        try:
            # Prefer a bundled yt-dlp executable when available (for packaged EXE).
            yt_exe = _find_yt_dlp_exe()
            info = None
            if yt_exe:
                try:
                    info = _run_yt_dlp_info(yt_exe, url)
                except Exception:
                    info = None

            if info is None:
                # Fall back to Python API if available
                try:
                    import yt_dlp
                    ydl_opts = {
                        'quiet': True,
                        'no_warnings': True,
                    }
                    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                        info = ydl.extract_info(url, download=False)
                except Exception as e:
                    raise

            # Format information for display
            title = info.get('title', 'Unknown')
            uploader = info.get('uploader', 'Unknown')
            duration = info.get('duration', 0)
            view_count = info.get('view_count', 0)

            # Format duration
            if duration:
                minutes, seconds = divmod(duration, 60)
                duration_str = f"{int(minutes):02d}:{int(seconds):02d}"
            else:
                duration_str = "Unknown"

            # Format view count
            if view_count:
                if view_count >= 1000000:
                    view_str = f"{view_count/1000000:.1f}M views"
                elif view_count >= 1000:
                    view_str = f"{view_count/1000:.1f}K views"
                else:
                    view_str = f"{view_count} views"
            else:
                view_str = "Unknown views"

            info_text = f"Title: {title}\n"
            info_text += f"Uploader: {uploader}\n"
            info_text += f"Duration: {duration_str}\n"
            info_text += f"Views: {view_str}\n"

            # Update GUI in main thread
            self.root.after(0, self._update_video_info, info_text)
                
        except Exception as e:
            error_msg = f"Error getting video information: {str(e)}"
            self.root.after(0, self._update_video_info, error_msg)
        finally:
            self.root.after(0, lambda: self.info_button.config(state="normal"))
            self.root.after(0, lambda: self.status_label.config(text="Ready to download"))
    
    def _update_video_info(self, info_text):
        """Update video info display in main thread"""
        self.info_text.config(state="normal")
        self.info_text.delete(1.0, tk.END)
        self.info_text.insert(1.0, info_text)
        self.info_text.config(state="disabled")
    
    def is_valid_youtube_url(self, url):
        """Check if URL is a valid YouTube URL"""
        youtube_regex = re.compile(
            r'(https?://)?(www\.)?(youtube|youtu|youtube-nocookie)\.(com|be)/'
            r'(watch\?v=|embed/|v/|.+\?v=)?([^&=%\?]{11})'
        )
        return youtube_regex.match(url) is not None

    def _locate_ffmpeg(self):
        """Locate ffmpeg executable directory.

        Checks bundled locations (when packaged with PyInstaller) and system PATH.
        Returns the directory containing the ffmpeg executable, or None if not found.
        """
        # If running in a PyInstaller bundle, resources are unpacked to _MEIPASS
        try:
            if getattr(sys, 'frozen', False):
                bundle_dir = sys._MEIPASS  # type: ignore[attr-defined]
            else:
                bundle_dir = os.path.dirname(os.path.abspath(__file__))
        except Exception:
            bundle_dir = os.path.dirname(os.path.abspath(__file__))

        # Common ffmpeg executable names
        names = ['ffmpeg.exe', 'ffmpeg']

        # Check bundled folder first
        for name in names:
            potential = os.path.join(bundle_dir, name)
            if os.path.isfile(potential) and os.access(potential, os.X_OK):
                return bundle_dir

        # Also check a subfolder named 'ffmpeg' (useful when including the ffmpeg folder)
        ffmpeg_subdir = os.path.join(bundle_dir, 'ffmpeg')
        if os.path.isdir(ffmpeg_subdir):
            # Walk the ffmpeg folder to find the ffmpeg executable in common layouts
            for root, dirs, files in os.walk(ffmpeg_subdir):
                for name in names:
                    potential = os.path.join(root, name)
                    if os.path.isfile(potential) and os.access(potential, os.X_OK):
                        return root

        # Fall back to system PATH
        which = shutil.which('ffmpeg')
        if which:
            return os.path.dirname(which)

        return None
    
    def start_download(self):
        """Start the download process"""
        url = self.url_var.get().strip()
        if not url:
            messagebox.showwarning("Warning", "Please enter a YouTube URL")
            return
        
        if not self.is_valid_youtube_url(url):
            messagebox.showerror("Error", "Please enter a valid YouTube URL")
            return
        
        if not os.path.exists(self.download_path.get()):
            messagebox.showerror("Error", "Download folder does not exist")
            return
        
        if self.is_downloading:
            messagebox.showwarning("Warning", "Download already in progress")
            return
        
        # Disable download button and start download
        self.download_button.config(state="disabled", text="Downloading...")
        self.is_downloading = True
        self.progress_var.set(0)
        
        # Start download in separate thread
        thread = threading.Thread(target=self._download_thread, args=(url,))
        thread.daemon = True
        thread.start()
    
    def _download_thread(self, url):
        """Thread function to handle download"""
        try:
            # Determine format and quality
            format_string = self._get_format_string()
            # Try to locate ffmpeg (system or bundled)
            ffmpeg_dir = self._locate_ffmpeg()

            # Prefer executable yt-dlp when packaging
            yt_exe = _find_yt_dlp_exe()
            outtmpl = os.path.join(self.download_path.get(), '%(title)s.%(ext)s')

            if yt_exe:
                # Build arguments for yt-dlp executable
                # For audio conversion, use --extract-audio and --audio-format
                fmt = format_string
                if self.format_var.get() in ['mp3', 'm4a']:
                    fmt = 'bestaudio/best'
                    # Build progress callback
                    def progress_cb(pct, status):
                        try:
                            if pct >= 0:
                                self.root.after(0, self._update_progress, pct, status)
                            else:
                                self.root.after(0, self._update_progress, -1, status)
                        except Exception:
                            pass
                    # Build audio extraction args
                    extra_args = ['--extract-audio', '--audio-format', self.format_var.get()]
                    # Run download with audio conversion
                    _run_yt_dlp_download(
                        yt_exe, url, outtmpl, fmt,
                        ffmpeg_location=ffmpeg_dir,
                        progress_callback=progress_cb,
                        extra_args=extra_args
                    )

                else:
                    def progress_cb(pct, status):
                        try:
                            if pct >= 0:
                                self.root.after(0, self._update_progress, pct, status)
                            else:
                                self.root.after(0, self._update_progress, -1, status)
                        except Exception:
                            pass

                    _run_yt_dlp_download(yt_exe, url, outtmpl, fmt, ffmpeg_location=ffmpeg_dir, progress_callback=progress_cb)

            else:
                # Fall back to Python API
                try:
                    import yt_dlp
                    ydl_opts = {
                        'format': format_string,
                        'outtmpl': outtmpl,
                        'progress_hooks': [self._progress_hook],
                    }

                    if ffmpeg_dir:
                        ydl_opts['ffmpeg_location'] = ffmpeg_dir

                    if self.format_var.get() in ['mp3', 'm4a']:
                        ydl_opts['format'] = 'bestaudio/best'
                        ydl_opts['postprocessors'] = [{
                            'key': 'FFmpegExtractAudio',
                            'preferredcodec': self.format_var.get(),
                            'preferredquality': '192',
                        }]

                    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                        ydl.download([url])
                except Exception:
                    raise
            
            # Success
            self.root.after(0, self._download_complete, True, "Download completed successfully!")
            
        except Exception as e:
            error_msg = f"Download failed: {str(e)}"
            self.root.after(0, self._download_complete, False, error_msg)
    
    def _get_format_string(self):
        """Get format string for yt-dlp based on user selection"""
        quality = self.quality_var.get()
        format_ext = self.format_var.get()
        
        if quality == "best":
            return f"best[ext={format_ext}]/best"
        elif quality == "worst":
            return f"worst[ext={format_ext}]/worst"
        else:
            # Extract height from quality (e.g., "720p" -> "720")
            height = quality.replace('p', '')
            return f"best[height<={height}][ext={format_ext}]/best[height<={height}]/best"
    
    def _progress_hook(self, d):
        """Progress hook for yt-dlp"""
        if d['status'] == 'downloading':
            if 'total_bytes' in d:
                percent = (d['downloaded_bytes'] / d['total_bytes']) * 100
                self.root.after(0, self._update_progress, percent, 
                              f"Downloading... {percent:.1f}%")
            elif 'total_bytes_estimate' in d:
                percent = (d['downloaded_bytes'] / d['total_bytes_estimate']) * 100
                self.root.after(0, self._update_progress, percent, 
                              f"Downloading... {percent:.1f}% (estimated)")
            else:
                self.root.after(0, self._update_progress, -1, "Downloading...")
        
        elif d['status'] == 'finished':
            self.root.after(0, self._update_progress, 100, 
                          f"Download finished: {os.path.basename(d['filename'])}")
    
    def _update_progress(self, percent, status):
        """Update progress bar and status in main thread"""
        if percent >= 0:
            self.progress_var.set(percent)
        self.status_label.config(text=status)
    
    def _download_complete(self, success, message):
        """Handle download completion in main thread"""
        self.is_downloading = False
        self.download_button.config(state="normal", text="Download Video")
        
        if success:
            messagebox.showinfo("Success", message)
            self.progress_var.set(100)
        else:
            messagebox.showerror("Error", message)
            self.progress_var.set(0)
        
        self.status_label.config(text="Ready to download")


def main():
    """Main function to run the application"""
    # Create the main window
    root = tk.Tk()
    
    # Set window icon (if available)
    try:
        root.iconbitmap("icon.ico")  # You can add an icon file
    except:
        pass
    
    # Create the application
    app = YouTubeDownloader(root)
    
    # Start the GUI event loop
    root.mainloop()


if __name__ == "__main__":
    main()
