#include <pybind11/pybind11.h>
#include <pybind11/stl.h>
#include <pybind11/complex.h>
#include <pybind11/numpy.h>
#include "fft_processor.hpp"

namespace py = pybind11;
using namespace dsp;

// Convertidor de numpy array a vector
std::vector<std::complex<float>> numpy_to_vector(py::array_t<std::complex<float>> arr) {
    py::buffer_info buf = arr.request();
    std::complex<float>* ptr = static_cast<std::complex<float>*>(buf.ptr);
    return std::vector<std::complex<float>>(ptr, ptr + buf.size);
}

// Convertidor inverso
py::array_t<float> vector_to_numpy(const std::vector<float>& vec) {
    return py::array_t<float>(vec.size(), vec.data());
}

PYBIND11_MODULE(dsp_core, m) {
    m.doc() = "Módulo DSP de alto rendimiento para SIMANEEM";
    
    // Configuración FFT
    py::class_<FFTConfig>(m, "FFTConfig")
        .def(py::init<>())
        .def_readwrite("fft_size", &FFTConfig::fft_size)
        .def_readwrite("averaging", &FFTConfig::averaging)
        .def_readwrite("overlap", &FFTConfig::overlap)
        .def_readwrite("window_type", &FFTConfig::window_type)
        .def_readwrite("floor_db", &FFTConfig::floor_db)
        .def_readwrite("sample_rate", &FFTConfig::sample_rate);
    
    // Estadísticas
    py::class_<FFTStats>(m, "FFTStats")
        .def_readonly("frames_processed", &FFTStats::frames_processed)
        .def_readonly("avg_process_time_ms", &FFTStats::avg_process_time_ms)
        .def_readonly("fft_size", &FFTStats::fft_size)
        .def_readonly("averaging_target", &FFTStats::averaging_target)
        .def_readonly("averaging_actual", &FFTStats::averaging_actual)
        .def_readonly("dropped_frames", &FFTStats::dropped_frames);
    
    // Procesador FFT
    py::class_<FFTProcessor>(m, "FFTProcessor")
        .def(py::init<>())
        .def("configure", &FFTProcessor::configure)
        .def("process", [](FFTProcessor& self, py::array_t<std::complex<float>> samples) {
            auto vec = numpy_to_vector(samples);
            auto result = self.process(vec);
            return vector_to_numpy(result);
        }, py::arg("samples"))
        .def("process_welch", [](FFTProcessor& self, py::array_t<std::complex<float>> samples) {
            auto vec = numpy_to_vector(samples);
            auto result = self.process_welch(vec);
            return vector_to_numpy(result);
        }, py::arg("samples"))
        .def("get_freq_axis", [](FFTProcessor& self) {
            return vector_to_numpy(self.get_freq_axis());
        })
        .def("get_stats", &FFTProcessor::get_stats)
        .def("reset_stats", &FFTProcessor::reset_stats)
        .def("on_frame_consumed", &FFTProcessor::on_frame_consumed);
}