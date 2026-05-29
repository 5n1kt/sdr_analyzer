#include "fft_processor.hpp"
#include <fftw3.h>
#include <cmath>
#include <unordered_map>
#include <algorithm>
#include <chrono>
#include <mutex>
#include <iostream>

namespace dsp {

// ============================================================================
// IMPLEMENTACIÓN PRIVADA
// ============================================================================

class FFTProcessor::Impl {
public:
    FFTConfig config;
    FFTStats stats;
    
    // FFTW3 planificaciones
    fftwf_plan forward_plan = nullptr;
    fftwf_complex* fft_in = nullptr;
    fftwf_complex* fft_out = nullptr;
    
    // Buffers
    std::vector<float> window;
    std::vector<double> power_accum;
    int frames_accum = 0;
    bool frame_pending = false;
    
    // Caché de ventanas (estática para compartir entre instancias)
    static std::unordered_map<std::string, std::vector<float>> window_cache;
    static std::mutex cache_mutex;
    
    // Temporizador
    std::chrono::steady_clock::time_point last_time;
    double last_process_time_ms = 0.0;
    
    Impl() {
        last_time = std::chrono::steady_clock::now();
        stats.fft_size = config.fft_size;
        stats.averaging_target = config.averaging;
        
        // Inicializar FFTW3 con soporte multi-thread
        static bool fftw_initialized = false;
        if (!fftw_initialized) {
            std::cout << "[C++] Initializing FFTW3 with threading support" << std::endl;
            fftwf_init_threads();
            fftwf_plan_with_nthreads(4);  // Usar 4 threads
            fftw_initialized = true;
        }

        // === INICIALIZACIÓN POR DEFECTO ===
        int default_size = 1024;
        std::cout << "[C++] Creating default FFT plan with size: " << default_size << std::endl;
        fft_in = (fftwf_complex*)fftwf_malloc(sizeof(fftwf_complex) * default_size);
        fft_out = (fftwf_complex*)fftwf_malloc(sizeof(fftwf_complex) * default_size);
        forward_plan = fftwf_plan_dft_1d(default_size, fft_in, fft_out, FFTW_FORWARD, FFTW_MEASURE);
        stats.fft_size = default_size;
        // ==================================

    }
    
    ~Impl() {
        if (forward_plan) {
            fftwf_destroy_plan(forward_plan);
        }
        if (fft_in) {
            fftwf_free(fft_in);
        }
        if (fft_out) {
            fftwf_free(fft_out);
        }
    }
    
    void resize_fft(int size) {
        std::cout << "[C++] resize_fft called with size: " << size << std::endl;
        
        // Liberar planes existentes
        if (forward_plan) {
            fftwf_destroy_plan(forward_plan);
        }
        if (fft_in) {
            fftwf_free(fft_in);
        }
        if (fft_out) {
            fftwf_free(fft_out);
        }
        
        // Inicializar FFTW3 con planificación optimizada
        fft_in = (fftwf_complex*)fftwf_malloc(sizeof(fftwf_complex) * size);
        fft_out = (fftwf_complex*)fftwf_malloc(sizeof(fftwf_complex) * size);
        
        // Usar FFTW_MEASURE para mejor rendimiento (primera vez más lenta)
        std::cout << "[C++] Creating FFTW plan with size: " << size << std::endl;
        forward_plan = fftwf_plan_dft_1d(
            size,
            fft_in,
            fft_out,
            FFTW_FORWARD,
            FFTW_MEASURE
        );
        
        if (!forward_plan) {
            std::cout << "[C++] ERROR: Failed to create FFTW plan!" << std::endl;
        } else {
            std::cout << "[C++] FFTW plan created successfully" << std::endl;
        }
        
        stats.fft_size = size;
        power_accum.clear();
        power_accum.resize(size, 0.0);
    }
    
