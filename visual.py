import tkinter as tk
from tkinter import ttk
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
import numpy as np

class ModernSIGINTApp:
    def __init__(self, root):
        self.root = root
        self.root.title("SIMANEEM // SIGINT - Rediseño Moderno")
        self.root.geometry("1400x900")
        self.root.configure(bg='#1a1a2e')
        
        # Configurar estilo
        self.setup_styles()
        
        # Crear layout
        self.create_top_toolbar()
        self.create_main_content()
        self.create_bottom_tabs()
        self.create_status_bar()
        
    def setup_styles(self):
        style = ttk.Style()
        style.theme_use('clam')
        
        # Colores basados en la imagen
        self.colors = {
            'bg_dark': '#1a1a2e',
            'bg_medium': '#1e1e2e',
            'bg_light': '#2a2a3e',
            'accent_blue': '#0080ff',
            'accent_cyan': '#00ccff',
            'text_primary': '#ccccdd',
            'text_bright': '#00aaff',
            'success': '#00ff00',
            'warning': '#ffaa00',
            'danger': '#ff4444'
        }
        
        style.configure('TFrame', background=self.colors['bg_dark'])
        style.configure('TLabelframe', background=self.colors['bg_medium'], 
                       foreground=self.colors['text_bright'])
        style.configure('TLabelframe.Label', background=self.colors['bg_medium'],
                       foreground=self.colors['text_bright'])
        style.configure('TButton', background=self.colors['bg_light'],
                       foreground=self.colors['text_bright'])
        
    def create_top_toolbar(self):
        toolbar = tk.Frame(self.root, height=60, bg=self.colors['bg_medium'])
        toolbar.pack(fill=tk.X, padx=5, pady=5)
        
        # Botón INICIAR (estilo neón)
        start_btn = tk.Button(toolbar, text="▶ INICIAR", 
                             bg=self.colors['accent_blue'], fg='white',
                             font=('Segoe UI', 10, 'bold'),
                             padx=20, pady=8, relief=tk.FLAT)
        start_btn.pack(side=tk.LEFT, padx=5)
        
        # Indicadores LED
        sdr_label = tk.Label(toolbar, text="● SDR: OK", 
                            fg=self.colors['success'], bg=self.colors['bg_medium'],
                            font=('Segoe UI', 9, 'bold'))
        sdr_label.pack(side=tk.LEFT, padx=15)
        
        fpga_label = tk.Label(toolbar, text="● FPGA: OK",
                             fg=self.colors['success'], bg=self.colors['bg_medium'],
                             font=('Segoe UI', 9, 'bold'))
        fpga_label.pack(side=tk.LEFT, padx=5)
        
        # Separador
        tk.Frame(toolbar, width=2, bg=self.colors['accent_blue']).pack(side=tk.LEFT, padx=15, fill=tk.Y)
        
        # Display de frecuencia
        freq_frame = tk.Frame(toolbar, bg=self.colors['bg_dark'], relief=tk.SUNKEN, bd=1)
        freq_frame.pack(side=tk.LEFT, padx=10)
        
        tk.Label(freq_frame, text="FREC:", fg=self.colors['accent_cyan'],
                bg=self.colors['bg_dark'], font=('Segoe UI', 9, 'bold')).pack(side=tk.LEFT, padx=5)
        
        tk.Label(freq_frame, text="2437.000 MHz", fg='white',
                bg=self.colors['bg_dark'], font=('Courier New', 12, 'bold')).pack(side=tk.LEFT, padx=5)
        
        # Medidor de potencia
        power_frame = tk.Frame(toolbar, bg=self.colors['bg_dark'], relief=tk.SUNKEN, bd=1)
        power_frame.pack(side=tk.RIGHT, padx=10)
        
        tk.Label(power_frame, text="POT:", fg=self.colors['accent_cyan'],
                bg=self.colors['bg_dark'], font=('Segoe UI', 9, 'bold')).pack(side=tk.LEFT, padx=5)
        
        tk.Label(power_frame, text="-33.5 dBm", fg=self.colors['accent_cyan'],
                bg=self.colors['bg_dark'], font=('Courier New', 12, 'bold')).pack(side=tk.LEFT, padx=5)
        
        # Barra de progreso simulada
        progress = ttk.Progressbar(power_frame, length=80, mode='determinate',
                                  style='TProgressbar')
        progress.pack(side=tk.LEFT, padx=5)
        progress['value'] = 45
        
    def create_spectrum_plot(self, parent):
        # Crear figura de matplotlib para el espectro
        fig, ax = plt.subplots(figsize=(12, 3), facecolor=self.colors['bg_medium'])
        fig.patch.set_facecolor(self.colors['bg_medium'])
        
        # Datos simulados (similar a la imagen)
        freqs = np.linspace(2.41, 2.5, 1000)
        signal = -120 + 80 * np.exp(-((freqs - 2.43725)**2) / (2*0.0005**2))
        noise = np.random.normal(0, 3, len(freqs))
        spectrum = signal + noise
        
        # Graficar con estilo moderno
        ax.plot(freqs, spectrum, color=self.colors['accent_cyan'], linewidth=2)
        ax.fill_between(freqs, spectrum, -130, alpha=0.3, color=self.colors['accent_cyan'])
        
        # Estilo del gráfico
        ax.set_facecolor(self.colors['bg_dark'])
        ax.grid(True, alpha=0.2, linestyle='--')
        ax.set_xlabel('Frequency (GHz)', color=self.colors['text_primary'])
        ax.set_ylabel('Power (dBm)', color=self.colors['text_primary'])
        ax.tick_params(colors=self.colors['text_primary'])
        
        # Marcar el pico
        peak_freq = 2.43725
        peak_power = -33.5
        ax.plot(peak_freq, peak_power, 'ro', markersize=8)
        ax.annotate(f'Peak: {peak_power} dBm', 
                   xy=(peak_freq, peak_power),
                   xytext=(peak_freq+0.005, peak_power+10),
                   color='white',
                   bbox=dict(boxstyle="round,pad=0.3", facecolor=self.colors['danger'], alpha=0.7))
        
        canvas = FigureCanvasTkAgg(fig, parent)
        canvas.draw()
        return canvas
    
    def create_main_content(self):
        # Splitter vertical para espectro y waterfall
        main_container = tk.Frame(self.root, bg=self.colors['bg_dark'])
        main_container.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        
        # Espectro
        spectrum_frame = tk.LabelFrame(main_container, text="ESPECTRO", 
                                       bg=self.colors['bg_medium'],
                                       fg=self.colors['text_bright'],
                                       font=('Segoe UI', 10, 'bold'))
        spectrum_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 5))
        
        spectrum_canvas = self.create_spectrum_plot(spectrum_frame)
        spectrum_canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        
        # Waterfall (simulado con texto)
        waterfall_frame = tk.LabelFrame(main_container, text="WATERFALL",
                                        bg=self.colors['bg_medium'],
                                        fg=self.colors['text_bright'],
                                        font=('Segoe UI', 10, 'bold'))
        waterfall_frame.pack(fill=tk.BOTH, expand=True, pady=(5, 0))
        
        # Simular waterfall con caracteres
        waterfall_text = tk.Text(waterfall_frame, height=8, bg=self.colors['bg_dark'],
                                fg=self.colors['accent_cyan'], font=('Courier New', 8))
        waterfall_text.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        
        # Generar visualización de waterfall
        chars = ['░', '▒', '▓', '█']
        for i in range(20):
            line = ''.join(np.random.choice(chars, 100, p=[0.5, 0.3, 0.15, 0.05]))
            waterfall_text.insert(tk.END, line + '\n')
        waterfall_text.config(state=tk.DISABLED)
        
    def create_bottom_tabs(self):
        # Notebook para las pestañas inferiores
        notebook = ttk.Notebook(self.root)
        notebook.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        
        # Pestaña 1: IQ Constellation
        constellation_frame = tk.Frame(notebook, bg=self.colors['bg_medium'])
        notebook.add(constellation_frame, text="💠 IQ CONSTELLATION")
        
        # Simular constelación con canvas
        const_canvas = tk.Canvas(constellation_frame, bg=self.colors['bg_dark'],
                                 highlightbackground=self.colors['accent_blue'])
        const_canvas.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        # Dibujar constelación
        width, height = 400, 400
        const_canvas.create_line(width//2, 0, width//2, height, fill=self.colors['accent_blue'])
        const_canvas.create_line(0, height//2, width, height//2, fill=self.colors['accent_blue'])
        
        # Generar puntos QPSK simulados
        for _ in range(200):
            x = np.random.choice([-1, 1]) * np.random.uniform(0.7, 1) * width//4
            y = np.random.choice([-1, 1]) * np.random.uniform(0.7, 1) * height//4
            const_canvas.create_oval(width//2 + x, height//2 + y,
                                    width//2 + x + 2, height//2 + y + 2,
                                    fill=self.colors['accent_cyan'], outline='')
        
        tk.Label(constellation_frame, text="Points: 4096 | Sample Rate: 61.44 MSPS",
                bg=self.colors['bg_medium'], fg=self.colors['text_primary']).pack()
        
        # Pestaña 2: Direction Finding
        doa_frame = tk.Frame(notebook, bg=self.colors['bg_medium'])
        notebook.add(doa_frame, text="📡 DIRECTION FINDING")
        
        # Dibujar círculo polar
        doa_canvas = tk.Canvas(doa_frame, width=400, height=400,
                              bg=self.colors['bg_dark'],
                              highlightbackground=self.colors['accent_blue'])
        doa_canvas.pack(pady=20)
        
        # Círculo externo
        doa_canvas.create_oval(50, 50, 350, 350, outline=self.colors['accent_cyan'], width=2)
        
        # Línea del DOA (63.4 grados)
        import math
        angle = 63.4
        rad = math.radians(angle - 90)
        radius = 150
        center_x, center_y = 200, 200
        end_x = center_x + radius * math.cos(rad)
        end_y = center_y + radius * math.sin(rad)
        
        doa_canvas.create_line(center_x, center_y, end_x, end_y,
                              fill=self.colors['danger'], width=3)
        
        # Marcador del objetivo
        doa_canvas.create_oval(end_x-5, end_y-5, end_x+5, end_y+5,
                              fill=self.colors['accent_cyan'], outline='')
        
        # Etiquetas
        tk.Label(doa_frame, text=f"DOA: 63.4°  |  Confidence: 92%  |  Power: -33.5 dBm",
                bg=self.colors['bg_medium'], fg=self.colors['accent_cyan'],
                font=('Segoe UI', 12, 'bold')).pack()
        
        # Pestaña 3: Audio Monitor
        audio_frame = tk.Frame(notebook, bg=self.colors['bg_medium'])
        notebook.add(audio_frame, text="🎧 AUDIO MONITOR")
        
        # Controles
        controls_frame = tk.Frame(audio_frame, bg=self.colors['bg_medium'])
        controls_frame.pack(fill=tk.X, padx=10, pady=10)
        
        tk.Label(controls_frame, text="Demod:", bg=self.colors['bg_medium'],
                fg=self.colors['text_primary']).pack(side=tk.LEFT, padx=5)
        
        demod_combo = ttk.Combobox(controls_frame, values=['NFM', 'WFM', 'AM'], width=8)
        demod_combo.set('NFM')
        demod_combo.pack(side=tk.LEFT, padx=5)
        
        # Checkboxes
        for text in ['Max Hold', 'Average']:
            cb = tk.Checkbutton(controls_frame, text=text, bg=self.colors['bg_medium'],
                               fg=self.colors['text_primary'], selectcolor=self.colors['bg_dark'])
            cb.pack(side=tk.LEFT, padx=10)
        
        # Simular espectro de audio
        audio_canvas = self.create_spectrum_plot(audio_frame)
        audio_canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        # Pestaña 4: Signal Detection Table
        signals_frame = tk.Frame(notebook, bg=self.colors['bg_medium'])
        notebook.add(signals_frame, text="📊 SIGNAL DETECTION")
        
        # Tabla de detecciones
        columns = ('Freq (MHz)', 'BW (kHz)', 'Power (dBm)', 'SNR', 'Type', 'Confidence')
        tree = ttk.Treeview(signals_frame, columns=columns, show='headings', height=10)
        
        for col in columns:
            tree.heading(col, text=col)
            tree.column(col, width=120)
        
        # Datos de ejemplo
        signals = [
            ('2437.250', '11200', '-33.5', '24.2', '🟢 WiFi 802.11g', '98%'),
            ('2442.112', '20000', '-52.1', '12.5', '🟡 Unknown', '72%'),
            ('2426.780', '12500', '-61.3', '8.4', '🟠 Bluetooth LE', '85%'),
            ('2450.500', '8000', '-71.8', '4.1', '🔴 LoRa', '65%'),
        ]
        
        for signal in signals:
            tree.insert('', tk.END, values=signal)
        
        tree.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        # Botones de acción
        btn_frame = tk.Frame(signals_frame, bg=self.colors['bg_medium'])
        btn_frame.pack(fill=tk.X, padx=10, pady=5)
        
        for text in ['🗑️ LIMPIAR', '📤 EXPORTAR', '🔍 FILTRAR']:
            btn = tk.Button(btn_frame, text=text, bg=self.colors['bg_light'],
                           fg=self.colors['text_bright'], relief=tk.FLAT)
            btn.pack(side=tk.LEFT, padx=5)
    
    def create_status_bar(self):
        status_frame = tk.Frame(self.root, height=120, bg=self.colors['bg_medium'])
        status_frame.pack(fill=tk.X, side=tk.BOTTOM, padx=5, pady=5)
        
        tk.Label(status_frame, text="⚠ ALERT LOG", font=('Segoe UI', 9, 'bold'),
                fg=self.colors['accent_cyan'], bg=self.colors['bg_medium']).pack(anchor=tk.W, padx=10, pady=5)
        
        # Log de alertas
        log_text = tk.Text(status_frame, height=4, bg=self.colors['bg_dark'],
                          fg=self.colors['text_primary'], font=('Consolas', 8))
        log_text.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)
        
        alerts = [
            ('🔴', 'HIGH', 'Unknown signal detected at 2.442 GHz'),
            ('🟡', 'MEDIUM', 'New WiFi network detected - SNR: 24dB'),
            ('🟢', 'LOW', 'Bluetooth LE activity detected'),
            ('🔴', 'HIGH', 'Strong signal detected - DOA 63°, Power -33.5 dBm'),
            ('🔵', 'INFO', 'Scan complete - 4 signals found')
        ]
        
        for icon, level, msg in alerts:
            log_text.insert(tk.END, f"{icon} {level:6}  {msg}\n")
        
        log_text.config(state=tk.DISABLED)
        
        # Botón clear
        clear_btn = tk.Button(status_frame, text="🗑️ CLEAR LOG",
                             bg=self.colors['bg_light'], fg=self.colors['text_bright'],
                             relief=tk.FLAT)
        clear_btn.pack(side=tk.RIGHT, padx=10, pady=5)

if __name__ == "__main__":
    root = tk.Tk()
    app = ModernSIGINTApp(root)
    root.mainloop()