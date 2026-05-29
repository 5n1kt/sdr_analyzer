source ~/miniconda3/etc/profile.d/conda.sh
    conda activate simaneem

cd ~/sdr_analyzer/dsp_core

# Limpiar todo
rm -rf build/ *.so __pycache__/

# Compilar
python setup.py build_ext --inplace

# Copiar al directorio principal
cp dsp_core*.so ../

# Verificar desde el directorio principal
cd ~/sdr_analyzer
python -c "
import dsp_core
print('✅ dsp_core importado desde:', dsp_core.__file__)
print('✅ FFTProcessor:', hasattr(dsp_core, 'FFTProcessor'))
"
