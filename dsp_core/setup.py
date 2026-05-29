#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from setuptools import setup, Extension
from pybind11.setup_helpers import Pybind11Extension, build_ext
import sys

# Asegurar que pybind11 está instalado
try:
    import pybind11
except ImportError:
    print("Instalando pybind11...")
    import subprocess
    subprocess.check_call([sys.executable, "-m", "pip", "install", "pybind11"])

ext_module = Pybind11Extension(
    "dsp_core",
    [
        "src/fft_processor.cpp",
        "bindings/pybind_module.cpp",
    ],
    include_dirs=["include"],
    extra_compile_args=['-std=c++17', '-O3', '-march=native', '-ffast-math'],
    libraries=['fftw3f', 'fftw3f_threads'],
)

setup(
    name="dsp_core",
    version="1.0.0",
    description="SIMANEEM - Núcleo DSP de alto rendimiento en C++",
    ext_modules=[ext_module],
    cmdclass={"build_ext": build_ext},
    zip_safe=False,
)