    std::vector<float> get_window(int size, const std::string& type) {
        std::string cache_key = std::to_string(size) + "_" + type;
        
        std::lock_guard<std::mutex> lock(cache_mutex);
        auto it = window_cache.find(cache_key);
        if (it != window_cache.end()) {
            return it->second;
        }
        
        std::cout << "[C++] Calculating window: size=" << size << ", type=" << type << std::endl;
        
        // Calcular ventana
        std::vector<float> w(size);
        
        if (type == "rectangular") {
            std::fill(w.begin(), w.end(), 1.0f);
        }
        else if (type == "hann") {
            for (int i = 0; i < size; i++) {
                w[i] = 0.5f * (1.0f - std::cos(2.0f * M_PI * i / (size - 1)));
            }
        }
        else if (type == "hamming") {
            for (int i = 0; i < size; i++) {
                w[i] = 0.54f - 0.46f * std::cos(2.0f * M_PI * i / (size - 1));
            }
        }
        else if (type == "blackman") {
            float a0 = 0.42f;
            float a1 = 0.5f;
            float a2 = 0.08f;
            for (int i = 0; i < size; i++) {
                w[i] = a0 - a1 * std::cos(2.0f * M_PI * i / (size - 1)) +
                       a2 * std::cos(4.0f * M_PI * i / (size - 1));
            }
        }
        else if (type == "kaiser") {
            float beta = 14.0f;
            float i0_beta = std::cyl_bessel_i(0, beta);
            for (int i = 0; i < size; i++) {
                float x = 2.0f * i / (size - 1) - 1.0f;
                w[i] = std::cyl_bessel_i(0, beta * std::sqrt(1.0f - x * x)) / i0_beta;
            }
        }
        else {
            // Default: Hann
            for (int i = 0; i < size; i++) {
                w[i] = 0.5f * (1.0f - std::cos(2.0f * M_PI * i / (size - 1)));
            }
        }
        
        window_cache[cache_key] = w;
        return w;
    }
    
    void compute_fft(const std::vector<std::complex<float>>& segment) {
        if (!forward_plan) {
            std::cout << "[C++] ERROR: forward_plan is NULL!" << std::endl;
            return;
        }
        
        if (!fft_in || !fft_out) {
            std::cout << "[C++] ERROR: fft_in or fft_out is NULL!" << std::endl;
            return;
        }
        
        if (segment.size() != static_cast<size_t>(stats.fft_size)) {
            std::cout << "[C++] ERROR: Segment size mismatch. Expected: " 
                      << stats.fft_size << ", got: " << segment.size() << std::endl;
            return;
        }
        
        // Verificar datos antes de FFT
        float max_val = 0;
        for (size_t i = 0; i < std::min(segment.size(), (size_t)10); i++) {
            max_val = std::max(max_val, std::abs(segment[i].real()));
            max_val = std::max(max_val, std::abs(segment[i].imag()));
        }
        std::cout << "[C++] Before FFT - max value: " << max_val << std::endl;
        
        // Copiar datos a entrada de FFTW3
        for (size_t i = 0; i < segment.size(); i++) {
            fft_in[i][0] = segment[i].real();
            fft_in[i][1] = segment[i].imag();
        }
        
        // Ejecutar FFT
        std::cout << "[C++] Executing FFTW3..." << std::endl;
        fftwf_execute(forward_plan);
        std::cout << "[C++] FFTW3 execution completed" << std::endl;
        
        // Verificar salida después de FFT
        max_val = 0;
        for (int i = 0; i < std::min(10, stats.fft_size); i++) {
            max_val = std::max(max_val, std::abs(fft_out[i][0]));
        }
        std::cout << "[C++] After FFT - max real output: " << max_val << std::endl;
    }
    
    std::vector<float> get_power_db() {
        std::vector<float> power(stats.fft_size);
        
        // Calcular potencia = |FFT|^2
        float max_power = 0;
        for (int i = 0; i < stats.fft_size; i++) {
            float real = fft_out[i][0];
            float imag = fft_out[i][1];
            power[i] = real * real + imag * imag;
            max_power = std::max(max_power, power[i]);
        }
        std::cout << "[C++] Max power (linear): " << max_power << std::endl;
        
        // Normalización por tamaño FFT
        float fft_norm = 1.0f / stats.fft_size;
        for (int i = 0; i < stats.fft_size; i++) {
            power[i] *= fft_norm;
        }
        
        // Normalizar por potencia de la ventana
        if (!window.empty()) {
            float window_power = 0.0f;
            for (float w : window) {
                window_power += w * w;
            }
            window_power /= stats.fft_size;
            std::cout << "[C++] Window power: " << window_power << std::endl;
            
            for (int i = 0; i < stats.fft_size; i++) {
                power[i] /= window_power;
            }
        }
        
        // Convertir a dB
        float eps = 1e-12f;
        for (int i = 0; i < stats.fft_size; i++) {
            if (power[i] < eps) {
                power[i] = eps;
            }
            power[i] = 10.0f * std::log10(power[i]);
        }
        
        // Verificar primeros valores en dB
        std::cout << "[C++] After dB conversion - first 5 values:" << std::endl;
        for (int i = 0; i < std::min(5, stats.fft_size); i++) {
            std::cout << "[C++]   power[" << i << "] = " << power[i] << " dB" << std::endl;
        }
        
        // Aplicar piso de ruido
        for (int i = 0; i < stats.fft_size; i++) {
            if (power[i] < config.floor_db) {
                power[i] = config.floor_db;
            }
        }
        
        // Desplazar para frecuencia cero al centro
        std::rotate(power.begin(), power.begin() + stats.fft_size / 2, power.end());
        
        return power;
    }
    
    void apply_window(std::vector<std::complex<float>>& segment) {
        if (window.size() != segment.size()) {
            window = get_window(segment.size(), config.window_type);
        }
        
        for (size_t i = 0; i < segment.size(); i++) {
            segment[i] *= window[i];
        }
    }
    
    void update_stats(double process_time_ms) {
        stats.frames_processed++;
        
        // Media móvil exponencial
        double alpha = 0.05;
        stats.avg_process_time_ms = alpha * process_time_ms + 
                                    (1.0 - alpha) * stats.avg_process_time_ms;
        last_process_time_ms = process_time_ms;
    }
};

// Inicialización estática
std::unordered_map<std::string, std::vector<float>> FFTProcessor::Impl::window_cache;
std::mutex FFTProcessor::Impl::cache_mutex;

// ============================================================================
// IMPLEMENTACIÓN PÚBLICA
// ============================================================================

FFTProcessor::FFTProcessor() : pImpl(std::make_unique<Impl>()) {
    std::cout << "[C++] FFTProcessor constructor called" << std::endl;
}

FFTProcessor::~FFTProcessor() = default;

void FFTProcessor::configure(const FFTConfig& config) {
    std::cout << "[C++] configure() called" << std::endl;
    std::cout << "[C++]   fft_size: " << config.fft_size << std::endl;
    
    pImpl->config = config;
    pImpl->stats.averaging_target = config.averaging;
    
    if (config.fft_size != pImpl->stats.fft_size) {
        std::cout << "[C++] Calling resize_fft from configure" << std::endl;
        pImpl->resize_fft(config.fft_size);
    }
    
    pImpl->power_accum.clear();
    pImpl->power_accum.resize(config.fft_size, 0.0);
    pImpl->frames_accum = 0;
    
    // Verificar que el plan se creó
    if (pImpl->forward_plan) {
        std::cout << "[C++] FFT plan is ready after configure" << std::endl;
    } else {
        std::cout << "[C++] WARNING: FFT plan is still NULL after configure!" << std::endl;
    }
}

std::vector<float> FFTProcessor::process(const std::vector<std::complex<float>>& samples) {
    auto start = std::chrono::steady_clock::now();
    
    if (samples.size() < static_cast<size_t>(pImpl->config.fft_size)) {
        std::cout << "[C++] process(): samples.size() < fft_size" << std::endl;
        return std::vector<float>(pImpl->config.fft_size, pImpl->config.floor_db);
    }
    
    // Tomar segmento del tamaño FFT
    std::vector<std::complex<float>> segment(
        samples.begin(), 
        samples.begin() + pImpl->config.fft_size
    );
    
    // Aplicar ventana
    pImpl->apply_window(segment);
    
    // Calcular FFT
    pImpl->compute_fft(segment);
    
    // Obtener potencia en dB
    auto result = pImpl->get_power_db();
    
    auto end = std::chrono::steady_clock::now();
    double elapsed_ms = std::chrono::duration<double, std::milli>(end - start).count();
    pImpl->update_stats(elapsed_ms);
    
    return result;
}

std::vector<float> FFTProcessor::process_welch(const std::vector<std::complex<float>>& samples) {
    auto start = std::chrono::steady_clock::now();
    
    int fft_size = pImpl->config.fft_size;
    
    std::cout << "[C++] process_welch called" << std::endl;
    std::cout << "[C++]   samples.size(): " << samples.size() << std::endl;
    std::cout << "[C++]   fft_size: " << fft_size << std::endl;
    std::cout << "[C++]   averaging: " << pImpl->config.averaging << std::endl;
    std::cout << "[C++]   overlap: " << pImpl->config.overlap << std::endl;
    
    // VERIFICACIÓN 1: Muestras suficientes
    if (samples.size() < static_cast<size_t>(fft_size)) {
        std::cout << "[C++] ERROR: samples.size() < fft_size" << std::endl;
        pImpl->stats.averaging_actual = 0;
        return std::vector<float>(fft_size, pImpl->config.floor_db);
    }
    
    int step = fft_size * (100 - pImpl->config.overlap) / 100;
    step = std::max(1, step);
    
    int max_segments = (static_cast<int>(samples.size()) - fft_size) / step + 1;
    int num_segments = std::min(pImpl->config.averaging, max_segments);
    
    std::cout << "[C++]   step: " << step << std::endl;
    std::cout << "[C++]   max_segments: " << max_segments << std::endl;
    std::cout << "[C++]   num_segments: " << num_segments << std::endl;
    
    // VERIFICACIÓN 2: Segments válidos
    if (num_segments < 1) {
        std::cout << "[C++] ERROR: num_segments < 1" << std::endl;
        pImpl->stats.averaging_actual = 0;
        return std::vector<float>(fft_size, pImpl->config.floor_db);
    }
    
    // VERIFICACIÓN 3: Plan FFT válido
    if (!pImpl->forward_plan || !pImpl->fft_in || !pImpl->fft_out) {
        std::cout << "[C++] ERROR: FFT plan not initialized" << std::endl;
        return std::vector<float>(fft_size, pImpl->config.floor_db);
    }
    
    // Reiniciar acumulador
    if (static_cast<int>(pImpl->power_accum.size()) != fft_size) {
        pImpl->power_accum.assign(fft_size, 0.0);
    } else {
        std::fill(pImpl->power_accum.begin(), pImpl->power_accum.end(), 0.0);
    }
    
    // Verificar datos de entrada
    float max_input = 0;
    for (size_t i = 0; i < std::min(samples.size(), (size_t)100); i++) {
        max_input = std::max(max_input, std::abs(samples[i].real()));
        max_input = std::max(max_input, std::abs(samples[i].imag()));
    }
    std::cout << "[C++] Max input value (first 100): " << max_input << std::endl;
    
    // Procesar cada segmento
    for (int i = 0; i < num_segments; i++) {
        int start_idx = i * step;
        
        if (start_idx + fft_size > static_cast<int>(samples.size())) {
            std::cout << "[C++] WARNING: Segment " << i << " out of bounds" << std::endl;
            break;
        }
        
        std::vector<std::complex<float>> segment(
            samples.begin() + start_idx,
            samples.begin() + start_idx + fft_size
        );
        
        // Aplicar ventana
        pImpl->apply_window(segment);
        
        // Calcular FFT
        pImpl->compute_fft(segment);
        
        // Obtener potencia y acumular
        auto power = pImpl->get_power_db();
        for (int j = 0; j < fft_size; j++) {
            pImpl->power_accum[j] += power[j];
        }
    }
    
    // Promediar
    std::vector<float> result(fft_size);
    float inv_num = 1.0f / num_segments;
    for (int i = 0; i < fft_size; i++) {
        result[i] = static_cast<float>(pImpl->power_accum[i]) * inv_num;
    }
    
    pImpl->stats.averaging_actual = num_segments;
    
    auto end = std::chrono::steady_clock::now();
    double elapsed_ms = std::chrono::duration<double, std::milli>(end - start).count();
    pImpl->update_stats(elapsed_ms);
    
    std::cout << "[C++] process_welch completed, returning result" << std::endl;
    
    return result;
}

std::vector<float> FFTProcessor::get_freq_axis() const {
    int fft_size = pImpl->config.fft_size;
    std::vector<float> axis(fft_size);
    float half_band = pImpl->config.sample_rate / 2.0f / 1e6f;  // MHz
    
    for (int i = 0; i < fft_size; i++) {
        axis[i] = -half_band + (i * (2.0f * half_band) / fft_size);
    }
    
    return axis;
}

FFTStats FFTProcessor::get_stats() const {
    return pImpl->stats;
}

void FFTProcessor::reset_stats() {
    pImpl->stats.frames_processed = 0;
    pImpl->stats.avg_process_time_ms = 0.0;
    pImpl->stats.dropped_frames = 0;
}

void FFTProcessor::on_frame_consumed() {
    pImpl->frame_pending = false;
}

} // namespace dsp